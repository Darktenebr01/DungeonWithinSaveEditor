#!/usr/bin/env python3
"""
Encrypt a plain save into a legitimate ES3E container using the game itself.

The routine does not rely on the game loading our file (cloud/device conflict can
interfere).  Instead:

  1. the plain JSON is minified and pushed to a side file on the device,
  2. the game is started and `ES3Saver.DecryptAndDecompress` is hooked (no
     replacement) - it runs on a game thread and returns a large plaintext
     buffer (the game's own save, from cloud or device),
  3. that buffer is overwritten in place with our JSON (padded with spaces),
  4. the real `CompressAndEncrypt` is called on the same thread and the
     ciphertext is written to save.es3 with libc,
  5. the game is stopped and the result is decrypted again to verify it matches
     the edited save.

The output is a normal encrypted save (ES3E) - the same kind the game uploads.
"""

import hashlib
import json
import os
import re
import sys
import time

import dw_android as android
import dw_methods

SIDE_NAME = '_dw_encrypt.json'

JS_FILL_AND_ENCRYPT = r"""
(function () {
  const DEC = 0x%(dec)s, ENC = 0x%(enc)s;
  const NEED = %(need)d;
  let installed = false;
  const t = setInterval(function () {
    const mod = Process.findModuleByName('libil2cpp.so');
    if (!mod || installed) return;
    installed = true;
    clearInterval(t);
    const decFn = mod.base.add(DEC);
    const encFn = mod.base.add(ENC);
    const Fopen = new NativeFunction(Module.getGlobalExportByName('fopen'), 'pointer', ['pointer', 'pointer']);
    const Fread = new NativeFunction(Module.getGlobalExportByName('fread'), 'size_t', ['pointer', 'size_t', 'size_t', 'pointer']);
    const Fwrite = new NativeFunction(Module.getGlobalExportByName('fwrite'), 'size_t', ['pointer', 'size_t', 'size_t', 'pointer']);
    const Fclose = new NativeFunction(Module.getGlobalExportByName('fclose'), 'int', ['pointer']);
    const Fseek = new NativeFunction(Module.getGlobalExportByName('fseek'), 'int', ['pointer', 'long', 'int']);
    const Ftell = new NativeFunction(Module.getGlobalExportByName('ftell'), 'long', ['pointer']);
    const src = Memory.allocUtf8String('%(side)s');
    const dst = Memory.allocUtf8String('%(path)s');
    let payload = null, plen = 0;
    try {
      const f = Fopen(src, Memory.allocUtf8String('rb'));
      Fseek(f, 0, 2); plen = Number(Ftell(f)); Fseek(f, 0, 0);
      payload = Memory.alloc(plen);
      Fread(payload, 1, plen, f);
      Fclose(f);
      send({ loaded: plen });
    } catch (e) { send({ loadErr: '' + e }); }
    let done = false;
    Interceptor.attach(decFn, {
      onLeave(ret) {
        try {
          if (done || !payload || ret.isNull()) return;
          const len = ret.add(0x18).readS32();
          if (len < NEED || len < 50000) { send({ skip: len }); return; }
          const dstp = ret.add(0x20);
          for (let off = 0; off < plen - 1; off += 8192) {
            dstp.add(off).writeByteArray(new Uint8Array(payload.add(off).readByteArray(Math.min(8192, plen - 1 - off))));
          }
          for (let off = plen - 1; off < len - 1; off += 8192) {
            const n = Math.min(8192, len - 1 - off);
            dstp.add(off).writeByteArray(new Uint8Array(n).fill(0x20));
          }
          dstp.add(len - 1).writeU8(0x7d);
          ret.add(0x18).writeS32(len);
          const Enc = new NativeFunction(encFn, 'pointer', ['pointer', 'pointer']);
          const cipher = Enc(ret, ret);
          const clen = cipher.add(0x18).readS32();
          const f = Fopen(dst, Memory.allocUtf8String('wb'));
          if (f.isNull()) { send({ err: 'fopen write failed' }); return; }
          Fwrite(cipher.add(0x20), 1, clen, f);
          Fclose(f);
          done = true;
          send({ encrypted: clen, buffer: len });
        } catch (e) { send({ err: '' + e }); }
      }
    });
    send({ hooked: true });
  }, 5);
})();
"""


def minify(text):
    out = []
    in_str = False
    esc = False
    for c in text:
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            out.append(c)
        elif c in ' \t\r\n':
            continue
        else:
            out.append(c)
    return ''.join(out)


def _uid(adb, serial):
    rc, out, _ = android.adb(adb, serial, 'shell', 'dumpsys', 'package', android.PACKAGE, timeout=20)
    m = re.search(r'userId=(\d+)', out or '')
    return m.group(1) if m else None


def encrypt_plain(plain_path, adb=None, serial=None, endpoint=None, log=print, timeout=90,
                  verify=True):
    adb = adb or android.find_adb()
    if not adb:
        raise RuntimeError('adb not found')
    devs = android.devices(adb)
    if not devs:
        raise RuntimeError('no adb device attached')
    serial = serial if serial in devs else devs[0]
    remote = android.find_save_path(adb, serial)
    if not remote:
        raise RuntimeError('save.es3 not found on the device (start the game once)')
    side = remote.rsplit('/', 1)[0] + '/' + SIDE_NAME

    dec_rva, enc_rva, _info = dw_methods.ensure_rvas(adb, serial, endpoint, log=log)

    text = open(plain_path, encoding='utf-8').read()
    mini = minify(text)
    side_local = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                              'DungeonWithinSaveEditor', 'encrypt_payload.json')
    os.makedirs(os.path.dirname(side_local), exist_ok=True)
    open(side_local, 'w', encoding='utf-8', newline='').write(mini)
    need = len(mini.encode('utf-8'))
    log('payload: %d bytes (minified)' % need)

    rc, out, err = android.push(adb, serial, side_local, side, timeout=120)
    if rc != 0:
        raise RuntimeError('push failed: %s' % (err or out))
    uid = _uid(adb, serial)
    if uid:
        android.adb(adb, serial, 'shell', 'chown', '%s:1078' % uid, side, timeout=15)

    # keep a copy of the current save so a failed attempt can be rolled back
    cache = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'DungeonWithinSaveEditor')
    os.makedirs(cache, exist_ok=True)
    backup = os.path.join(cache, 'encrypt_before.es3')
    android.pull(adb, serial, remote, backup, timeout=120)

    dev = android.frida_device(endpoint)
    try:
        for p in dev.enumerate_processes():
            if p.name == 'DungeonWithin':
                dev.kill(p.pid)
    except Exception:
        pass
    time.sleep(1)
    pid = dev.spawn([android.PACKAGE])
    log('spawned game pid %s' % pid)
    session = dev.attach(pid)
    script = session.create_script(JS_FILL_AND_ENCRYPT % {
        'dec': format(dec_rva, 'x'), 'enc': format(enc_rva, 'x'),
        'need': need, 'side': side, 'path': remote})
    state = {'done': False, 'err': None, 'clen': 0, 'buf': 0}

    def on_message(msg, data):
        if msg['type'] != 'send':
            log('script: %s' % msg.get('description'))
            return
        p = msg['payload']
        if 'hooked' in p or 'loaded' in p or 'loadErr' in p:
            log('script ready: %s' % p)
        if 'skip' in p:
            log('buffer too small (%d), waiting for a bigger one' % p['skip'])
        if p.get('encrypted'):
            state.update(done=True, clen=p['encrypted'], buf=p.get('buffer', 0))
            log('encrypted %d bytes from a %d-byte buffer' % (p['encrypted'], p.get('buffer', 0)))
        elif p.get('err'):
            state['err'] = p['err']
            log('script error: %s' % p['err'])

    script.on('message', on_message)
    script.load()
    dev.resume(pid)

    start = time.time()
    while time.time() - start < timeout and not state['done']:
        time.sleep(1)
    if not state['done']:
        try:
            session.detach()
        except Exception:
            pass
        raise RuntimeError('encryption failed%s' % ((': ' + state['err']) if state['err'] else ' (timeout)'))

    time.sleep(1)
    android.adb(adb, serial, 'shell', 'am', 'force-stop', android.PACKAGE, timeout=20)
    try:
        session.detach()
    except Exception:
        pass
    if uid:
        android.adb(adb, serial, 'shell', 'chown', '%s:1078' % uid, remote, timeout=15)

    head = (android.head(adb, serial, remote, 4) or '').strip()
    if not head.startswith('ES3E'):
        raise RuntimeError('device save is %r, expected ES3E' % head)
    rc, listing, _ = android.adb(adb, serial, 'shell', 'ls', '-l', remote, timeout=15)
    log('encrypted save: %s' % listing.strip())

    result = {'remote': remote, 'head': head, 'listing': listing.strip(), 'cipher_bytes': state['clen']}

    if verify:
        import dw_save_convert as conv
        plain_after = conv.convert_save(endpoint=endpoint, adb=adb, serial=serial, log=log)
        result['roundtrip_bytes'] = len(plain_after)
        a = plain_after.decode('utf-8', 'replace')
        marker = re.search(r'"GOLD"\s*:\s*(-?\d+)', text)
        if marker:
            got = re.search(r'"GOLD"\s*:\s*(-?\d+)', a)
            if not got or got.group(1) != marker.group(1):
                android.push(adb, serial, backup, remote, timeout=120)
                raise RuntimeError('verification failed (GOLD %s != %s); previous save restored'
                                   % (got.group(1) if got else '?', marker.group(1)))
            log('verified: GOLD %s survived' % marker.group(1))
        result['verified'] = True

    return result


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description='Encrypt a plain save with the game itself')
    ap.add_argument('file', help='plain save JSON')
    ap.add_argument('--adb', default=None)
    ap.add_argument('--serial', default=None)
    ap.add_argument('--endpoint', default=None, help='frida endpoint; omit to use USB')
    ap.add_argument('--timeout', type=int, default=90)
    ap.add_argument('--no-verify', action='store_true')
    args = ap.parse_args()
    res = encrypt_plain(args.file, adb=args.adb, serial=args.serial, endpoint=args.endpoint,
                        log=print, timeout=args.timeout, verify=not args.no_verify)
    print('OK', res)
    return 0


if __name__ == '__main__':
    import sys as _sys
    _sys.exit(main())
