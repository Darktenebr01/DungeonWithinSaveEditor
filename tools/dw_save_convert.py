#!/usr/bin/env python3
"""
dw_save_convert.py - convert an encrypted save.es3 into the plain ES3 JSON form.

It spawns the game (unpatched), hooks ES3Saver.DecryptAndDecompress and writes
the returned plaintext (the ES3 JSON document) to a local file.  Push that file
to the save path and launch the game through dw_save_launch.py to play with a
plain, editable save.

The RVA is for the x86_64 build v0.7.0 (b.209).  Other builds need their own
offset (see docs/SAVE_EDITOR.md).
"""

import argparse
import json
import subprocess
import sys
import time

DEFAULT_DEC_RVA = 0x3453fa3
DEFAULT_PACKAGE = 'com.GameCoaster.DungeonWithin'
DEFAULT_ENDPOINT = '127.0.0.1:27042'

JS = r"""
const DEC = %d;
let done = false;
const t = setInterval(() => {
  const mod = Process.findModuleByName('libil2cpp.so');
  if (!mod) return;
  clearInterval(t);
  try {
    Interceptor.attach(mod.base.add(DEC), {
      onLeave(ret) {
        if (done || ret.isNull()) return;
        try {
          const len = ret.add(0x18).readS32();
          if (len < 4096) return;
          done = true;
          send({ len: len }, ret.add(0x20).readByteArray(len));
        } catch (e) { send({ err: '' + e }); }
      }
    });
    send({ hooked: true, base: mod.base.toString() });
  } catch (e) { send({ err: '' + e }); }
}, 20);
"""


def convert_save(endpoint=None, dec_rva=None, timeout=45, package=DEFAULT_PACKAGE,
                 adb=None, serial=None, log=print):
    """Run the game once and capture the decrypted save bytes.

    dec_rva may be omitted: it is resolved automatically for the connected
    device/build and cached (see dw_methods).
    Returns the plaintext bytes, or raises RuntimeError on failure.
    """
    if adb and endpoint:
        port = endpoint.split(':')[-1]
        cmd = [adb]
        if serial:
            cmd += ['-s', serial]
        cmd += ['forward', 'tcp:%s' % port, 'tcp:%s' % port]
        subprocess.run(cmd, check=False, capture_output=True)

    if dec_rva is None:
        import dw_methods
        dec_rva, _enc, _info = dw_methods.ensure_rvas(adb, serial, endpoint, log=log)

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
    script = session.create_script(JS % int(dec_rva))
    state = {'data': None}

    def on_message(msg, data):
        if msg['type'] == 'send':
            p = msg['payload']
            log(str(p))
            if data is not None and state['data'] is None:
                state['data'] = bytes(data)
                log('captured plaintext: %d bytes' % len(data))
        else:
            log('script error: %s' % msg.get('description'))

    script.on('message', on_message)
    script.load()
    dev.resume(pid)

    deadline = time.time() + timeout
    while time.time() < deadline and state['data'] is None:
        time.sleep(0.3)
    if state['data'] is None:
        raise RuntimeError('no save decrypted within %ds (is save.es3 present on the device?)' % timeout)
    return state['data']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--endpoint', default=None, help='frida endpoint; omit to use USB')
    ap.add_argument('--package', default=DEFAULT_PACKAGE)
    ap.add_argument('--out', required=True)
    ap.add_argument('--adb', default=None)
    ap.add_argument('--serial', default=None)
    ap.add_argument('--timeout', type=int, default=45)
    args = ap.parse_args()
    data = convert_save(endpoint=args.endpoint, timeout=args.timeout, package=args.package,
                        adb=args.adb, serial=args.serial, log=print)
    open(args.out, 'wb').write(data)
    print('wrote %s %d' % (args.out, len(data)))
    return 0


if __name__ == '__main__':
    sys.exit(main())