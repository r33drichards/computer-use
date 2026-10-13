#!/usr/bin/env python3
"""Read-only diagnostics for one owned canary pod, before session cleanup.
Never dump pod env, Secret objects, auth headers or unrelated resources.
"""
import json
import os
import re
import subprocess
from bounded_process import run_bounded, OutputLimitExceeded

MAX_COMMAND_BYTES = 131072
MAX_EVENTS = 32
MAX_MESSAGE_CHARS = 1024


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
    done = run_bounded(['kubectl', '-n', 'browserjs-sessions', *args],
                       timeout=8, max_bytes=8192 if args[0] == 'logs' else MAX_COMMAND_BYTES)
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
    try:
        pod = json.loads(command('get', 'pod', sid, '-o', 'json'))
    except OutputLimitExceeded:
        return json.dumps({'pod': sid, 'status': 'truncated', 'reason': 'byte-limit'})
    except (subprocess.TimeoutExpired, RuntimeError, ValueError):
        return json.dumps({'pod': sid, 'status': 'unavailable', 'reason': 'pod-metadata-unavailable'})
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
            except OutputLimitExceeded:
                result['logs'][field] = {'status': 'truncated', 'reason': 'byte-limit'}
            except subprocess.TimeoutExpired:
                result['logs'][field] = {'status': 'unavailable', 'reason': 'timeout'}
            except RuntimeError:
                result['logs'][field] = {'status': 'error', 'reason': 'command-failed'}
    try:
        events = json.loads(command('get', 'events', '--field-selector',
                                   'involvedObject.uid=' + meta['uid'], '-o', 'json'))
        owned = [e for e in events.get('items', []) if e.get('involvedObject', {}).get('uid') == meta['uid']]
        result['eventsTruncated'] = len(owned) > MAX_EVENTS
        for e in owned[:MAX_EVENTS]:
            event = {k: e.get(k) for k in ('reason', 'type', 'count')}
            message = redact(str(e.get('message', '')))
            event['messageTruncated'] = len(message) > MAX_MESSAGE_CHARS
            event['message'] = message[:MAX_MESSAGE_CHARS]
            result['events'].append(event)
    except OutputLimitExceeded:
        result['eventsStatus'] = {'status': 'truncated', 'reason': 'byte-limit'}
    except (RuntimeError, subprocess.TimeoutExpired, ValueError):
        result['eventsStatus'] = {'status': 'unavailable', 'reason': 'command-failed'}
    return json.dumps(redact_values(result), indent=2)


if __name__ == '__main__':
    print(collect(os.environ['SESSION_ID']))
