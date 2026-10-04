#!/usr/bin/env python3
"""Disposable smoke fixture client, NOT a runtime unlock mechanism.

GNOME 50 --unlock starts another daemon; use the existing daemon's private
control request, as PAM does. Protocol: upstream 50.0 daemon/control/
gkd-control-{client,server}.c, gkd-control-codes.h and egg/egg-buffer.c.
Linux SO_PEERCRED authenticates the one-byte credentials preamble. Password
is read from stdin only; nothing is logged or persisted by this helper.
"""
import os
import socket
import stat
import struct
import sys


def unlock(path, password, expected):
    if not password or len(password) > 8192:
        raise ValueError("fixture requires a nonempty bounded password")
    info = os.lstat(path)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError("control must be a same-user, non-symlink socket")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(10)
        peer.connect(path)
        # uint32 network byte order: packet size, UNLOCK=1, string byte count.
        peer.sendall(b"\0" + struct.pack("!III", 12 + len(password), 1, len(password)) + password)
        reply = b""
        while len(reply) < 8:
            chunk = peer.recv(8 - len(reply))
            if not chunk:
                raise ValueError("truncated control response")
            reply += chunk
        size, result = struct.unpack("!II", reply)
        if size != 8 or result != expected:
            raise ValueError("unexpected control result")


if __name__ == "__main__":
    try:
        expected = {"ok": 0, "denied": 1}[sys.argv[1]]
        unlock(os.path.join(os.environ["GNOME_KEYRING_CONTROL"], "control"),
               sys.stdin.buffer.read(8193), expected)
    except (OSError, ValueError, KeyError, IndexError) as error:
        sys.exit("keyring fixture unlock failed: " + str(error))
