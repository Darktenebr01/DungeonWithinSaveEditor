#!/usr/bin/env python3
"""
Dump every ability/part key registered by the running game.

Some parts (event/elemental "Ethereal" parts) are not in the static UnitPartsKey
enum, so they are only discoverable at runtime.  This tool attaches to the game,
locates the AbilityTable and UnitPartsTable classes and enumerates their live
instances, writing every key it sees to parts_dump.json (next to this file).
The editor merges that file into its part catalog automatically.
"""

import json
import os
import sys
import time

import dw_android

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP_PATH = os.path.join(HERE, 'parts_dump.json')
CATALOG_PATH = os.path.join(HERE, 'parts_catalog.json')

JS = r"""
(function () {
  function str(p) { try { return p.isNull() ? null : p.readUtf8String(); } catch (e) { return null; } }
  function hexpat(s) { let p = ''; for (let i = 0; i < s.length; i++) p += (s.charCodeAt(i) & 0xFF).toString(16).padStart(2, '0') + ' '; return p.trim(); }
  function ptrPat(a) { let s = ''; const v = BigInt(a.toString()); for (let i = 0; i < 8; i++) s += Number((v >> BigInt(8 * i)) & 0xFFn).toString(16).padStart(2, '0') + ' '; return s.trim(); }
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
            if (str((function(){ try { return k.add(0x10).readPointer(); } catch(e){ return null; } })()) === name) return k;
          }
        }
      }
    }
    return null;
  }
  function enumNames() {
    const out = {};
    // UnitPartsKey / AbilityKey names are not in memory; only values are dumped here.
    return out;
  }
  function scanInstances(klass, field, kind) {
    const p = ptrPat(klass);
    const out = [];
    for (const r of Process.enumerateRanges('rw-')) {
      let hs = []; try { hs = Memory.scanSync(r.base, r.size, p); } catch (e) { continue; }
      for (const m of hs) {
        try {
          const obj = m.address;
          const key = obj.add(field).readS32();
          const path = str(obj.add(0x10).readPointer());
          const origin = str(obj.add(0x20).readPointer());
          if (key >= -1 && key < 100000) out.push({ kind: kind, key: key, path: path, origin: origin });
        } catch (e) {}
      }
    }
    return out;
  }
  const parts = findKlass('UnitPartsTable');
  const abil = findKlass('AbilityTable');
  send({ classes: { parts: parts ? parts.toString() : null, abil: abil ? abil.toString() : null } });
  const res = [];
  if (parts) res.push.apply(res, scanInstances(parts, 0x18, 'part'));
  if (abil) res.push.apply(res, scanInstances(abil, 0x10, 'ability'));
  send({ total: res.length, sample: res.slice(0, 20) });
  send({ all: res });
})();
"""


def dump(log=print, endpoint=None, timeout=120):
    dev = dw_android.frida_device(endpoint)
    pid = None
    for p in dev.enumerate_processes():
        if p.name == 'DungeonWithin':
            pid = p.pid
            break
    if pid is None:
        raise RuntimeError('game is not running - start it once, then dump')
    session = dev.attach(pid)
    script = session.create_script(JS)
    state = {'items': None, 'detail': None, 'classes': None}

    def on_message(msg, data):
        if msg['type'] != 'send':
            return
        p = msg['payload']
        if 'classes' in p:
            state['classes'] = p['classes']
        if 'sample' in p or 'total' in p:
            state['detail'] = p
        if 'all' in p:
            state['items'] = p['all']

    script.on('message', on_message)
    script.load()
    start = time.time()
    while time.time() - start < timeout and state['items'] is None:
        time.sleep(0.5)
    try:
        session.detach()
    except Exception:
        pass
    if state['items'] is None:
        raise RuntimeError('timed out waiting for the game to report its tables')
    log('classes: %s' % state['classes'])
    log('instances: %d' % len(state['items']))
    return state['items']


def main():
    items = dump(log=print)
    keys = sorted({it['path'] for it in items if it.get('path')})
    json.dump({'items': items, 'paths': keys}, open(DUMP_PATH, 'w', encoding='utf-8'), indent=1)
    print('wrote %s (%d items, %d unique paths)' % (DUMP_PATH, len(items), len(keys)))
    # merge any part-looking paths into the catalog
    try:
        cat = set(json.load(open(CATALOG_PATH, encoding='utf-8')))
    except Exception:
        cat = set()
    import re
    pat = re.compile(r'^[A-Z0-9]+(_[A-Z0-9]+)*_[IMS][12]$')
    added = [k for k in keys if pat.match(k) and k not in cat]
    if added:
        cat.update(added)
        json.dump(sorted(cat), open(CATALOG_PATH, 'w', encoding='utf-8'), indent=0)
        print('catalog +%d keys' % len(added))
    return 0


if __name__ == '__main__':
    sys.exit(main())
