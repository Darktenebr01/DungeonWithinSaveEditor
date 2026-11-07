#!/usr/bin/env python3
"""
dw_live_stats.py - live Dark Lord base-stat editor for Dungeon Within (Frida).

Locates UnitTable's stat getters by their managed names, then overrides their
return values for Dark Lord ("Mawang") unit tables only.  The hook is
process-local: units/runs created after it starts use the boosted base values,
and the save file is never touched.

Resolution strategy:
  * method RVAs are cached per <version>:<abi>; a later start installs the hooks
    from the cache in about a second
  * a cold start scans the metadata once per name group ("Base", "Growth",
    "get_IsMawang") instead of once per method, then matches the MethodInfos
    inside the usage region that held the first hit

Usage:
    python -u tools\\dw_live_stats.py --str 9999 --dex 9999 --con 9999 --int 9999 ^
        --wis 9999 --cha 9999 --hp 999999
    python -u tools\\dw_live_stats.py --attach --str 5000 --wait 600
    python -u tools\\dw_live_stats.py --refresh          # ignore the RVA cache
"""

import argparse
import json
import os
import sys
import time

import frida

import dw_android as android

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'live_stats')
CACHE_FILE = os.path.join(CACHE_DIR, 'live_stats_rvas.json')

STATS = ('Hp', 'Str', 'Dex', 'Con', 'Int', 'Wis', 'Cha')

RESOLVE_JS = r"""
(function () {
  var CFG = __CFG__;
  var MOD = null, usageRange = null;

  function str(p) { try { return p.isNull() ? null : p.readUtf8String(); } catch (e) { return null; } }
  function hexpat(s) { var p = ''; for (var i = 0; i < s.length; i++) p += (s.charCodeAt(i) & 0xFF).toString(16).padStart(2, '0') + ' '; return p.trim(); }
  function ptrPat(a) { var s = ''; var v = BigInt(a.toString()); for (var i = 0; i < 8; i++) s += Number((v >> BigInt(8 * i)) & 0xFFn).toString(16).padStart(2, '0') + ' '; return s.trim(); }
  function ranges(perm) { var out = []; Process.enumerateRanges(perm).forEach(function (r) { out.push([r.base, r.size]); }); return out; }
  function windowOf(addr, before, after) {
    var r = Process.findRangeByAddress(addr);
    if (!r) return null;
    var start = addr.sub(before), end = addr.add(after);
    if (start.compare(r.base) < 0) start = r.base;
    var rEnd = r.base.add(r.size);
    if (end.compare(rEnd) > 0) end = rEnd;
    return [start, end.sub(start)];
  }

  // Chunked scan: yields between 4 MiB blocks so the agent never blocks the game
  // (a full-range scanSync pass wedged the process once).
  function scanRanges(rs, pat, done) {
    var hits = [], ri = 0, off = 0, CHUNK = 4 * 1024 * 1024;
    function step() {
      var budget = 6;
      while (budget-- > 0 && ri < rs.length) {
        var pair = rs[ri], b = pair[0], sz = pair[1];
        var n = Math.min(CHUNK, sz - off);
        if (n > 0) {
          try { var hs = Memory.scanSync(b.add(off), n, pat); for (var i = 0; i < hs.length; i++) hits.push(hs[i].address); } catch (e) { }
          off += n;
        }
        if (off >= sz) { ri++; off = 0; }
      }
      if (ri < rs.length) setTimeout(step, 0); else done(hits);
    }
    setTimeout(step, 0);
  }

  // The game's method-name strings live concatenated in the metadata blob; the
  // pointer stored in MethodInfo points straight at the first character, so a
  // token hit is matched by comparing the bytes that precede the token.
  function bytesEqual(addr, text) {
    try {
      var b = addr.readByteArray(text.length);
      if (!b) return false;
      var u = new Uint8Array(b);
      for (var i = 0; i < text.length; i++) {
        if (u[i] !== (text.charCodeAt(i) & 0xFF)) return false;
      }
      return true;
    } catch (e) { return false; }
  }

  function collectNames(token, wanted, cb) {
    scanRanges(ranges('r--'), hexpat(token), function (hits) {
      var out = {};
      for (var i = 0; i < hits.length; i++) {
        for (var w = 0; w < wanted.length; w++) {
          var name = wanted[w];
          if (out[name]) continue;
          var off = name.length - token.length;
          if (off < 0) continue;
          var start = hits[i].sub(off);
          if (bytesEqual(start, name)) out[name] = start;
        }
      }
      cb(out);
    });
  }

  function resolveName(name, addr, scoped, cb) {
    var ur = scoped && usageRange ? [usageRange] : ranges('rw-');
    scanRanges(ur, ptrPat(addr), function (ph) {
      for (var j = 0; j < ph.length; j++) {
        var mi = ph[j].sub(0x18), k = null;
        try { k = mi.add(0x20).readPointer(); } catch (e) { continue; }
        if (k && str(k.add(0x10).readPointer()) === 'UnitTable') {
          var mp = null; try { mp = mi.readPointer(); } catch (e) { }
          if (mp) {
            if (!usageRange) usageRange = windowOf(ph[j], 8 * 1024 * 1024, 8 * 1024 * 1024);
            cb(mp); return;
          }
        }
      }
      if (scoped && usageRange) { resolveName(name, addr, false, cb); return; }
      cb(null);
    });
  }

  function install(found) {
    var isPtr = found['UnitTable.get_IsMawang'];
    if (!isPtr) { send({ stage: 'error', error: 'UnitTable.get_IsMawang not resolved' }); return; }
    var isMawang = new NativeFunction(ptr(isPtr), 'uchar', ['pointer']);
    var overrides = CFG.overrides || {};
    var hooked = [], missing = [];
    Object.keys(overrides).forEach(function (name) {
      var p = found['UnitTable.' + name];
      if (!p) { missing.push(name); return; }
      var value = overrides[name];
      Interceptor.attach(ptr(p), {
        onEnter: function (args) { this.self = args[0]; },
        onLeave: function (ret) {
          try {
            if (!this.self || this.self.isNull()) return;
            if (isMawang(this.self) === 0) return;
            ret.replace(value);
          } catch (e) { }
        }
      });
      hooked.push(name);
    });
    send({ stage: 'hooked', hooked: hooked, missing: missing, overrides: overrides });
  }

  function tryCached() {
    var cached = CFG.cached || {};
    var found = {}, ready = true;
    CFG.methods.forEach(function (m) {
      var key = m.cls + '.' + m.method;
      var rva = cached[key];
      if (!rva) { ready = false; return; }
      found[key] = MOD.base.add(ptr(rva)).toString();
    });
    if (!ready) return false;
    send({ stage: 'cache', used: true, n: Object.keys(found).length });
    install(found);
    return true;
  }

  function resolveAll() {
    var wanted = CFG.methods.map(function (m) { return m.method; });
    var groups = [], base = [], growth = [], other = [];
    wanted.forEach(function (n) {
      if (/Base$/.test(n)) base.push(n);
      else if (/Growth$/.test(n)) growth.push(n);
      else other.push(n);
    });
    if (base.length) groups.push({ token: 'Base', names: base });
    if (growth.length) groups.push({ token: 'Growth', names: growth });
    if (other.length) groups.push({ token: 'IsMawang', names: other });

    var addrs = {}, pending = groups.length || 1;
    groups.forEach(function (g) {
      collectNames(g.token, g.names, function (map) {
        Object.keys(map).forEach(function (k) { addrs[k] = map[k]; });
        if (--pending === 0) afterNames(addrs, wanted);
      });
    });
    if (!groups.length) afterNames(addrs, wanted);
  }

  function afterNames(addrs, wanted) {
    var found = {}, i = 0;
    function step() {
      if (i >= wanted.length) {
        send({ stage: 'resolved', found: found });
        install(found);
        return;
      }
      var name = wanted[i++], addr = addrs[name];
      var done = function (mp) {
        found['UnitTable.' + name] = mp ? mp.toString() : null;
        send({ stage: 'resolve', key: 'UnitTable.' + name, ptr: found['UnitTable.' + name], i: i, n: wanted.length });
        setTimeout(step, 0);
      };
      if (!addr) { done(null); return; }
      resolveName(name, addr, !!usageRange, done);
    }
    step();
  }

  function boot() {
    MOD = Process.findModuleByName('libil2cpp.so');
    if (!MOD) { setTimeout(boot, 500); return; }
    send({ stage: 'module', base: MOD.base.toString(), size: MOD.size });
    if (CFG.cached && CFG.cached_size === MOD.size && tryCached()) return;
    setTimeout(resolveAll, (CFG.settle_ms || 0));
  }
  boot();
})();
"""


def load_cache():
    try:
        return json.load(open(CACHE_FILE, encoding='utf-8'))
    except Exception:
        return {}


def save_cache(cache):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=1)
    except Exception as e:
        print('cache not saved:', e, flush=True)


def device_info():
    adb_path = android.find_adb()
    if not adb_path:
        raise RuntimeError('adb not found')
    devs = android.devices(adb_path)
    if not devs:
        raise RuntimeError('no adb device')
    return devs[0], android.device_info(adb_path, devs[0])


def find_game_pid(dev):
    for p in dev.enumerate_processes():
        if p.name == 'DungeonWithin':
            return p.pid
    return None


def build_overrides(args):
    over = {}
    pairs = [('Hp', args.hp), ('Str', args.str), ('Dex', args.dex), ('Con', args.con),
             ('Int', args.int), ('Wis', args.wis), ('Cha', args.cha)]
    for name, value in pairs:
        if value is None:
            continue
        over['Get%sBase' % name] = int(value)
        if args.growth is not None:
            over['Get%sGrowth' % name] = int(args.growth)
    return over


def main():
    ap = argparse.ArgumentParser()
    for name in ('hp', 'str', 'dex', 'con', 'int', 'wis', 'cha'):
        ap.add_argument('--' + name, type=int, default=None)
    ap.add_argument('--growth', type=int, default=None)
    ap.add_argument('--attach', action='store_true')
    ap.add_argument('--clear', action='store_true')
    ap.add_argument('--refresh', action='store_true', help='ignore cached RVAs')
    ap.add_argument('--wait', type=float, default=0)
    ap.add_argument('--settle', type=float, default=0,
                    help='only used when spawning: seconds to let the game load before scanning')
    args = ap.parse_args()

    overrides = {} if args.clear else build_overrides(args)
    if not overrides and not args.clear:
        ap.error('give at least one stat value or --clear')

    methods = [{'cls': 'UnitTable', 'method': 'get_IsMawang'}]
    for name in STATS:
        methods.append({'cls': 'UnitTable', 'method': 'Get%sBase' % name})
        if args.growth is not None:
            methods.append({'cls': 'UnitTable', 'method': 'Get%sGrowth' % name})

    serial, info = device_info()
    key = '%s:%s' % (info.get('version') or 'unknown', info.get('abi') or 'unknown')
    entry = {} if args.refresh else (load_cache().get(key) or {})

    dev = android.frida_device()
    if args.attach:
        pid = find_game_pid(dev)
        if pid is None:
            raise RuntimeError('game is not running')
        session = dev.attach(pid)
    else:
        pid = dev.spawn([android.PACKAGE])
        session = dev.attach(pid)

    settle_ms = 0
    if not entry.get('rvas') and not args.attach:
        settle_ms = int(args.settle * 1000)
    cfg = {
        'methods': methods,
        'overrides': overrides,
        'settle_ms': settle_ms,
        'cached': entry.get('rvas') or {},
        'cached_size': entry.get('module_size'),
    }
    script = session.create_script(RESOLVE_JS.replace('__CFG__', json.dumps(cfg)))
    state = {'hooked': False, 'found': {}, 'base': None, 'size': None}

    def on_message(msg, data):
        if msg['type'] != 'send':
            print('frida:', msg.get('description'), flush=True)
            return
        p = msg['payload']
        stage = p.get('stage')
        if stage == 'module':
            state['base'] = int(p['base'], 16)
            state['size'] = p.get('size')
            print('libil2cpp', p['base'], 'size', p.get('size'), flush=True)
        elif stage == 'cache':
            print('using cached RVAs (%d methods)' % p.get('n'), flush=True)
        elif stage in ('scan', 'scan-done'):
            pass
        elif stage == 'resolve':
            kind = 'ok' if p['ptr'] else 'MISSING'
            print('  [%2d/%2d] %-26s %s %s' % (p['i'], p['n'], p['key'], kind, p['ptr'] or ''), flush=True)
        elif stage == 'resolved':
            state['found'] = p['found']
        elif stage == 'hooked':
            state['hooked'] = True
            print('hooked %d getters, missing=%s' % (len(p['hooked']), p['missing']), flush=True)
        elif stage == 'error':
            state['error'] = p.get('error')
            print('ERROR:', p.get('error'), flush=True)

    script.on('message', on_message)
    script.load()
    if not args.attach:
        print('spawned pid', pid, flush=True)
        dev.resume(pid)

    deadline = time.time() + 300
    while time.time() < deadline and not state['hooked'] and not state.get('error'):
        time.sleep(1)
    if not state['hooked']:
        print('hook installation failed', flush=True)
        session.detach()
        return 1

    if state['found'] and state['base']:
        cache = load_cache()
        rvas = {}
        for k, absolute in state['found'].items():
            if absolute:
                rvas[k] = hex(int(absolute, 16) - state['base'])
        cache[key] = {
            'rvas': rvas,
            'module_size': state['size'],
            'found_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        save_cache(cache)
        print('cached %d RVAs for %s' % (len(rvas), key), flush=True)

    print('live. Open Dark Lord\'s Quarters / a unit sheet to see the boosted base stats.', flush=True)
    try:
        if args.wait and args.wait > 0:
            time.sleep(args.wait)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    session.detach()
    return 0


if __name__ == '__main__':
    sys.exit(main())
