#!/usr/bin/env python3
"""
Capture monster display names from the running game.

Hook `UnitTable.GetName()` (the method the game uses to render a monster name);
every call is recorded as `unitIdx -> name`.  Browse the Monster list (and open
each monster) while this runs, then the editor can show the names.

Writes monster_names.json next to this file; names_dump.json keeps the raw list.
"""

import json
import os
import sys
import time

import dw_android

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = os.path.join(HERE, 'monster_names.json')

JS = r"""
(function () {
  function str(p) { try { return p.isNull() ? null : p.readUtf8String(); } catch (e) { return null; } }
  function hexpat(s) { let p = ''; for (let i = 0; i < s.length; i++) p += (s.charCodeAt(i) & 0xFF).toString(16).padStart(2, '0') + ' '; return p.trim(); }
  function ptrPat(a) { let s = ''; const v = BigInt(a.toString()); for (let i = 0; i < 8; i++) s += Number((v >> BigInt(8 * i)) & 0xFFn).toString(16).padStart(2, '0') + ' '; return s.trim(); }
  function safe(fn, d) { try { return fn(); } catch (e) { return d; } }
  function findKlass(name) {
    const pat = hexpat(name);
    for (const r of Process.enumerateRanges('r--')) {
      let hits = []; try { hits = Memory.scanSync(r.base, r.size, pat); } catch (e) { continue; }
      for (const h of hits) {
        const p = ptrPat(h.address);
        for (const r2 of Process.enumerateRanges('rw-')) {
          let hs = []; try { hs = Memory.scanSync(r2.base, r2.size, p); } catch (e) { continue; }
          for (const m of hs) {
            const k = m.address.sub(0x10);
            if (str(safe(() => k.add(0x10).readPointer(), null)) === name) return k;
          }
        }
      }
    }
    return null;
  }
  setTimeout(function () {
    const kl = findKlass('UnitTable');
    if (!kl) { send({ err: 'UnitTable class not found' }); return; }
    const methods = kl.add(0x98).readPointer();
    let target = null;
    for (let i = 0; i < 400; i++) {
      const mi = safe(() => methods.add(i * 8).readPointer(), null);
      if (!mi || mi.isNull()) continue;
      const nm = str(safe(() => mi.add(0x18).readPointer(), null));
      if (nm === 'GetName') {
        const fn = safe(() => mi.readPointer(), null);
        if (fn && !fn.isNull()) { target = fn; break; }
      }
    }
    if (!target) { send({ err: 'GetName not found in UnitTable' }); return; }
    send({ hooked: true, fn: target.toString() });
    let unitIdx = null;
    Interceptor.attach(target, {
      onEnter(args) {
        try {
          for (const cand of [args[0], args[1]]) {
            if (cand.isNull()) continue;
            const idx = str(cand.add(0x18).readPointer());
            if (idx && /^[A-Z]{3,4}\d{3}/.test(idx)) { unitIdx = idx; return; }
          }
          unitIdx = null;
        } catch (e) { unitIdx = null; }
      },
      onLeave(ret) {
        try {
          if (!unitIdx) return;
          const name = str(ret);
          if (name) send({ unit: unitIdx, name: name });
        } catch (e) {}
        unitIdx = null;
      }
    });
  }, 0);
})();
"""


def capture(timeout=120, log=print, endpoint=None):
    dev = dw_android.frida_device(endpoint)
    pid = None
    for p in dev.enumerate_processes():
        if p.name == 'DungeonWithin':
            pid = p.pid
            break
    if pid is None:
        raise RuntimeError('game is not running')
    session = dev.attach(pid)
    mapping = {}
    state = {'err': None}

    def on_message(msg, data):
        if msg['type'] != 'send':
            return
        p = msg['payload']
        if 'unit' in p:
            mapping[p['unit']] = p['name']
        elif 'err' in p:
            state['err'] = p['err']

    script = session.create_script(JS)
    script.on('message', on_message)
    script.load()
    log('capturing names for %ds - browse the Monster list now' % timeout)
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(2)
        if state['err']:
            break
        if mapping:
            log('captured %d names so far' % len(mapping))
    try:
        session.detach()
    except Exception:
        pass
    if state['err']:
        raise RuntimeError(state['err'])
    if mapping:
        old = {}
        try:
            old = json.load(open(NAMES, encoding='utf-8'))
        except Exception:
            pass
        old.update(mapping)
        json.dump(old, open(NAMES, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        log('saved %d names to %s' % (len(old), NAMES))
    return mapping


def load_names():
    try:
        return json.load(open(NAMES, encoding='utf-8'))
    except Exception:
        return {}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--timeout', type=int, default=120)
    args = ap.parse_args()
    m = capture(timeout=args.timeout, log=print)
    print('captured', len(m))
    return 0


if __name__ == '__main__':
    sys.exit(main())
