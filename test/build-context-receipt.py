"""Bounded receipt for path-context inputs, before build-push-action."""
import hashlib
import json
import os
import pathlib
import stat
import subprocess

def receipt(root, name, context, dockerfile, expected):
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
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(8192), b''): digest.update(chunk)
        return {'path': str(p.relative_to(root)), 'sha256': digest.hexdigest(), 'mode': oct(stat.S_IMODE(info.st_mode))}
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, timeout=5, text=True).strip()
    if sha != expected: raise ValueError('build context source mismatch')
    result = {'image': name[:64], 'actionContext': context, 'actionDockerfile': dockerfile or '(default Dockerfile)',
              'resolvedContext': str(folder.relative_to(root)), 'source': sha, 'actionCheckoutRef': expected, 'dockerfile': file_info(buildfile)}
    specific = pathlib.Path(str(buildfile) + '.dockerignore')
    ignore = specific if specific.exists() else folder / '.dockerignore'
    if ignore.exists(): result['effectiveIgnore'] = file_info(ignore)
    else: result['effectiveIgnore'] = None
    if name == 'mcp-js': result['startScript'] = file_info(folder / 'start.sh')
    return result

if __name__ == '__main__':
    try:
        print(json.dumps(receipt('.', os.environ['BUILD_NAME'], os.environ['BUILD_CONTEXT'],
                                 os.environ.get('BUILD_FILE', ''), os.environ['EXPECTED_SOURCE']), sort_keys=True))
    except (OSError, ValueError, subprocess.SubprocessError):
        raise SystemExit('build context receipt unavailable or invalid')
