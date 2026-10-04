"""Write only an owned regular diagnostic inode; refuse links/foreign files."""
import os
import stat

def write_private_json(path, payload):
    # Never truncate before checking the descriptor's type and owner.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise OSError('unsafe diagnostic inode')
        os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        with os.fdopen(fd, 'w') as output:
            fd = -1
            output.write(payload)
    finally:
        if fd != -1: os.close(fd)
