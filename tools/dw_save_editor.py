#!/usr/bin/env python3
"""
dw_save_editor.py - editor for Dungeon Within plain saves (ES3 dialect).

Why text edits: the game's ES3 writer emits a non-standard dialect for strings
inside lists:  "key" : { "__type" : "string""value" }.  Re-serializing the whole
document changes that dialect and the game silently drops data, so this tool
only rewrites the exact scalar tokens it changes and leaves every other byte
(and therefore the dialect) untouched.  DataVault checksums are recomputed as
seed XOR values and patched in place.

Commands:
    info      FILE
    validate  FILE
    get       FILE PATH
    resource  FILE KEY VALUE        (USER_DATA.storage.values)
    gold      FILE VALUE
    all-resources FILE VALUE
    unit-level FILE INDEX LEVEL
    unit-stat  FILE INDEX FIELD STAT VALUE   (FIELD: baseEft|growEft|awakeEft)
    memento   FILE KEY BUYCOUNT
    checksums FILE
"""

import argparse
import json
import os
import re
import sys


def to_signed32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def value_span(text, key, start=0, end=None):
    """Span (begin,end) of the value that follows "key" : inside text[start:end]."""
    end = len(text) if end is None else end
    pat = re.compile(r'"' + re.escape(key) + r'"\s*:\s*')
    m = pat.search(text, start, end)
    if not m:
        raise KeyError(key)
    i = m.end()
    j = i
    depth = 0
    in_str = False
    esc = False
    while j < len(text):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            j += 1
            continue
        if c == '"':
            in_str = True
        elif c in '{[':
            depth += 1
        elif c in '}]':
            if depth == 0:
                break
            depth -= 1
        elif c == ',' and depth == 0:
            break
        j += 1
    return i, j


def get_token(text, key, start=0, end=None):
    i, j = value_span(text, key, start, end)
    return text[i:j].strip()


def set_token(text, key, value, start=0, end=None):
    i, j = value_span(text, key, start, end)
    return text[:i] + ' ' + value + ' ' + text[j:]


def object_span(text, key, start=0, end=None):
    i, j = value_span(text, key, start, end)
    while i < j and text[i] != '{':
        i += 1
    return i, j


def array_span(text, key, start=0, end=None):
    i, j = value_span(text, key, start, end)
    while i < j and text[i] != '[':
        i += 1
    return i, j


def split_children(text, span, open_ch='{'):
    """Yield spans of the direct children of the object/array at span."""
    i, j = span
    close = '}' if open_ch == '{' else ']'
    k = i + 1
    depth = 0
    in_str = False
    esc = False
    child_start = None
    while k < j - 1:
        c = text[k]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            k += 1
            continue
        if c == '"':
            in_str = True
        elif c in '{[':
            depth += 1
        elif c in '}]':
            depth -= 1
        elif c == ',' and depth == 0:
            if child_start is not None:
                yield (child_start, k)
            child_start = None
            k += 1
            continue
        if child_start is None and not c.isspace() and c != ',':
            child_start = k
        k += 1
    if child_start is not None:
        yield (child_start, j - 1)


def parseIntToken(s):
    s = s.strip()
    if s in ('true', 'false'):
        return s == 'true'
    return int(s)


def vault_region(text, checksum_pos):
    """Given the position of '"checksum"', find its object start and read values/seed."""
    # object start: nearest '{' before that contains checksumSeed after it
    seg = text.rfind('{', 0, checksum_pos)
    while seg >= 0:
        # find matching close
        depth = 0
        in_str = False
        esc = False
        k = seg
        end = None
        while k < len(text):
            c = text[k]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
                k += 1
                continue
            if c == '"':
                in_str = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = k + 1
                    break
            k += 1
        if end is None:
            return None
        if '"checksumSeed"' in text[seg:end] and '"values"' in text[seg:end]:
            return seg, end
        seg = text.rfind('{', 0, seg)
    return None


def vault_values(text, region):
    i, j = object_span(text, 'values', region[0], region[1])
    vals = {}
    for cs, ce in split_children(text, (i, j), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*(.+)', text[cs:ce], re.S)
        if not m:
            continue
        try:
            vals[m.group(1)] = parseIntToken(m.group(2))
        except ValueError:
            vals[m.group(1)] = None
    return vals


def find_all_checksums(text):
    return [m.start() for m in re.finditer(r'"checksum"\s*:', text)]


def recompute_checksums(text, verbose=False):
    out = text
    fixed = 0
    # walk from the end so positions stay valid
    for pos in reversed(find_all_checksums(out)):
        reg = vault_region(out, pos)
        if not reg:
            continue
        vals = vault_values(out, reg)
        if any(v is None for v in vals.values()):
            continue
        seed_s = get_token(out, 'checksumSeed', reg[0], reg[1])
        try:
            seed = int(seed_s)
        except ValueError:
            continue
        x = 0
        for v in vals.values():
            x ^= (int(v) if isinstance(v, bool) else v) & 0xFFFFFFFF
        want = to_signed32((seed ^ x) & 0xFFFFFFFF)
        cur = int(get_token(out, 'checksum', reg[0], reg[1]))
        if cur != want:
            out = set_token(out, 'checksum', str(want), reg[0], reg[1])
            fixed += 1
        # tamper flag
        try:
            if get_token(out, 'isTampered', reg[0], reg[1]) != 'false':
                out = set_token(out, 'isTampered', 'false', reg[0], reg[1])
        except KeyError:
            pass
    if verbose:
        print('recomputed %d vault checksums' % fixed)
    return out


def restore_good_save():
    pass


# ------------------------------- commands ----------------------------------

def load(path):
    return open(path, encoding='utf-8').read()


def save(path, text):
    open(path, 'w', encoding='utf-8', newline='').write(text)


def repair(text):
    fixed = text.replace('"__type" : "string""', '"__type" : "string", "value" : "')
    fixed = re.sub(r'("__type" : "(?:int|long|float|double|bool|byte|short|uint|ulong|sbyte|ushort|decimal|char)")(?=[-0-9tfn"])',
                   r'\1, "value" : ', fixed)
    return fixed


def parse(text):
    return json.loads(repair(text))


def cmd_unit_parts(args):
    text = load(args.file)
    parts = unit_parts(text, args.index)
    key = unit_index_key(text, args.index)
    print('%s (%d slots)' % (key, len(parts)))
    for i, p in enumerate(parts):
        print('  [%d] id=%s key=%s' % (i, p.get('id'), p.get('key')))
    return 0


def cmd_unit_set_part(args):
    text = load(args.file)
    parts = unit_parts(text, args.index)
    if args.slot < 0 or args.slot >= len(parts):
        print('slot out of range 0..%d' % (len(parts) - 1))
        return 1
    parts[args.slot]['key'] = args.key
    text = set_unit_parts(text, args.index, parts)
    save(args.file, text)
    print('unit %s slot %d = %s' % (unit_index_key(text, args.index), args.slot, args.key))
    return 0


def cmd_unit_clone_parts(args):
    text = load(args.file)
    src = unit_index_key(text, args.source)
    dst_parts = unit_parts(text, args.source)
    if not dst_parts:
        print('source unit %s has no parts' % src)
        return 1
    text = copy_unit_parts(text, args.source, args.target)
    save(args.file, text)
    print('copied %d parts from %s to %s' % (len(dst_parts), src, unit_index_key(text, args.target)))
    return 0


def cmd_set_json(args):
    """Replace the value of the first "KEY" occurrence with a JSON literal.

    Useful for arrays (e.g. clearStage) and objects; the literal is validated
    with json.loads before it is written, and everything else stays byte-identical.
    """
    text = load(args.file)
    try:
        json.loads(args.json)
    except Exception as e:
        print('invalid JSON literal:', e)
        return 1
    text = set_token(text, args.key, args.json)
    if args.checksums:
        text = recompute_checksums(text, True)
    save(args.file, text)
    print('%s = %s' % (args.key, args.json))
    return 0


def cmd_info(args):
    obj = parse(load(args.file))
    st = obj.get('USER_DATA.storage', {}).get('value') or {}
    vals = st.get('values', {}) if isinstance(st, dict) else {}
    print('keys:', len(obj))
    print('lastSaveTime:', obj.get('USER_DATA.lastSaveTime', {}).get('value'))
    print('runCount:', obj.get('USER_DATA.runCount', {}).get('value'))
    print('playTime(h):', round((obj.get('USER_DATA.playTime', {}).get('value') or 0) / 3600, 1))
    print('units:', len(obj.get('USER_DATA.m_Units', {}).get('value') or []))
    print('facilities:', len(obj.get('USER_DATA.m_Facilities', {}).get('value') or []))
    print('mementos:', len(obj.get('USER_DATA.mementos', {}).get('value') or []))
    print('resources:', json.dumps(vals, ensure_ascii=False))
    return 0


def storage_region(text):
    reg = object_span(text, 'USER_DATA.storage')
    return reg


def cmd_resource(args):
    text = load(args.file)
    reg = storage_region(text)
    vals_i, vals_j = object_span(text, 'values', reg[0], reg[1])
    text = set_token(text, args.key, str(int(args.value)), vals_i, vals_j)
    text = recompute_checksums(text, True)
    save(args.file, text)
    print('%s = %s' % (args.key, args.value))
    return 0


def cmd_gold(args):
    return cmd_resource(argparse.Namespace(file=args.file, key='GOLD', value=args.value))


def cmd_all_resources(args):
    text = load(args.file)
    reg = storage_region(text)
    vals_i, vals_j = object_span(text, 'values', reg[0], reg[1])
    preserve = {'FIRSTPLAY', 'MW_TOKEN_SEED', 'RAND_TOKEN_COIN', 'TKQ_IROCHI_RETRO'}
    vals = vault_values(text, reg)
    for k in list(vals.keys()):
        if k in preserve:
            continue
        text = set_token(text, k, str(int(args.value)), vals_i, vals_j)
    text = recompute_checksums(text, True)
    save(args.file, text)
    print('all resources = %s' % args.value)
    return 0


def unit_element_spans(text):
    ai, aj = array_span(text, 'USER_DATA.m_Units')
    return list(split_children(text, (ai, aj), '['))


def unit_exp_span(text, key):
    """Span of the USER_DATA.unitExp entry whose "key" equals key."""
    ai, aj = array_span(text, 'USER_DATA.unitExp')
    for s, e in split_children(text, (ai, aj), '['):
        try:
            k = get_token(text, 'key', s, e).strip('"')
        except KeyError:
            continue
        if k == key:
            return s, e
    return None


def unit_exp_values_span(text, key):
    s, e = unit_exp_span(text, key)
    si, sj = object_span(text, 'storage', s, e)
    return object_span(text, 'values', si, sj)


def get_unit_exp(text, key):
    span = unit_exp_values_span(text, key)
    vi, vj = span
    out = {}
    for cs, ce in split_children(text, (vi, vj), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*(.+)', text[cs:ce], re.S)
        if m:
            try:
                out[m.group(1)] = int(m.group(2))
            except ValueError:
                pass
    return out


def set_unit_exp(text, key, field, value):
    vi, vj = unit_exp_values_span(text, key)
    text = set_token(text, field, str(int(value)), vi, vj)
    return recompute_checksums(text)


def unit_index_key(text, index):
    spans = unit_element_spans(text)
    s, e = spans[index]
    return get_token(text, 'unitIdx', s, e).strip('"')


def unit_parts(text, index):
    """Equipped parts (M1/S1/S2) of a unit as a list of {id, key}."""
    spans = unit_element_spans(text)
    s, e = spans[index]
    ai, aj = array_span(text, 'parts', s, e)
    tok = text[ai:aj]
    try:
        parts = json.loads(tok)
    except Exception:
        parts = []
    return parts or []


def set_unit_parts(text, index, parts):
    spans = unit_element_spans(text)
    s, e = spans[index]
    ai, aj = array_span(text, 'parts', s, e)
    return text[:ai] + json.dumps(parts, separators=(',', ':')) + text[aj:]


def copy_unit_parts(text, src_index, dst_index):
    return set_unit_parts(text, dst_index, unit_parts(text, src_index))


def part_catalog(obj):
    """All part keys: full vanilla catalog + partsLog + part-like AbilityLog entries."""
    out = set()
    candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parts_catalog.json')]
    base = getattr(sys, '_MEIPASS', None)
    if base:
        candidates.insert(0, os.path.join(base, 'parts_catalog.json'))
    candidates.append(os.path.join(os.getcwd(), 'parts_catalog.json'))
    for cat in candidates:
        if not os.path.exists(cat):
            continue
        try:
            out.update(json.load(open(cat, encoding='utf-8')))
            break
        except Exception:
            pass
    for ent in obj.get('USER_DATA.partsLog', {}).get('value') or []:
        val = ent.get('value') if isinstance(ent, dict) else ent
        if isinstance(val, str):
            out.add(val)
    pat = re.compile(r'^[A-Z0-9]+(_[A-Z0-9]+)*_[IMS][12]$')
    for ent in obj.get('USER_DATA.AbilityLog', {}).get('value') or []:
        val = ent.get('value') if isinstance(ent, dict) else ent
        if isinstance(val, str) and pat.match(val):
            out.add(val)
    for u in obj.get('USER_DATA.m_Units', {}).get('value') or []:
        for p in u.get('parts') or []:
            if isinstance(p, dict) and isinstance(p.get('key'), str):
                out.add(p['key'])
    return sorted(out)


def cmd_unit_level(args):
    text = load(args.file)
    spans = unit_element_spans(text)
    if args.index < 0 or args.index >= len(spans):
        print('unit index out of range 0..%d' % (len(spans) - 1))
        return 1
    key = unit_index_key(text, args.index)
    if unit_exp_span(text, key) is None:
        print('unit %s has no unitExp entry' % key)
        return 1
    text = set_unit_exp(text, key, 'LEVEL', args.level)
    save(args.file, text)
    print('unit %s level = %s' % (key, args.level))
    return 0


UNIT_EXP_FIELDS = ('LEVEL', 'EXP', 'AWAKE_LEVEL', 'TRAIN_LEVEL')

# MonPrefix.Key from GameDefinitions (monster variant/prefix)
MON_PREFIXES = [
    'NONE',
    'TMP_N_TKS', 'TMP_N_EC', 'TMP_N_SF', 'TMP_N_FJ', 'TMP_N_PB', 'TMP_N_FF', 'TMP_N_IM', 'TMP_N_CP',
    'TMP_N_NP', 'TMP_N_RG', 'TMP_N_PR',
    'TMP_R_RDS', 'TMP_R_WDS', 'TMP_R_BDS', 'TMP_R_BKD', 'TMP_R_GDS', 'TMP_R_CS', 'TMP_R_US', 'TMP_R_THS',
    'TMP_R_FV', 'TMP_R_TM', 'TMP_R_SB', 'TMP_R_AB', 'TMP_R_BC', 'TMP_R_GC', 'TMP_R_NA',
    'TMP_E_FR', 'TMP_E_GB', 'TMP_E_ID', 'TMP_E_AOF', 'TMP_E_AOI', 'TMP_E_AOS', 'TMP_E_AOM', 'TMP_E_AOD',
    'TMP_E_AOA', 'TMP_E_AOT', 'TMP_E_AMC', 'TMP_E_IB', 'TMP_E_WS', 'TMP_E_JN', 'TMP_E_CR', 'TMP_E_UA',
    'TMP_L_TR', 'TMP_L_MS', 'TMP_L_AS', 'TMP_L_FT', 'TMP_L_PS', 'TMP_L_PC', 'TMP_L_AM', 'TMP_L_AI',
]

# UnitSkin.Key (cosmetic skin)
UNIT_SKINS = ['None', 'MOONVEIL']

# IrochiType (visual variant / recolored "shiny" version of a monster)
IROCHI_TYPES = ['NONE', 'BETRAY']


def set_unit_field(text, index, field, value):
    """Set a string field on a unit (e.g. prefix, skin, customName)."""
    spans = unit_element_spans(text)
    s, e = spans[index]
    return set_token(text, field, json.dumps(value), s, e)


def unit_type_catalog(obj):
    """All known monster type ids (for the Monster replacement dropdown)."""
    out = set()
    for u in obj.get('USER_DATA.m_Units', {}).get('value') or []:
        if isinstance(u.get('unitIdx'), str):
            out.add(u['unitIdx'])
    for ent in obj.get('USER_DATA.AbilityLog', {}).get('value') or []:
        val = ent.get('value') if isinstance(ent, dict) else ent
        if isinstance(val, str) and val.endswith('_I1'):
            out.add(val[:-3])
    cat = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'parts_catalog.json')
    try:
        for key in json.load(open(cat, encoding='utf-8')):
            for suf in ('_I1', '_M1', '_S1', '_S2'):
                if key.endswith(suf):
                    out.add(key[:-3])
                    break
    except Exception:
        pass
    return sorted(out)


def collections_span(text):
    ci = object_span(text, 'USER_DATA.collections')
    return object_span(text, 'values', ci[0], ci[1])


def get_collections(text):
    vi, vj = collections_span(text)
    out = {}
    for cs, ce in split_children(text, (vi, vj), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*(-?\d+)', text[cs:ce])
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def set_collection(text, key, value):
    """Set a collection counter (dark-lord costume unlock progress). Existing keys only."""
    vi, vj = collections_span(text)
    return recompute_checksums(set_token(text, key, str(int(value)), vi, vj))


def last_skin_span(text):
    ci = object_span(text, 'USER_DATA.lastPlaySkin')
    return value_span(text, 'value', ci[0], ci[1])


def get_last_skins(text):
    vi, vj = last_skin_span(text)
    out = {}
    for cs, ce in split_children(text, (vi, vj), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*"([^"]*)"', text[cs:ce])
        if m:
            out[m.group(1)] = m.group(2)
    return out


def set_last_skin(text, unit_key, skin_name):
    """Set the remembered skin for a unit/Dark Lord (USER_DATA.lastPlaySkin)."""
    vi, vj = last_skin_span(text)
    try:
        text = set_token(text, unit_key, json.dumps(skin_name), vi, vj)
    except KeyError:
        text = insert_token(text, unit_key, json.dumps(skin_name), vi, vj)
    return recompute_checksums(text)


def unit_vault_span(text, index):
    spans = unit_element_spans(text)
    s, e = spans[index]
    vi = object_span(text, 'vault', s, e)
    return object_span(text, 'values', vi[0], vi[1])


def get_unit_vault(text, index):
    vi, vj = unit_vault_span(text, index)
    out = {}
    for cs, ce in split_children(text, (vi, vj), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*(-?\d+)', text[cs:ce])
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def set_unit_vault(text, index, key, value):
    """Set a unit vault entry (RankUp / TRANSCEND / CALLUP / GMO), inserting if absent."""
    vi, vj = unit_vault_span(text, index)
    try:
        text = set_token(text, key, str(int(value)), vi, vj)
    except KeyError:
        text = insert_token(text, key, str(int(value)), vi, vj)
    return recompute_checksums(text)


def unit_innate_key(text, index):
    """Innate trait ability key for a unit (UnitTable.strInnateBasicAction = <unitIdx>_I1)."""
    return unit_index_key(text, index) + '_I1'


def innate_keys(obj):
    """Every innate (I1) ability recorded in AbilityLog."""
    out = set()
    for ent in obj.get('USER_DATA.AbilityLog', {}).get('value') or []:
        val = ent.get('value') if isinstance(ent, dict) else ent
        if isinstance(val, str) and val.endswith('_I1'):
            out.add(val)
    return sorted(out)


def unit_exp_entry_text(text, key):
    span = unit_exp_span(text, key)
    if span is None:
        return None
    s, e = span
    return text[s:e]


def append_unit_exp(text, entry_text):
    ai, aj = array_span(text, 'USER_DATA.unitExp')
    body = text[ai + 1:aj - 1].rstrip()
    if body:
        new = body + ',' + entry_text
    else:
        new = entry_text
    return text[:ai + 1] + new + text[aj - 1:]


def transform_unit_type(text, index, new_key):
    """Change a unit's monster type (unitIdx).

    The unitExp entry of the old type stays as it is; if the new type has no
    entry yet the game creates one when it loads the save.  Destructive: stats,
    parts and prefix still belong to the old type, so back the save up first.
    """
    return recompute_checksums(set_unit_field(text, index, 'unitIdx', new_key))


def irochi_user_span(text, user):
    outer = object_span(text, 'USER_DATA.irochiLog')
    s, e = outer
    pat = re.compile(r'"' + re.escape(user) + r'"\s*:\s*\{')
    m = pat.search(text, s, e)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    for i in range(start, e):
        c = text[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return start, i + 1
    return None


def get_irochi(text, user):
    span = irochi_user_span(text, user)
    if span is None:
        return None
    s, e = span
    out = {}
    ci, cj = object_span(text, 'count', s, e)
    vi, vj = object_span(text, 'values', ci, cj)
    for cs, ce in split_children(text, (vi, vj), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*(-?\d+)', text[cs:ce])
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def set_irochi_count(text, user, variant, value):
    span = irochi_user_span(text, user)
    if span is None:
        raise KeyError('no irochi entry for %s' % user)
    s, e = span
    ci, cj = object_span(text, 'count', s, e)
    vi, vj = object_span(text, 'values', ci, cj)
    try:
        text = set_token(text, variant, str(int(value)), vi, vj)
    except KeyError:
        text = insert_token(text, variant, str(int(value)), vi, vj)
    return recompute_checksums(text)


def get_irochi_research(text, unit_key):
    span = unit_exp_span(text, unit_key)
    if span is None:
        return {}
    s, e = span
    ir = object_span(text, 'irochiResearch', s, e)
    vi, vj = object_span(text, 'values', ir[0], ir[1])
    out = {}
    for cs, ce in split_children(text, (vi, vj), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*(-?\d+)', text[cs:ce])
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def set_irochi_research(text, unit_key, stat, value):
    span = unit_exp_span(text, unit_key)
    if span is None:
        raise KeyError('no unitExp entry for %s' % unit_key)
    s, e = span
    ir = object_span(text, 'irochiResearch', s, e)
    vi, vj = object_span(text, 'values', ir[0], ir[1])
    try:
        text = set_token(text, stat, str(int(value)), vi, vj)
    except KeyError:
        text = insert_token(text, stat, str(int(value)), vi, vj)
    return recompute_checksums(text)


def insert_token(text, key, literal, start, end):
    """Insert "key": literal as a new member of the object whose '{' is at start."""
    depth = 0
    in_str = False
    esc = False
    close = None
    for k in range(start, len(text)):
        c = text[k]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                close = k
                break
    if close is None:
        raise ValueError('unbalanced object for insertion')
    body = text[start + 1:close].rstrip()
    sep = ',' if body.strip() else ''
    new_body = body + sep + '"' + key + '" : ' + literal
    return text[:start + 1] + new_body + text[close:]


def mw_vault_span(text, index, field):
    spans = mw_spans(text)
    s, e = spans[index]
    hi = object_span(text, field, s, e)
    return object_span(text, 'values', hi[0], hi[1])


def get_mw_vault(text, index, field):
    vi, vj = mw_vault_span(text, index, field)
    out = {}
    for cs, ce in split_children(text, (vi, vj), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*(-?\d+)', text[cs:ce])
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def set_mw_vault(text, index, field, key, value):
    """Set an entry of a Dark Lord form sub-vault (UpgAspe / lcUpg / storage ...)."""
    vi, vj = mw_vault_span(text, index, field)
    try:
        text = set_token(text, key, str(int(value)), vi, vj)
    except KeyError:
        text = insert_token(text, key, str(int(value)), vi, vj)
    return recompute_checksums(text)


def facility_spans(text):
    ai, aj = array_span(text, 'USER_DATA.m_Facilities')
    return list(split_children(text, (ai, aj), '['))


def facility_element_spans(text):
    return facility_spans(text)


def get_facility(text, index):
    s, e = facility_spans(text)[index]
    out = {'id': None, 'facKey': None, 'bonus': 0, 'prefixs': [], 'RankUp': 0}
    try:
        out['id'] = int(get_token(text, 'id', s, e))
    except Exception:
        pass
    try:
        out['facKey'] = get_token(text, 'facKey', s, e).strip('"')
    except Exception:
        pass
    try:
        out['bonus'] = int(get_token(text, 'bonus', s, e))
    except Exception:
        pass
    try:
        pf = get_token(text, 'prefixs', s, e)
        out['prefixs'] = [] if pf.strip() == 'null' else json.loads(pf)
    except Exception:
        pass
    try:
        vi = object_span(text, 'vault', s, e)
        vi = object_span(text, 'values', vi[0], vi[1])
        out['RankUp'] = int(get_token(text, 'RankUp', vi[0], vi[1]))
    except Exception:
        pass
    return out


def set_facility_field(text, index, field, literal):
    """Set facKey / bonus on one facility (literal is already JSON text)."""
    s, e = facility_spans(text)[index]
    return set_token(text, field, literal, s, e)


def set_facility_prefixes(text, index, keys):
    """Replace the modification list (prefixs) of one facility."""
    s, e = facility_spans(text)[index]
    i, j = value_span(text, 'prefixs', s, e)
    body = json.dumps(list(keys), ensure_ascii=False)
    return text[:i] + ' ' + body + ' ' + text[j:]


def set_facility_rankup(text, index, value):
    s, e = facility_spans(text)[index]
    vi = object_span(text, 'vault', s, e)
    vi = object_span(text, 'values', vi[0], vi[1])
    text = set_token(text, 'RankUp', str(int(value)), vi[0], vi[1])
    return recompute_checksums(text)


def facility_catalog():
    candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'facility_catalog.json')]
    base = getattr(sys, '_MEIPASS', None)
    if base:
        candidates.insert(0, os.path.join(base, 'facility_catalog.json'))
    candidates.append(os.path.join(os.getcwd(), 'facility_catalog.json'))
    for cat in candidates:
        if os.path.exists(cat):
            try:
                return json.load(open(cat, encoding='utf-8'))
            except Exception:
                pass
    return []


def mw_spans(text):
    ai, aj = array_span(text, 'USER_DATA.mwExp')
    return list(split_children(text, (ai, aj), '['))


def mw_values_span(text, index):
    spans = mw_spans(text)
    s, e = spans[index]
    si, sj = object_span(text, 'storage', s, e)
    return object_span(text, 'values', si, sj)


def mw_entry(text, index):
    spans = mw_spans(text)
    s, e = spans[index]
    out = {'key': get_token(text, 'key', s, e).strip('"')}
    vi, vj = mw_values_span(text, index)
    for cs, ce in split_children(text, (vi, vj), '{'):
        m = re.match(r'\s*"([^"]+)"\s*:\s*(.+)', text[cs:ce], re.S)
        if m:
            try:
                out[m.group(1)] = int(m.group(2))
            except ValueError:
                pass
    return out


def set_mw_field(text, index, field, value):
    vi, vj = mw_values_span(text, index)
    text = set_token(text, field, str(int(value)), vi, vj)
    return recompute_checksums(text)


def cmd_unit_exp(args):
    text = load(args.file)
    spans = unit_element_spans(text)
    if args.index < 0 or args.index >= len(spans):
        print('unit index out of range 0..%d' % (len(spans) - 1))
        return 1
    key = unit_index_key(text, args.index)
    if unit_exp_span(text, key) is None:
        print('unit %s has no unitExp entry' % key)
        return 1
    if args.field not in UNIT_EXP_FIELDS:
        print('field must be one of %s' % (', '.join(UNIT_EXP_FIELDS),))
        return 1
    text = set_unit_exp(text, key, args.field, args.value)
    save(args.file, text)
    print('unit %s %s = %s' % (key, args.field, args.value))
    return 0


def cmd_unit_stat(args):
    text = load(args.file)
    spans = unit_element_spans(text)
    if args.index < 0 or args.index >= len(spans):
        print('unit index out of range 0..%d' % (len(spans) - 1))
        return 1
    s, e = spans[args.index]
    if args.field in ('baseEft', 'growEft'):
        fi, fj = object_span(text, args.field, s, e)
        text = set_token(text, args.stat, repr(float(args.value)), fi, fj)
    elif args.field == 'awakeEft':
        ai, aj = object_span(text, 'awakeEft', s, e)
        vi, vj = object_span(text, 'values', ai, aj)
        text = set_token(text, args.stat, str(int(args.value)), vi, vj)
        text = recompute_checksums(text, True)
    else:
        print('field must be baseEft|growEft|awakeEft')
        return 1
    save(args.file, text)
    print('unit %d %s %s = %s' % (args.index, args.field, args.stat, args.value))
    return 0


def cmd_memento(args):
    text = load(args.file)
    ai, aj = array_span(text, 'USER_DATA.mementos')
    found = False
    for s, e in split_children(text, (ai, aj), '['):
        try:
            key = get_token(text, 'key', s, e).strip('"')
        except KeyError:
            continue
        if key == args.key:
            text = set_token(text, 'buyCount', str(int(args.count)), s, e)
            found = True
            break
    if not found:
        print('memento %s not found (add it in game first)' % args.key)
        return 1
    save(args.file, text)
    print('memento %s buyCount = %s' % (args.key, args.count))
    return 0


def cmd_checksums(args):
    text = load(args.file)
    text = recompute_checksums(text, True)
    save(args.file, text)
    return 0


def cmd_validate(args):
    obj = parse(load(args.file))
    bad = 0
    n = 0
    for path, vault in walk_vaults(obj):
        n += 1
        vals = vault.get('values') or {}
        if any(not isinstance(v, int) for v in vals.values()):
            continue
        x = 0
        for v in vals.values():
            x ^= (int(v) if isinstance(v, bool) else v) & 0xFFFFFFFF
        want = to_signed32((vault.get('checksumSeed', 0) ^ x) & 0xFFFFFFFF)
        if vault.get('checksum') != want:
            bad += 1
            if bad <= 5:
                print('MISMATCH', path)
    print('vaults', n, 'mismatched', bad)
    return 0 if bad == 0 else 2


def walk_vaults(node, path=''):
    if isinstance(node, dict):
        if 'checksum' in node and 'checksumSeed' in node and 'values' in node:
            yield path, node
        for k, v in node.items():
            yield from walk_vaults(v, path + '/' + str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk_vaults(v, path + '[%d]' % i)


def cmd_get(args):
    obj = parse(load(args.file))
    node = obj
    for part in re.findall(r'[^.\[\]]+|\[\d+\]', args.path):
        if part.startswith('['):
            node = node[int(part[1:-1])]
        else:
            node = node[part]
    print(json.dumps(node, ensure_ascii=False)[:4000])
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description='Dungeon Within plain-save editor (ES3 dialect preserving)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('info').add_argument('file')
    sub.add_parser('validate').add_argument('file')
    sub.add_parser('checksums').add_argument('file')
    p = sub.add_parser('get'); p.add_argument('file'); p.add_argument('path')

    p = sub.add_parser('resource'); p.add_argument('file'); p.add_argument('key'); p.add_argument('value')
    p = sub.add_parser('gold'); p.add_argument('file'); p.add_argument('value')
    p = sub.add_parser('all-resources'); p.add_argument('file'); p.add_argument('value')

    p = sub.add_parser('unit-level'); p.add_argument('file'); p.add_argument('index', type=int); p.add_argument('level')
    p = sub.add_parser('unit-exp'); p.add_argument('file'); p.add_argument('index', type=int)
    p.add_argument('field'); p.add_argument('value', type=int)
    p = sub.add_parser('unit-parts'); p.add_argument('file'); p.add_argument('index', type=int)
    p = sub.add_parser('unit-set-part'); p.add_argument('file'); p.add_argument('index', type=int)
    p.add_argument('slot', type=int); p.add_argument('key')
    p = sub.add_parser('unit-clone-parts'); p.add_argument('file'); p.add_argument('source', type=int)
    p.add_argument('target', type=int)
    p = sub.add_parser('unit-stat'); p.add_argument('file'); p.add_argument('index', type=int)
    p.add_argument('field'); p.add_argument('stat'); p.add_argument('value')

    p = sub.add_parser('memento'); p.add_argument('file'); p.add_argument('key'); p.add_argument('count', type=int)

    p = sub.add_parser('set-json'); p.add_argument('file'); p.add_argument('key'); p.add_argument('json')
    p.add_argument('--checksums', action='store_true')

    args = ap.parse_args(argv)
    args.func = {
        'info': cmd_info, 'validate': cmd_validate, 'checksums': cmd_checksums, 'get': cmd_get,
        'resource': cmd_resource, 'gold': cmd_gold, 'all-resources': cmd_all_resources,
        'unit-level': cmd_unit_level, 'unit-exp': cmd_unit_exp, 'unit-stat': cmd_unit_stat, 'memento': cmd_memento,
        'unit-parts': cmd_unit_parts, 'unit-set-part': cmd_unit_set_part, 'unit-clone-parts': cmd_unit_clone_parts,
        'set-json': cmd_set_json,
    }[args.cmd]
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
