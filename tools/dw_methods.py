#!/usr/bin/env python3
"""
Dynamic discovery of ES3Saver.CompressAndEncrypt / DecryptAndDecompress.

Instead of hardcoding an RVA per game build/ABI, the functions are located at
runtime by their managed names: find the method-name string in memory, find the
MethodInfo that points at it, verify MethodInfo->klass->name == "ES3Saver", and
read MethodInfo->methodPointer.  The resulting offsets are cached per
<game version>:<abi>, so subsequent launches are instant.

This is ABI- and version-independent as long as the class/method names stay the
same.
"""

import json
import os
import time

import dw_android as android

CACHE_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'DungeonWithinSaveEditor')
CACHE_FILE = os.path.join(CACHE_DIR, 'methods.json')

RESOLVE_JS = r"""
(function () {
  function str(p) { try { return p.isNull() ? null : p.readUtf8String(); } catch (e) { return null; } }
  function hexpat(s) { let p = ''; for (let i = 0; i < s.length; i++) p += (s.charCodeAt(i) & 0xFF).toString(16).padStart(2, '0') + ' '; return p.trim(); }
  function ptrPat(a) { let s = ''; const v = BigInt(a.toString()); for (let i = 0; i < 8; i++) s += Number((v >> BigInt(8 * i)) & 0xFFn).toString(16).padStart(2, '0') + ' '; return s.trim(); }
  function safe(fn, d) { try { return fn(); } catch (e) { return d; } }
  function findMethod(className, methodName) {
    const pat = hexpat(methodName);
    for (const r of Process.enumerateRanges('r--')) {
      let hits = [];
      try { hits = Memory.scanSync(r.base, r.size, pat); } catch (e) { continue; }
      for (const h of hits) {
        const p = ptrPat(h.address);
        for (const r2 of Process.enumerateRanges('rw-')) {
          let hs = [];
          try { hs = Memory.scanSync(r2.base, r2.size, p); } catch (e) { continue; }
          for (const m of hs) {
            const mi = m.address.sub(0x18);
            const k = safe(() => mi.add(0x20).readPointer(), null);
            if (k && safe(() => str(k.add(0x10).readPointer()) === className, false)) {
              return safe(() => mi.readPointer(), null);
            }
          }
        }
      }
    }
    return null;
  }
  setTimeout(function () {
    const mod = Process.getModuleByName('libil2cpp.so');
    const dec = findMethod('ES3Saver', 'DecryptAndDecompress');
    const enc = findMethod('ES3Saver', 'CompressAndEncrypt');
    function rva(p) { return p ? p.sub(mod.base).toString(16) : null; }
    send({ dec_rva: rva(dec), enc_rva: rva(enc), base: mod.base.toString() });
    const load = findMethod('ES3Saver', 'Load');
    const save = findMethod('ES3Saver', 'Save');
    send({ load_rva: rva(load), save_rva: rva(save) });
  }, 0);
})();
"""


def load_cache():
    try:
        return json.load(open(CACHE_FILE, encoding='utf-8'))
    except Exception:
        return {}


def save_cache(cache):
    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dump(cache, open(CACHE_FILE, 'w', encoding='utf-8'), indent=1)


def cache_key(info):
    return '%s:%s' % (info.get('version') or 'unknown', info.get('abi') or 'unknown')


def find_game_pid(dev):
    for pid, name in android.list_frida_processes(dev):
        if name == 'DungeonWithin':
            return pid
    return None


def resolve_live(dev, log=print, wait=25):
    """Attach to the running game and resolve both method RVAs."""
    deadline = time.time() + wait
    pid = None
    while time.time() < deadline and pid is None:
        pid = find_game_pid(dev)
        if pid is None:
            time.sleep(1)
    if pid is None:
        raise RuntimeError('game is not running (cannot calibrate)')
    log('attaching to game pid %s to locate ES3Saver methods...' % pid)
    session = dev.attach(pid)
    script = session.create_script(RESOLVE_JS)
    result = {}

    def on_message(msg, data):
        if msg['type'] == 'send':
            result.update(msg['payload'])
        else:
            log('resolve error: %s' % msg.get('description'))

    script.on('message', on_message)
    script.load()
    deadline = time.time() + 120
    while time.time() < deadline and not result.get('dec_rva'):
        time.sleep(0.5)
    # give the optional Load/Save lookup a moment, but never block on it
    extra = time.time() + 60
    while time.time() < extra and not (result.get('load_rva') and result.get('save_rva')):
        time.sleep(0.5)
    try:
        session.detach()
    except Exception:
        pass
    if not result.get('dec_rva') or not result.get('enc_rva'):
        raise RuntimeError('could not locate ES3Saver methods (game build changed?)')
    log('found DecryptAndDecompress @ %s, CompressAndEncrypt @ %s' % (result['dec_rva'], result['enc_rva']))
    return result


def cached_entry(adb_path=None, serial=None):
    """Cached offsets for the connected device/build (or None)."""
    adb_path = adb_path or android.find_adb()
    if not adb_path:
        return None
    devs = android.devices(adb_path)
    if not devs:
        return None
    serial = serial if serial in devs else devs[0]
    return load_cache().get(cache_key(android.device_info(adb_path, serial)))


def ensure_rvas(adb_path=None, serial=None, endpoint=None, log=print, start_game=True):
    """Return (dec_rva, enc_rva, info) for the connected device/game build."""
    adb_path = adb_path or android.find_adb()
    if not adb_path:
        raise RuntimeError('adb not found; install platform-tools or set ADB')
    if not serial:
        devs = android.devices(adb_path)
        if not devs:
            raise RuntimeError('no adb device attached')
        serial = devs[0]
    info = android.device_info(adb_path, serial)
    info['adb'] = adb_path
    key = cache_key(info)
    cache = load_cache()
    if key in cache:
        entry = cache[key]
        log('using cached method offsets for %s (%s)' % (key, entry.get('source', 'cache')))
        return int(entry['dec_rva'], 16), int(entry['enc_rva'], 16), info

    dev = android.frida_device(endpoint)
    if start_game and find_game_pid(dev) is None:
        log('starting the game once to calibrate this build (%s)...' % key)
        android.adb(adb_path, serial, 'shell', 'am', 'start', '-n', android.ACTIVITY, timeout=30)
        time.sleep(6)
    result = resolve_live(dev, log=log)
    cache[key] = {
        'dec_rva': result['dec_rva'],
        'enc_rva': result['enc_rva'],
        'load_rva': result.get('load_rva'),
        'save_rva': result.get('save_rva'),
        'source': 'auto',
        'found_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    save_cache(cache)
    log('cached method offsets for %s' % key)
    return int(result['dec_rva'], 16), int(result['enc_rva'], 16), info
