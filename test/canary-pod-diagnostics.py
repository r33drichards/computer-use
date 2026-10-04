#!/usr/bin/env python3
"""Read-only diagnostics for one owned canary pod, before session cleanup.
Never dump pod env, Secret objects, auth headers or unrelated resources.
"""
import json
import os
import re
import subprocess


def redact(text):
    text = re.sub(r'bjs_[A-Za-z0-9_-]+', '[redacted]', text)
    text = re.sub(r'(?i)(Bearer|Basic)\s+\S+', r'\1 [redacted]', text)
    text = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[redacted]', text)
    return text


def redact_values(value):
    # Redact values before JSON encoding: token regexes must not eat JSON
    # delimiters when a log ends with an Authorization/token string.
    if isinstance(value, str): return redact(value)
    if isinstance(value, list): return [redact_values(x) for x in value]
    if isinstance(value, dict): return {k: redact_values(v) for k, v in value.items()}
    return value


def command(*args):
    done = subprocess.run(['kubectl', '-n', 'browserjs-sessions', *args],
                          capture_output=True, text=True, timeout=8)
    if done.returncode:
        raise RuntimeError('diagnostic kubectl command failed')
    return done.stdout


def probe(value):
    if not value: return None
    safe = {k: value.get(k) for k in ('periodSeconds', 'failureThreshold', 'timeoutSeconds', 'initialDelaySeconds')}
    if 'httpGet' in value:
        safe['httpGet'] = {k: value['httpGet'].get(k) for k in ('path', 'port', 'scheme')}
    if 'tcpSocket' in value: safe['tcpSocket'] = {'port': value['tcpSocket'].get('port')}
    return safe


def collect(sid):
    if not re.fullmatch(r's-[a-z0-9]{10}', sid):
        raise ValueError('invalid canary session id')
    pod = json.loads(command('get', 'pod', sid, '-o', 'json'))
    meta = pod['metadata']
    if meta['name'] != sid or meta.get('labels', {}).get('app') != 'browserjs-session':
        raise ValueError('not an owned canary pod')
    result = {'pod': sid, 'uid': meta['uid'], 'podSecurityContext': pod['spec'].get('securityContext'),
              'status': pod.get('status'), 'containers': [], 'logs': {}, 'events': []}
    for c in pod['spec']['containers']:
        if c['name'] not in ('browser', 'mcp-js'): continue
        result['containers'].append({k: c.get(k) for k in
            ('name', 'image', 'securityContext')})
        result['containers'][-1].update({k: probe(c.get(k)) for k in ('startupProbe', 'readinessProbe')})
        statuses = pod.get('status', {}).get('containerStatuses', [])
        no_previous = any(x.get('name') == c['name'] and x.get('restartCount') == 0 for x in statuses)
        for previous in (False, True):
            field = c['name'] + ('-previous' if previous else '')
            if previous and no_previous:
                result['logs'][field] = {'status': 'unavailable', 'reason': 'no-previous-container'}
                continue
            try:
                args = ['logs', sid, '-c', c['name'], '--tail=100']
                if previous: args.append('--previous')
                result['logs'][field] = redact(command(*args))
            except subprocess.TimeoutExpired:
                result['logs'][field] = {'status': 'unavailable', 'reason': 'timeout'}
            except RuntimeError:
                result['logs'][field] = {'status': 'error', 'reason': 'command-failed'}
    events = json.loads(command('get', 'events', '--field-selector',
                               'involvedObject.uid=' + meta['uid'], '-o', 'json'))
    result['events'] = [{k: e.get(k) for k in ('reason', 'message', 'type', 'count')}
                        for e in events.get('items', []) if e.get('involvedObject', {}).get('uid') == meta['uid']]
    return json.dumps(redact_values(result), indent=2)


if __name__ == '__main__':
    print(collect(os.environ['SESSION_ID']))
