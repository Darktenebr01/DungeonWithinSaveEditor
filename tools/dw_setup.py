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


def prepare(adb, serial, log=print, wait=15):
    """Push and start frida-server on the device. Returns a status dict."""
    if not adb:
        raise RuntimeError('adb not found')

    rc, out, err = dw_android.adb(adb, serial, 'shell', 'id', timeout=15)
    already_root = rc == 0 and 'uid=0' in (out or '')
    prefix = ''
    if already_root:
        log('adb shell is already root')
    else:
        rc, out, err = dw_android.adb(adb, serial, 'shell', 'su -c id', timeout=15)
        if rc == 0 and 'uid=0' in (out or ''):
            prefix = 'su -c '
            log('using su for root commands')
        else:
            raise RuntimeError(
                'root is required: adb shell is not root and su is unavailable (%s)'
                % ((err or out or '').strip()[:160]))

    def sh(cmd, timeout=20):
        full = prefix + ('"%s"' % cmd if prefix else cmd)
        return dw_android.adb(adb, serial, 'shell', full, timeout=timeout)

    rc, out, err = dw_android.adb(adb, serial, 'shell', 'getprop', 'ro.product.cpu.abi', timeout=15)
    abi = _abi_short(out)
    log('device ABI: %s' % (abi or '?'))

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

        sh('pkill -f frida-server', timeout=15)
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
            rc, out, err = sh('pgrep -f frida-server', timeout=15)
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
