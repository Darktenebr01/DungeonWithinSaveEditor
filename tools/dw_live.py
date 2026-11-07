#!/usr/bin/env python3
"""
dw_live.py - read the save from a running device without the game's convert dance.

The GUI's Active Game page uses this to poll `save.es3`, decrypt it with the
ES3E container module and hand the fresh plaintext to the editor.  It never
writes to the device.
"""

import hashlib
import os
import time

import dw_android as android
import dw_es3

WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'live_pull')


def device_serial(adb_path=None):
    adb = adb_path or android.find_adb()
    if not adb:
        raise RuntimeError('adb not found')
    devs = android.devices(adb)
    if not devs:
        raise RuntimeError('no adb device attached')
    return adb, devs[0]


def game_pid(adb, serial):
    rc, out, _ = android.adb(adb, serial, 'shell', 'pidof', android.PACKAGE, timeout=10)
    pid = (out or '').strip()
    if pid and pid.isdigit():
        return int(pid)
    rc, out, _ = android.adb(adb, serial, 'shell', 'ps', '-A', timeout=10)
    for line in (out or '').splitlines():
        if 'DungeonWithin' in line:
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                return int(parts[1])
    return None


def _pull(adb, serial, remote, local):
    rc, out, err = android.pull(adb, serial, remote, local, timeout=60)
    if rc == 0:
        return
    # A network device can drop between pulls (emulator reboot, plain-mode spawn);
    # reconnect once before reporting the failure.
    if ':' in serial:
        android.adb(adb, serial, 'connect', serial, timeout=20)
        rc, out, err = android.pull(adb, serial, remote, local, timeout=60)
        if rc == 0:
            return
    detail = (err or out or '').strip().replace('\r', ' ')[:200]
    raise RuntimeError('adb pull failed (rc=%s): %s' % (rc, detail or 'no output'))


def pull_plain(adb, serial, remote_path):
    """adb pull the save, decrypt it, return {text, sha256, bytes, container_bytes, pulled_at}."""
    os.makedirs(WORK_DIR, exist_ok=True)
    local = os.path.join(WORK_DIR, 'save.es3')
    _pull(adb, serial, remote_path, local)
    data = open(local, 'rb').read()
    if dw_es3.is_container(data):
        plain = dw_es3.decrypt(data)
    elif data[:1] in (b'{', b'['):
        plain = data
    else:
        raise RuntimeError('unrecognised save container (%d bytes)' % len(data))
    return {
        'text': plain.decode('utf-8', 'replace'),
        'sha256': hashlib.sha256(plain).hexdigest(),
        'bytes': len(plain),
        'container_bytes': len(data),
        'pulled_at': time.time(),
    }
