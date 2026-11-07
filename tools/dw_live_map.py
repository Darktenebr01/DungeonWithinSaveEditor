#!/usr/bin/env python3
"""
dw_live_map.py - make every rendered run-map node selectable.

Dungeon Within normally only lets you click a node connected to your current
position.  This tool hooks the run-map UI while the game is running:

  * NodeContainer.ApplyVisuals is called with interactable=false for any node
    the player may not pick; the hook forces that flag to true so every node
    stays clickable.
  * NodesUIContents.OnClickDayTaskSpot normally validates the pick; the hook
    replaces it with a direct call to NodesUIContents._ConfirmDayNode(pin),
    which is the same method the normal flow calls after it accepts a node.

Result: scroll/zoom the map out, click the node you want (boss, treasure, the
last turn) and the run continues from there.  Process-local; nothing is saved
to disk, so restarting the game restores the normal rules.

Usage:
    python -u tools\\dw_live_map.py --attach            # running game
    python -u tools\\dw_live_map.py --spawn --settle 20 # start the game
    python -u tools\\dw_live_map.py --refresh           # ignore the RVA cache
"""

import argparse
import json
import os
import sys
import time

import frida

import dw_android as android

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'live_stats')
CACHE_FILE = os.path.join(CACHE_DIR, 'live_map_rvas.json')

METHODS = [
    ('NodeContainer', 'get_pin'),
    ('NodeContainer', 'ApplyVisuals'),
    ('NodesUIContents', 'OnClickDayTaskSpot'),
    ('NodesUIContents', '_ConfirmDayNode'),
    ('NodesUIContents', 'LoadDayTasks'),
    ('StageData', 'set_dayNodeCursor'),
]

RESOLVE_JS = r"""
(function () {
  var CFG = __CFG__;
  var MOD = null;

  function str(p) { try { return p.isNull() ? null : p.readUtf8String(); } catch (e) { return null; } }
  function hexpat(s) { var p = ''; for (var i = 0; i < s.length; i++) p += (s.charCodeAt(i) & 0xFF).toString(16).padStart(2, '0') + ' '; return p.trim(); }
  function ptrPat(a) { var s = ''; var v = BigInt(a.toString()); for (var i = 0; i < 8; i++) s += Number((v >> BigInt(8 * i)) & 0xFFn).toString(16).padStart(2, '0') + ' '; return s.trim(); }
  function ranges(perm) { var out = []; Process.enumerateRanges(perm).forEach(function (r) { out.push([r.base, r.size]); }); return out; }

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

  function findMethod(cls, method, cb) {
    scanRanges(ranges('r--'), hexpat(method), function (nameHits) {
      if (!nameHits.length) { cb(null); return; }
      var i = 0, MAX = Math.min(nameHits.length, 12);
      function hit() {
        if (i >= MAX) { cb(null); return; }
        var nh = nameHits[i++];
        scanRanges(ranges('rw-'), ptrPat(nh), function (ph) {
          for (var j = 0; j < ph.length; j++) {
            var mi = ph[j].sub(0x18), k = null;
            try { k = mi.add(0x20).readPointer(); } catch (e) { continue; }
            if (k && str(k.add(0x10).readPointer()) === cls) {
              var mp = null; try { mp = mi.readPointer(); } catch (e) { }
              if (mp) { cb(mp); return; }
            }
          }
          hit();
        });
      }
      hit();
    });
  }

  function install(found) {
    var getPin = found['NodeContainer.get_pin'];
    var apply = found['NodeContainer.ApplyVisuals'];
    var onClick = found['NodesUIContents.OnClickDayTaskSpot'];
    var confirm = found['NodesUIContents._ConfirmDayNode'];
    var missing = [];

    if (apply) {
      Interceptor.attach(ptr(apply), {
        onEnter: function (args) {
          // ApplyVisuals(float scale, float alpha, bool interactable, bool isBouncing, bool applyScale)
          args[1] = ptr(1);
        }
      });
    } else missing.push('ApplyVisuals');

    if (onClick && confirm && getPin) {
      var pinFn = new NativeFunction(ptr(getPin), 'pointer', ['pointer']);
      var confirmFn = new NativeFunction(ptr(confirm), 'void', ['pointer', 'pointer']);
      var replaced = new NativeCallback(function (self, clicked) {
        try {
          if (!clicked || clicked.isNull()) return;
          var pin = pinFn(clicked);
          if (pin && !pin.isNull()) confirmFn(self, pin);
        } catch (e) { }
      }, 'void', ['pointer', 'pointer']);
      Interceptor.replace(ptr(onClick), replaced);
    } else {
      if (!onClick) missing.push('OnClickDayTaskSpot');
      if (!confirm) missing.push('_ConfirmDayNode');
      if (!getPin) missing.push('get_pin');
    }
    // Turn jump: NodesUIContents.LoadDayTasks(StageData) runs on the main thread
    // when the map is (re)built; set the stage's day cursor there, before the
    // method body reads it, so the map rebuilds at the requested turn.
    var loadTasks = found['NodesUIContents.LoadDayTasks'];
    var setCursor = found['StageData.set_dayNodeCursor'];
    if (CFG.turn > 0 && loadTasks && setCursor) {
      var setCursorFn = new NativeFunction(ptr(setCursor), 'void', ['pointer', 'int']);
      Interceptor.attach(ptr(loadTasks), {
        onEnter: function (args) {
          try {
            var stage = args[1];
            if (stage && !stage.isNull()) {
              setCursorFn(stage, CFG.turn);
              send({ stage: 'turn-set', turn: CFG.turn });
            }
          } catch (e) { send({ stage: 'turn-error', error: String(e) }); }
        }
      });
    } else if (CFG.turn > 0) {
      missing.push('turn');
    }

    send({ stage: 'ready', missing: missing });
    // Day advances are triggered from the ApplyVisuals hook above (Unity main thread).

  }

  function tryCached() {
    var cached = CFG.cached || {}, found = {}, ready = true;
    CFG.methods.forEach(function (m) {
      var key = m[0] + '.' + m[1], rva = cached[key];
      if (!rva) { ready = false; return; }
      found[key] = MOD.base.add(ptr(rva)).toString();
    });
    if (!ready) return false;
    send({ stage: 'cache', n: Object.keys(found).length });
    install(found);
    return true;
  }

  var idx = 0, found = {};
  function next() {
    if (idx >= CFG.methods.length) { send({ stage: 'resolved', found: found }); install(found); return; }
    var m = CFG.methods[idx++];
    findMethod(m[0], m[1], function (p) {
      found[m[0] + '.' + m[1]] = p ? p.toString() : null;
      send({ stage: 'resolve', key: m[0] + '.' + m[1], ptr: found[m[0] + '.' + m[1]], i: idx, n: CFG.methods.length });
      setTimeout(next, 0);
    });
  }

  function boot() {
    MOD = Process.findModuleByName('libil2cpp.so');
    if (!MOD) { setTimeout(boot, 500); return; }
    send({ stage: 'module', base: MOD.base.toString(), size: MOD.size });
    if (CFG.cached && CFG.cached_size === MOD.size && tryCached()) return;
    setTimeout(next, CFG.settle_ms || 0);
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--attach', action='store_true')
    ap.add_argument('--spawn', action='store_true')
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--settle', type=float, default=25)
    ap.add_argument('--wait', type=float, default=0)
    ap.add_argument('--turn', type=int, default=0, help='set the run day cursor to this turn when the map loads')
    args = ap.parse_args()

    serial, info = device_info()
    key = '%s:%s' % (info.get('version') or 'unknown', info.get('abi') or 'unknown')
    entry = {} if args.refresh else (load_cache().get(key) or {})

    dev = android.frida_device()
    if args.spawn:
        pid = dev.spawn([android.PACKAGE])
        session = dev.attach(pid)
    else:
        pid = find_game_pid(dev)
        if pid is None:
            raise RuntimeError('game is not running (use --spawn)')
        session = dev.attach(pid)

    cfg = {
        'methods': [[c, m] for c, m in METHODS],
        'settle_ms': 0 if (entry.get('rvas') or args.attach) else int(args.settle * 1000),
        'cached': entry.get('rvas') or {},
        'cached_size': entry.get('module_size'),
        'turn': args.turn,
    }
    script = session.create_script(RESOLVE_JS.replace('__CFG__', json.dumps(cfg)))
    state = {'ready': False, 'found': {}, 'base': None, 'size': None, 'missing': []}

    def on_message(msg, data):
        if msg['type'] != 'send':
            print('frida:', msg.get('description'), flush=True)
            return
        p = msg['payload']
        st = p.get('stage')
        if st == 'module':
            state['base'] = int(p['base'], 16)
            state['size'] = p.get('size')
            print('libil2cpp', p['base'], flush=True)
        elif st == 'cache':
            print('using cached RVAs (%d methods)' % p.get('n'), flush=True)
        elif st == 'resolve':
            print('  [%d/%d] %-32s %s' % (p['i'], p['n'], p['key'], ('ok ' + (p['ptr'] or '')) if p['ptr'] else 'MISSING'), flush=True)
        elif st == 'resolved':
            state['found'] = p['found']

        elif st == 'turn-set':
            print('day cursor -> %s' % p.get('turn'), flush=True)
        elif st == 'turn-error':
            print('turn set error:', p.get('error'), flush=True)
        elif st == 'ready':
            state['ready'] = True
            state['missing'] = p.get('missing') or []
            print('map hook ready; missing=%s' % state['missing'], flush=True)

        elif st == 'error':
            print('ERROR:', p.get('error'), flush=True)

    script.on('message', on_message)
    script.load()
    if args.spawn:
        print('spawned pid', pid, flush=True)
        dev.resume(pid)

    deadline = time.time() + 300
    while time.time() < deadline and not state['ready']:
        time.sleep(1)
    if not state['ready']:
        print('map hook failed to install', flush=True)
        session.detach()
        return 1

    if state['found'] and state['base']:
        cache = load_cache()
        rvas = {k: hex(int(v, 16) - state['base']) for k, v in state['found'].items() if v}
        cache[key] = {'rvas': rvas, 'module_size': state['size'],
                      'found_at': time.strftime('%Y-%m-%d %H:%M:%S')}
        save_cache(cache)
        print('cached %d RVAs for %s' % (len(rvas), key), flush=True)

    print('live. Reopen the run map: every rendered node is now selectable.', flush=True)
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
