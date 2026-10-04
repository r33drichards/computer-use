"""Bounded receipt for path-context inputs, before build-push-action."""
import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess

def receipt(root, name, context, dockerfile, expected, progress=None):
    def mark(stage, **facts):
        if progress: progress(stage, facts)
    mark('context')
    root = pathlib.Path(root).resolve()
    def resolved(value):
        if len(value) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in value): raise ValueError('invalid context path')
        p = root / value
        if p.is_symlink(): raise ValueError('symlink context input')
        p = p.resolve()
        p.relative_to(root)
        return p
    folder = resolved(context)
    if not folder.is_dir(): raise ValueError('context directory unavailable')
    buildfile = resolved(dockerfile) if dockerfile else folder / 'Dockerfile'
    def file_info(p):
        info = p.lstat()
        if not stat.S_ISREG(info.st_mode): raise ValueError('build input not regular')
        if info.st_size > 1048576: raise ValueError('build receipt input byte limit')
        digest = hashlib.sha256()
        with os.fdopen(os.open(p, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode): raise ValueError('build input not regular')
            count = 0
            for chunk in iter(lambda: f.read(8192), b''):
                count += len(chunk)
                if count > 1048576: raise ValueError('build receipt input byte limit')
                digest.update(chunk)
        return {'path': str(p.relative_to(root)), 'sha256': digest.hexdigest(), 'mode': oct(stat.S_IMODE(info.st_mode))}
    mark('source')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, timeout=5, text=True, stderr=subprocess.DEVNULL).strip()
    if not re.fullmatch(r'[0-9a-f]{40}', sha): raise ValueError('invalid source SHA')
    mark('source', actualSource=sha)
    if sha != expected: raise ValueError('build context source mismatch')
    tree = subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=root, timeout=5, text=True, stderr=subprocess.DEVNULL).strip()
    if not re.fullmatch(r'[0-9a-f]{40}', tree): raise ValueError('invalid source tree')
    mark('dockerfile', source=sha, sourceTree=tree, resolvedContext=str(folder.relative_to(root)))
    result = {'image': name[:64], 'actionContext': context, 'actionDockerfile': dockerfile or '(default Dockerfile)',
              'resolvedContext': str(folder.relative_to(root)), 'source': sha, 'sourceTree': tree, 'actionCheckoutRef': expected, 'dockerfile': file_info(buildfile)}
    mark('effective-ignore', dockerfile=result['dockerfile'])
    specific = pathlib.Path(str(buildfile) + '.dockerignore')
    ignore = specific if specific.exists() else folder / '.dockerignore'
    if ignore.exists(): result['effectiveIgnore'] = file_info(ignore)
    else: result['effectiveIgnore'] = None
    if name == 'mcp-js':
        mark('start-script', effectiveIgnore=result['effectiveIgnore'])
        result['startScript'] = file_info(folder / 'start.sh')
    return result


def structured_receipt(root, name, context, dockerfile, expected, run_id='', job='build', test_outcome='unknown'):
    result = {'schemaVersion': 1, 'status': 'error', 'stage': 'inputs'}
    # Only whitelisted public action inputs enter the artifact, never exception text.
    valid = (re.fullmatch(r'[a-z0-9-]{1,64}', name) and
             re.fullmatch(r'[A-Za-z0-9_./-]{1,512}', context) and
             (not dockerfile or re.fullmatch(r'[A-Za-z0-9_./-]{1,512}', dockerfile)) and
             re.fullmatch(r'[0-9a-f]{40}', expected) and
             re.fullmatch(r'[0-9]{0,20}', run_id) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', job))
    if not valid:
        result['reason'] = 'invalid-input'
        return result
    result.update({'image': name, 'actionContext': context, 'actionDockerfile': dockerfile or '(default Dockerfile)',
                   'actionCheckoutRef': expected, 'runId': run_id, 'job': job,
                   'testOutcome': test_outcome if test_outcome in ('success', 'failure', 'skipped', 'cancelled') else 'unknown'})
    def progress(stage, facts):
        result.update(facts)
        result['stage'] = stage
    try:
        result.update(receipt(root, name, context, dockerfile, expected, progress))
        result.update({'status': 'success', 'stage': 'complete'})
    except FileNotFoundError: result['reason'] = 'missing-input'
    except PermissionError: result['reason'] = 'permission-denied'
    except subprocess.TimeoutExpired: result['reason'] = 'source-timeout'
    except subprocess.SubprocessError: result['reason'] = 'source-command-failed'
    except OSError: result['reason'] = 'io-unavailable'
    except ValueError: result['reason'] = 'validation-refused'
    return result

if __name__ == '__main__':
    result = structured_receipt('.', os.environ.get('BUILD_NAME', ''), os.environ.get('BUILD_CONTEXT', ''),
                                os.environ.get('BUILD_FILE', ''), os.environ.get('EXPECTED_SOURCE', ''),
                                os.environ.get('RECEIPT_RUN_ID', ''), os.environ.get('RECEIPT_JOB', 'build'),
                                os.environ.get('RECEIPT_TEST_OUTCOME', 'unknown'))
    payload = json.dumps(result, sort_keys=True)
    # This schema contains a fixed number of bounded paths and hashes.
    if len(payload.encode('utf-8')) > 8192:
        payload = json.dumps({'schemaVersion': 1, 'status': 'error', 'stage': 'serialization', 'reason': 'receipt-byte-limit'})
        result['status'] = 'error'
    destination = os.environ.get('RECEIPT_FILE')
    if destination:
        try:
            path = pathlib.Path(destination)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w') as output: output.write(payload + '\n')
        except OSError:
            payload = json.dumps({'schemaVersion': 1, 'status': 'error', 'stage': 'artifact-write', 'reason': 'receipt-write-failed'})
            result['status'] = 'error'
    print(payload)
    raise SystemExit(0 if result['status'] == 'success' else 1)
