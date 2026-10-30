#!/usr/bin/env python3
"""
Capture the Dark Lord costume/aspect list from the Select Dark Lord screen.

Run this, then open the in-game "Select Dark Lord" screen and keep it open.
The tool waits for `MawangSelectUIContents` to appear, then dumps every skin
slot's key plus any readable label, and writes tools/mawang_skins.json.
"""

import json
import os
import sys
import time

import dw_android

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'mawang_skins.json')

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
  function listItems(list) {
    const items = list.add(0x10).readPointer();
    const size = list.add(0x18).readS32();
    const out = [];
    for (let i = 0; i < size; i++) out.push(items.add(0x20).add(i * 8).readPointer());
    return out;
  }
  function textOf(comp) {
    if (!comp || comp.isNull()) return null;
    for (const off of [0x38, 0x40, 0x48, 0x50, 0x30]) {
      const s = str(safe(() => comp.add(off).readPointer(), null));
      if (s && s.length < 80) return s;
    }
    return null;
  }
  function spriteName(image) {
    if (!image || image.isNull()) return null;
    const sp = safe(() => image.add(0x48).readPointer(), null);
    if (!sp || sp.isNull()) return null;
    for (const off of [0x20, 0x18, 0x28]) {
      const s = str(safe(() => sp.add(off).readPointer(), null));
      if (s && s.length < 80) return s;
    }
    return null;
  }
  setTimeout(function () {
    const kl = findKlass('MawangSelectUIContents');
    if (!kl) { send({ status: 'no-class' }); return; }
    const p = ptrPat(kl);
    let inst = null;
    for (const r of Process.enumerateRanges('rw-')) {
      let hs = []; try { hs = Memory.scanSync(r.base, r.size, p); } catch (e) { continue; }
      if (hs.length) { inst = hs[0].address; break; }
    }
    if (!inst) { send({ status: 'no-instance' }); return; }
    const out = { status: 'ok', slots: [], selected: safe(() => inst.add(0xA0).readS32(), null) };
    const nameComp = safe(() => inst.add(0x70).readPointer(), null);
    out.skin_name = textOf(nameComp);
    const slotsPtr = safe(() => inst.add(0x90).readPointer(), null);
    if (slotsPtr && !slotsPtr.isNull()) {
      for (const s of listItems(slotsPtr)) {
        const key = safe(() => s.add(0x38).readS32(), null);
        const icon = safe(() => s.add(0x20).readPointer(), null);
        out.slots.push({ key: key, sprite: spriteName(icon) });
      }
    }
    send(out);
  }, 0);
})();
"""


def run(timeout=600, log=print):
    dev = dw_android.frida_device(None)
    pid = None
    for p in dev.enumerate_processes():
        if p.name == 'DungeonWithin':
            pid = p.pid
            break
    if pid is None:
        raise RuntimeError('game is not running')
    start = time.time()
    while time.time() - start < timeout:
        session = dev.attach(pid)
        state = {}

        def on_message(msg, data):
            if msg['type'] == 'send':
                state.update(msg['payload'])

        script = session.create_script(JS)
        script.on('message', on_message)
        script.load()
        time.sleep(8)
        try:
            session.detach()
        except Exception:
            pass
        if state.get('status') == 'ok':
            json.dump(state, open(OUT, 'w', encoding='utf-8'), indent=1)
            log('captured: %s' % json.dumps(state, ensure_ascii=False)[:400])
            return state
        log('waiting for the Select Dark Lord screen (status=%s)' % state.get('status'))
        time.sleep(4)
    return None


if __name__ == '__main__':
    r = run()
    print('result:', 'ok' if r else 'nothing captured')
    sys.exit(0 if r else 1)
