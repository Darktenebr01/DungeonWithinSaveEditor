#!/usr/bin/env python3
"""
dw_save_launch.py - launch Dungeon Within with ES3Saver's container crypto disabled.

It spawns the game through Frida and replaces

    ES3Saver.CompressAndEncrypt(byte[])   -> identity
    ES3Saver.DecryptAndDecompress(byte[]) -> identity

so that save.es3 is a plain ES3 JSON document (no magic/AES/HMAC).  Edit it with
dw_save_editor.py, then start the game through this launcher again.

Requirements: Android emulator/device with the game installed, frida-server
running, and a working adb.  The RVAs below are for the x86_64 build
v0.7.0 (b.209); other builds need their own offsets (see docs/SAVE_EDITOR.md).

Usage:
    python dw_save_launch.py --endpoint 127.0.0.1:27042
    python dw_save_launch.py --adb "E:\\...\\adb.exe" --serial emulator-5554
"""

import argparse
import json
import subprocess
import sys
import time

DEFAULT_DEC_RVA = 0x3453fa3
DEFAULT_ENC_RVA = 0x34535f8
DEFAULT_PACKAGE = 'com.GameCoaster.DungeonWithin'
DEFAULT_ENDPOINT = '127.0.0.1:27042'

JS = r"""
const DEC = %d, ENC = %d;
let done = false;
function patch() {
  if (done) return true;
  const mod = Process.findModuleByName('libil2cpp.so');
  if (!mod) return false;
  try {
    Interceptor.replace(mod.base.add(DEC), new NativeCallback(function (d) { return d; }, 'pointer', ['pointer']));
    Interceptor.replace(mod.base.add(ENC), new NativeCallback(function (d) { return d; }, 'pointer', ['pointer']));
    done = true;
    send({ replaced: true, base: mod.base.toString(), dec: mod.base.add(DEC).toString(), enc: mod.base.add(ENC).toString() });
  } catch (e) {
    send({ err: '' + e });
  }
  return true;
}
const t = setInterval(() => { if (patch()) clearInterval(t); }, 20);
"""


def launch_patched(endpoint=None, package=DEFAULT_PACKAGE, dec_rva=None,
                   enc_rva=None, adb=None, serial=None, log=print):
    """Spawn the game with container crypto replaced by identity.

    dec_rva/enc_rva may be omitted: they are then resolved automatically for the
    connected device/build and cached (see dw_methods).
    Returns a dict with the live frida objects; keep it alive for as long as the
    game should stay in plain-save mode (closing the session reverts the patch).
    """
    if adb and endpoint:
        port = endpoint.split(':')[-1]
        cmd = [adb]
        if serial:
            cmd += ['-s', serial]
        cmd += ['forward', 'tcp:%s' % port, 'tcp:%s' % port]
        try:
            subprocess.run(cmd, check=False, capture_output=True)
        except Exception as e:
            log('adb forward failed: %s' % e)

    if dec_rva is None or enc_rva is None:
        import dw_methods
        dec_rva, enc_rva, _info = dw_methods.ensure_rvas(adb, serial, endpoint, log=log)

    import dw_android
    dev = dw_android.frida_device(endpoint)
    try:
        for p in dev.enumerate_processes():
            if p.name == 'DungeonWithin':
                dev.kill(p.pid)
    except Exception:
        pass
    time.sleep(1)
    pid = dev.spawn([package])
    log('spawned game pid %s' % pid)
    session = dev.attach(pid)
    script = session.create_script(JS % (int(dec_rva), int(enc_rva)))

    def on_message(msg, data):
        if msg['type'] == 'send':
            log(str(msg['payload']))
        else:
            log('script error: %s' % msg.get('description'))

    script.on('message', on_message)
    script.load()
    dev.resume(pid)
    log('game running with identity save crypto (plain JSON mode)')
    return {'device': dev, 'session': session, 'script': script, 'pid': pid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--endpoint', default=None, help='frida endpoint; omit to use USB')
    ap.add_argument('--package', default=DEFAULT_PACKAGE)
    ap.add_argument('--adb', default=None)
    ap.add_argument('--serial', default=None)
    args = ap.parse_args()
    state = launch_patched(endpoint=args.endpoint, package=args.package, adb=args.adb,
                           serial=args.serial, log=print)
    print('launched pid %s - keep this process alive while playing (Ctrl+C to stop)' % state['pid'])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())