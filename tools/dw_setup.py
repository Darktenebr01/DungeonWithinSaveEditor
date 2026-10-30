"""Zero-install device preparation: bundled adb + frida-server push/start."""

import glob
import lzma
import os
import shutil
import sys
import tempfile
import time

import dw_android

REMOTE = '/data/local/tmp/frida-server'


def app_roots():
    roots = []
    if getattr(sys, 'frozen', False):
        roots.append(os.path.dirname(sys.executable))
    base = getattr(sys, '_MEIPASS', None)
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    roots.append(os.getcwd())
    return roots


def bundled_adb():
    for root in app_roots():
        p = os.path.join(root, 'vendor', 'platform-tools', 'adb.exe')
        if os.path.exists(p):
            return p
    return None


def bundled_server(abi):
    pattern_names = {
        'x86_64': '*-android-x86_64.xz',
        'arm64': '*-android-arm64.xz',
        'arm': '*-android-arm.xz',
        'x86': '*-android-x86.xz',
    }
    pat = pattern_names.get(abi)
    if not pat:
        return None
    for root in app_roots():
        hits = sorted(glob.glob(os.path.join(root, 'vendor', 'frida', pat)))
        if hits:
            return hits[-1]
    return None


def _abi_short(abi):
    abi = (abi or '').strip()
    if abi.startswith('arm64'):
        return 'arm64'
    if abi.startswith('x86_64'):
        return 'x86_64'
    if abi.startswith('armeabi') or abi == 'arm':
        return 'arm'
    if abi in ('x86', 'i686'):
        return 'x86'
    return abi


def detect_abi(adb, serial, log=print, tries=15):
    """Read the device ABI, retrying across the adbd restart that `adb root` causes."""
    for i in range(tries):
        rc, out, err = dw_android.adb(adb, serial, 'shell', 'getprop', 'ro.product.cpu.abi', timeout=10)
        if (out or '').strip():
            return _abi_short(out)
        rc, out, err = dw_android.adb(adb, serial, 'shell', 'getprop', 'ro.product.cpu.abilist', timeout=10)
        if (out or '').strip():
            return _abi_short(out.strip().split(',')[0])
        rc, out, err = dw_android.adb(adb, serial, 'shell', 'uname -m', timeout=10)
        machine = (out or '').strip()
        if machine:
            return _abi_short({'aarch64': 'arm64', 'armv8l': 'arm', 'x86_64': 'x86_64',
                               'i686': 'x86'}.get(machine, machine))
        try:
            dw_android.adb(adb, serial, 'wait-for-device', timeout=10)
        except Exception:
            pass
        time.sleep(1)
        if i % 3 == 0:
            log('waiting for the device to come back after adbd restart (%d/%d)' % (i + 1, tries))
    return ''


def prepare(adb, serial, log=print, wait=15):
    """Push and start frida-server on the device. Returns a status dict."""
    if not adb:
        raise RuntimeError('adb not found')

    rc, out, err = dw_android.adb(adb, serial, 'shell', 'id', timeout=15)
    already_root = rc == 0 and 'uid=0' in (out or '')
    prefix = ''
    if not already_root:
        # most emulators expose root through adbd (`adb root`) rather than su
        rc_root, out_root, err_root = dw_android.adb(adb, serial, 'root', timeout=20)
        log('adb root: %s' % ((out_root or err_root or '').strip()[:120] or ('rc=%d' % rc_root)))
        try:
            dw_android.adb(adb, serial, 'wait-for-device', timeout=20)
        except Exception:
            pass
        time.sleep(1)
        rc, out, err = dw_android.adb(adb, serial, 'shell', 'id', timeout=15)
        already_root = rc == 0 and 'uid=0' in (out or '')

    if already_root:
        log('adb shell is root')
    else:
        rc, out, err = dw_android.adb(adb, serial, 'shell', 'su -c id', timeout=15)
        if rc == 0 and 'uid=0' in (out or ''):
            prefix = 'su -c '
            log('using su for root commands')
        else:
            raise RuntimeError(
                'root is required. Enable root in the emulator settings (MuMu: Settings -> Root '
                'permission; LDPlayer: Settings -> Root), or use a rooted phone. '
                'adb root also failed: %s'
                % ((out_root or err_root or '').strip()[:120]))

    def sh(cmd, timeout=20):
        full = prefix + ('"%s"' % cmd if prefix else cmd)
        return dw_android.adb(adb, serial, 'shell', full, timeout=timeout)

    abi = detect_abi(adb, serial, log=log)
    log('device ABI: %s' % (abi or '?'))
    if not abi:
        raise RuntimeError('could not read the device ABI (device not answering after adb root)')

    asset = bundled_server(abi)
    if not asset:
        raise RuntimeError('no bundled frida-server for ABI %r (bundled: x86_64, arm64)' % abi)
    log('using %s' % os.path.basename(asset))

    tmpdir = tempfile.mkdtemp(prefix='dw_frida_')
    local = os.path.join(tmpdir, 'frida-server')
    try:
        with lzma.open(asset, 'rb') as src, open(local, 'wb') as dst:
            shutil.copyfileobj(src, dst)
        os.chmod(local, 0o755)
        log('extracted frida-server (%.1f MB)' % (os.path.getsize(local) / 1048576))

        sh('pkill -9 -f frida', timeout=15)
        rc, out, err = dw_android.adb(adb, serial, 'push', local, REMOTE, timeout=300)
        if rc != 0:
            raise RuntimeError('push failed: %s' % ((err or out or '').strip()[:200]))
        sh('chmod 755 %s' % REMOTE, timeout=15)

        start_cmd = 'nohup %s -D >/dev/null 2>&1 &' % REMOTE
        if prefix:
            start_cmd = 'su -c "%s"' % start_cmd
        dw_android.adb(adb, serial, 'shell', start_cmd, timeout=20)
        log('started frida-server')
        time.sleep(2)

        pid = None
        for _ in range(max(1, wait)):
            rc, out, err = sh('pgrep -f frida', timeout=15)
            if rc == 0 and (out or '').strip():
                pid = (out or '').strip().split()[-1]
                break
            time.sleep(1)
        if not pid:
            raise RuntimeError('frida-server did not stay running')
        log('frida-server running (pid %s)' % pid)
        return {'abi': abi, 'asset': os.path.basename(asset), 'pid': pid}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def frida_running(adb=None, serial=None, timeout=3):
    if adb and serial:
        rc, out, err = dw_android.adb(adb, serial, 'shell', 'pgrep -f frida', timeout=10)
        if rc != 0 or not (out or '').strip():
            return False
    try:
        import frida
    except Exception:
        return False
    try:
        device = frida.get_usb_device(timeout=timeout)
        device.enumerate_processes()
        return True
    except Exception:
        return False


def ensure_frida(adb, serial, log=print):
    """Make sure frida-server answers; start the bundled one if it does not."""
    if frida_running(adb, serial):
        return 'running'
    if not adb or not serial:
        raise RuntimeError('frida-server is not running - press "Prepare device" in the Connection tab first')
    log('frida-server is not running - starting the bundled one...')
    prepare(adb, serial, log=log)
    if not frida_running(adb, serial, timeout=10):
        raise RuntimeError('frida-server started but does not answer; try Prepare device again')
    return 'started'
