#!/usr/bin/env python3
"""
Android / adb / frida helpers used by the save editor.

Everything here is device-agnostic: adb is discovered, the device is chosen from
`adb devices`, and the save path is probed instead of hardcoded.
"""

import os
import shutil
import subprocess
import sys

PACKAGE = 'com.GameCoaster.DungeonWithin'
ACTIVITY = PACKAGE + '/com.unity3d.player.UnityPlayerActivity'
SAVE_NAME = 'save.es3'

ADB_CANDIDATES = (
    r'E:\Program Files\Netease\MuMuPlayer\nx_device\12.0\shell\adb.exe',
    r'C:\Program Files\Netease\MuMuPlayer\nx_device\12.0\shell\adb.exe',
    r'E:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe',
    r'C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe',
    r'C:\LDPlayer\LDPlayer9\adb.exe',
    r'C:\LDPlayer\LDPlayer4.0\adb.exe',
    r'C:\Program Files\BlueStacks_nxt\HD-Adb.exe',
    r'C:\Program Files (x86)\Nox\bin\adb.exe',
    r'C:\Program Files\Genymobile\Genymotion\adb.exe',
)

SAVE_PATH_TEMPLATES = (
    '/sdcard/Android/data/%s/files/' + SAVE_NAME,
    '/storage/emulated/0/Android/data/%s/files/' + SAVE_NAME,
    '/storage/self/primary/Android/data/%s/files/' + SAVE_NAME,
)


def bundled_adb():
    roots = []
    if getattr(sys, 'frozen', False):
        roots.append(os.path.dirname(sys.executable))
    base = getattr(sys, '_MEIPASS', None)
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    roots.append(os.getcwd())
    for root in roots:
        p = os.path.join(root, 'vendor', 'platform-tools', 'adb.exe')
        if os.path.exists(p):
            return p
    return None


def find_adb(override=None):
    if override and os.path.exists(override):
        return override
    bundled = bundled_adb()
    if bundled:
        return bundled
    env = os.environ.get('ADB')
    if env and os.path.exists(env):
        return env
    which = shutil.which('adb')
    if which:
        return which
    sdk = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Android', 'Sdk', 'platform-tools', 'adb.exe')
    if os.path.exists(sdk):
        return sdk
    sdk = os.path.join(os.environ.get('USERPROFILE', ''), 'AppData', 'Local', 'Android', 'Sdk', 'platform-tools', 'adb.exe')
    if os.path.exists(sdk):
        return sdk
    for p in ADB_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def run(adb, args, timeout=30):
    """Run adb with optional -s serial (first element of args may be serial=None)."""
    cmd = [adb] + [a for a in args if a is not None]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or '', r.stderr or ''
    except Exception as e:
        return 1, '', str(e)


def adb(adb_path, serial, *args, timeout=30):
    cmd = ['-s', serial] if serial else []
    return run(adb_path, cmd + list(args), timeout)


def devices(adb_path):
    rc, out, _ = run(adb_path, ['devices'], timeout=15)
    result = []
    for line in out.splitlines()[1:]:
        if '\tdevice' in line:
            result.append(line.split('\t')[0])
    return result


def device_info(adb_path, serial):
    _, abi, _ = adb(adb_path, serial, 'shell', 'getprop', 'ro.product.cpu.abi', timeout=15)
    _, ver, _ = adb(adb_path, serial, 'shell', 'dumpsys', 'package', PACKAGE, timeout=20)
    version = ''
    for line in ver.splitlines():
        line = line.strip()
        if line.startswith('versionName='):
            version = line.split('=', 1)[1].strip()
            break
    return {'abi': (abi or '').strip(), 'version': version, 'serial': serial}


def find_save_path(adb_path, serial):
    """Probe the usual external-files locations and return the first existing save path."""
    candidates = [t % PACKAGE for t in SAVE_PATH_TEMPLATES]
    for path in candidates:
        rc, out, _ = adb(adb_path, serial, 'shell', 'ls', '-l', path, timeout=15)
        if rc == 0 and 'No such file' not in out and out.strip():
            return path
    # last resort: list the app's files dir and look for *.es3
    for base in ('/sdcard/Android/data/%s/files' % PACKAGE,
                 '/storage/emulated/0/Android/data/%s/files' % PACKAGE):
        rc, out, _ = adb(adb_path, serial, 'shell', 'ls', base, timeout=15)
        if rc == 0:
            for name in out.split():
                if name.endswith('.es3'):
                    return base + '/' + name
    return None


def push(adb_path, serial, local, remote, timeout=120):
    return adb(adb_path, serial, 'push', local, remote, timeout=timeout)


def pull(adb_path, serial, remote, local, timeout=120):
    return adb(adb_path, serial, 'pull', remote, local, timeout=timeout)


def head(adb_path, serial, remote, n=1):
    rc, out, _ = adb(adb_path, serial, 'shell', 'head', '-c', str(n), remote, timeout=15)
    return out


PREFS_PATH = '/data/data/%s/shared_prefs/%s.v2.playerprefs.xml' % (PACKAGE, PACKAGE)


def read_prefs(adb_path, serial):
    rc, out, err = adb(adb_path, serial, 'shell', 'cat', PREFS_PATH, timeout=20)
    if rc != 0 or '<map>' not in out:
        raise RuntimeError('cannot read PlayerPrefs (root required): %s' % (err or out))
    return out


def get_player_pref(adb_path, serial, name):
    import xml.etree.ElementTree as ET
    xml = read_prefs(adb_path, serial)
    root = ET.fromstring(xml)
    for node in root:
        if node.get('name') == name:
            return node.get('value') if node.get('value') is not None else node.text
    return None


def set_player_pref(adb_path, serial, name, value, uid=None):
    """Edit one PlayerPrefs entry on the device (root). Stops the game first."""
    import xml.etree.ElementTree as ET
    xml = read_prefs(adb_path, serial)
    root = ET.fromstring(xml)
    found = None
    for node in root:
        if node.get('name') == name:
            found = node
            break
    if found is None:
        found = ET.SubElement(root, 'string', {'name': name})
    found.text = value
    data = ET.tostring(root, encoding='utf-8').decode('utf-8')
    tmp = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                       'DungeonWithinSaveEditor', 'playerprefs.xml')
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    open(tmp, 'w', encoding='utf-8').write(data)
    adb(adb_path, serial, 'shell', 'am', 'force-stop', PACKAGE, timeout=20)
    rc, out, err = adb(adb_path, serial, 'push', tmp, PREFS_PATH, timeout=60)
    if rc != 0:
        raise RuntimeError('push prefs failed: %s' % (err or out))
    if uid:
        adb(adb_path, serial, 'shell', 'chown', '%s:%s' % (uid, uid), PREFS_PATH, timeout=15)
    adb(adb_path, serial, 'shell', 'chmod', '660', PREFS_PATH, timeout=15)
    return value


def frida_device(endpoint=None, timeout=5):
    """Return a frida device: USB first (portable), then an explicit remote endpoint."""
    import frida
    if endpoint:
        try:
            return frida.get_device_manager().add_remote_device(endpoint, timeout=timeout)
        except Exception:
            pass
    try:
        return frida.get_usb_device(timeout=timeout)
    except Exception:
        if endpoint:
            raise
        raise RuntimeError('no frida device: start frida-server on the phone/emulator '
                           '(needs root) or set a remote endpoint')


def list_frida_processes(dev):
    try:
        return [(p.pid, p.name) for p in dev.enumerate_processes()]
    except Exception:
        return []
