# Dungeon Within save editor (tools)

Three small tools let you edit a real `save.es3` for **Dungeon Within v0.7.0 (b.209), x86_64** (MuMu). No AES key is needed: the game itself does every conversion.

| file | purpose |
|---|---|
| `tools/dw_save_convert.py` | encrypted `save.es3` -> plain ES3 JSON (hooks `ES3Saver.DecryptAndDecompress` in a normal game launch) |
| `tools/dw_save_editor.py` | edits the plain JSON (resources, unit stats/levels, mementos, checksums) |
| `tools/dw_save_launch.py` | launches the game with `ES3Saver.CompressAndEncrypt`/`DecryptAndDecompress` replaced by identity, so the game reads and writes plain JSON |

## What the save actually is

- Container: `45 53 33 45` (`ES3E`) + compressed + AES-CBC + HMAC, produced by `GCShared.ES3Save.ES3Saver.CompressAndEncrypt(byte[])` and consumed by `ES3Saver.DecryptAndDecompress(byte[])` (`dump.cs`: RVA `0x4E5C0E0` / `0x4E5CD88` in the arm64 build).
- In this x86_64 build (b.209) the two functions are at RVAs `0x3453fa3` (decrypt) and `0x34535f8` (encrypt). They are resolved per build; `dw_save_convert.py --dec-rva` / `dw_save_launch.py --dec-rva --enc-rva` let you override.
- Decrypted payload: one ES3 JSON document (~194 KB), 37 top-level keys `USER_DATA.*`, 413 `DataVault` objects with `checksum == checksumSeed XOR values`.
- ES3 dialect quirk: strings inside lists are written as `"__type" : "string""value"` (no `"value"` key). Re-serializing the whole document changes this dialect and the game silently drops data, so the editor only rewrites the exact scalar tokens it changes.

## Encrypt back to a legitimate ES3E file

`Encrypt save` (GUI) / `python tools\dw_save_encrypt.py save.json` (CLI) — deterministic, no load dependency:

1. minify the edited JSON and push it to a side file (`_dw_encrypt.json`) on the device,
2. start the game and hook `ES3Saver.DecryptAndDecompress` (no replacement) — it runs on a game thread
   and returns a large plaintext buffer (the game's own save, cloud or device),
3. overwrite that buffer with our JSON (padded with spaces, array length fixed up),
4. call the **real** `CompressAndEncrypt` on the same thread and write the ciphertext over `save.es3`
   with libc (the app's uid/gid is restored after the write),
5. stop the game, then decrypt the result again and compare a marker value (e.g. `GOLD`) with the input;
   on mismatch the previous save is pushed back automatically.

Verified: `GOLD = 22222` → 23,748-byte `ES3E` → decrypted back to `GOLD 22222`, and the game itself
re-reads the file. Because the plain file is never used as the live save, this cannot produce an empty
save through cloud/device conflicts.

## Why a plain save must never stay on the device

The game only understands the encrypted `ES3E` container. A plain JSON file left in
`.../files/save.es3` makes a *normal* game launch see "no device data" (empty last-saved/playtime) and
produce the **Cloud Data Conflict** dialog. Therefore:

- **Apply to file** only writes the local JSON — it never pushes.
- **Launch game (plain mode)** is the only place that pushes the plain file. Before pushing it copies the
  device's encrypted save to `%LOCALAPPDATA%\DungeonWithinSaveEditor\encrypted_backup.es3`, then verifies
  the pushed file starts with `{`.
- **Restore encrypted save** pushes that backup back, so the game can be started normally again.
- While a plain save is on the device, start the game **only** through the editor (patched mode).

## Portability (any device / ABI / build)

- No hardcoded offsets: `dw_methods.py` finds `ES3Saver.DecryptAndDecompress` and
  `CompressAndEncrypt` at runtime by method name and caches the offsets per
  `<game version>:<abi>` in `%LOCALAPPDATA%\DungeonWithinSaveEditor\methods.json`.
  The first use on a new build starts the game once to calibrate.
- `dw_android.py` discovers `adb` (PATH, `ADB`, common emulator installs, Android SDK),
  lists devices, probes the external-files save path, and reads the game version/ABI.
- Frida uses USB by default (`frida.get_usb_device`), so no port forwarding is needed;
  an explicit endpoint (e.g. `127.0.0.1:27042`) still works for networked setups.
- Manifest: `README.md`, `LICENSE` (MIT), `requirements.txt`, `.gitignore` (excludes
  decrypted personal saves and build output).

## GUI (recommended)

`start_editor.bat` in the repo root starts the GUI (`tools/dw_save_gui.py`).

- **Find save (auto)** / automatic on startup: finds `adb`, picks the attached device, pulls
  `/sdcard/Android/data/com.GameCoaster.DungeonWithin/files/save.es3` into
  `%LOCALAPPDATA%\DungeonWithinSaveEditor`, and opens it. Encrypted saves offer to decrypt via the game.
  If no device is reachable it scans Downloads, the MuMu shared folder and the Desktop.
- **Apply to file** writes the local JSON (timestamped `.bak`) and nothing else. **Restore encrypted save**
  puts the backed-up encrypted save back on the device for normal play.
- **Launch game (plain mode)** backs up the encrypted device save, pushes the plain JSON, verifies the
  device file starts with `{`, then starts the game with container crypto disabled. Keep the editor open
  while playing; when done, press **Restore encrypted save** before starting the game normally.
  Starting the game normally *while a plain save is on the device* is what produced the
  "Cloud Data Conflict / Device Data empty" dialog — the game cannot read a plain file.
- **Abilities tab**: each monster's equipped parts (`parts` on the unit: slots `M1`, `S1`, `S2`) can be
  changed to any part key known in the save (`USER_DATA.partsLog`, editable combo) and **cloned** from any
  other monster. The `B` innate skill and the Epic Trait are derived from the monster type/myth and are not
  stored in the save. CLI: `unit-parts`, `unit-set-part`, `unit-clone-parts`.
- **Units → Trait / Variant**: `prefix` is the monster trait (`MonPrefix.Key`, e.g. `TMP_E_GB`); the
  visual variant ("shiny" recolour) is the unit's `Irochi` field (`IrochiType`: `NONE`, `BETRAY`);
  `skin` (`UnitSkin.Key`: `None`, `MOONVEIL`) is a separate cosmetic, and `USER_DATA.lastPlaySkin`
  remembers the last skin per unit id.
- **Variants tab**: `USER_DATA.irochiLog` is keyed by monster type and holds a vault
  `count {NONE, BETRAY}` (the “N variants stored” counter used by Infuse Variant) plus a `log` list of
  discovered variant types. The tab edits the counts. Variant research lives in
  `USER_DATA.unitExp[i].irochiResearch` (a stat→level vault); the tab sets a research level per stat
  (`MaxHP`, `STR`, …). Empty vaults can be extended (new key inserted, checksum recomputed).
- **Dark Lord tab**: `USER_DATA.mwExp` holds one entry per Dark Lord form (key = monster, e.g. `BST001`,
  `ELM002`) with a vault `{LEVEL, TOKEN, UNLOCKED, INF_STAGE_CLEAR}` plus `UpgAspe`/`lcUpg`.
  `LEVEL` is the “Memory Stage” shown on the aspect screen. `UpgAspe` stores the **aspect** enhancement
  stage per aspect (`Basic` = Default Aspect). `lcUpg` stores the **authority/ability** enhancement stage
  for every command (`LC_<unit>_B01`, `_S01`…`_S04`, `_U01`/`_U02`, 0–5). The tab edits the form vault,
  the aspect stage and each ability stage.
  The forms' `UNLOCKED`/`LEVEL`/`TOKEN` are editable (checksums recomputed). The **active** Dark Lord is
  not in `save.es3`: it is the PlayerPrefs string `CurrentPlayMW` (e.g. `ELM002`), stored at
  `/data/data/<pkg>/shared_prefs/<pkg>.v2.playerprefs.xml`; the tab can read and set it (the game is
  stopped first, ownership/mode restored).
- **Awakening**: there is no separate awakening-skill list in the save. Per-unit awakening progress is
  `USER_DATA.unitExp[i].storage.values.AWAKE_LEVEL` (editable), the granted skills/abilities are the
  unit's `parts` (M1/S1/S2, editable in Abilities) and unlocked abilities are recorded in
  `USER_DATA.AbilityLog`; extra stats are `unit.awakeEft`.
- **Innate trait** is not stored on the unit: it is `<unitIdx>_I1` from
  `UnitTable.strInnateBasicAction`, fixed by the monster type (208 innate `_I1` abilities are recorded in
  `AbilityLog`). The Units tab shows the derived key and offers **Monster replacement…** — a dropdown of all
  known monster types (211 entries: units in the save, `_I1` abilities in the log, and the full parts
  catalog) that writes `unitIdx` (confirmation + `.bak`). This replaces the monster (model, stats, innate);
  stats/parts/prefix/myth fields stay as they were.
- **Promotion (Units tab)**: each unit has a vault `{RankUp, TRANSCEND, CALLUP, GMO}` — `RankUp` is the
  promotion tier (the game exposes `GlobalStatType.MWRankUp_AddStat` / `MWRankUp_StatBonus_Mul` bonuses),
  `TRANSCEND` the transcendence level. The tab shows all four and writes `RankUp` / `TRANSCEND`
  (keys are inserted when missing; checksums recomputed). The in-run Dark Lord counter
  `PlayerMawangData.promotion` (ES3 key `promote`) is run-scoped and not stored in `save.es3`.
- **Units tab**: level, essence/EXP, awake level and training stage come from
  `USER_DATA.unitExp[*].storage.values` (`LEVEL`, `EXP`, `AWAKE_LEVEL`, `TRAIN_LEVEL`), not from the
  unit object; the editor writes those vault fields and recomputes their checksums. `level`/`exp` fields
  on the unit object are always 0 in real saves. Display names are not stored in the save (localization
  lives in the game), so the list shows `unitIdx`; the game's `customName` field can be set per unit.

## Workflow

1. **Convert once** (only needed for an encrypted save). Put the encrypted `save.es3` on the device, then:

   ```
   python tools/dw_save_convert.py --endpoint 127.0.0.1:27042 --out save_plain.json
   ```

   Push `save_plain.json` to
   `/sdcard/Android/data/com.GameCoaster.DungeonWithin/files/save.es3`.

2. **Edit**

   ```
   python tools/dw_save_editor.py info    save_plain.json
   python tools/dw_save_editor.py resource save_plain.json GOLD 99999
   python tools/dw_save_editor.py all-resources save_plain.json 99999
   python tools/dw_save_editor.py unit-level save_plain.json 0 60
   python tools/dw_save_editor.py unit-stat  save_plain.json 0 awakeEft STR 10
   python tools/dw_save_editor.py unit-stat  save_plain.json 0 baseEft MaxHP 1.5
   python tools/dw_save_editor.py memento    save_plain.json BLD_PORTAL 1
   python tools/dw_save_editor.py set-json   save_plain.json USER_DATA.mementos '[{"__type":"...","key":"BLD_PORTAL","buyCount":1}]'
   python tools/dw_save_editor.py validate   save_plain.json
   ```

   Every edit recomputes affected DataVault checksums (`seed XOR values`) and clears `isTampered`.

3. **Play with the plain save.** Push the edited JSON and start the game through the launcher, keeping it attached for the whole session:

   ```
   python tools/dw_save_launch.py --endpoint 127.0.0.1:27042 --timeout 3600
   ```

   The launcher removes the container crypto for that process, so the game loads the JSON and writes plain JSON on its own saves. If you close the launcher, the patch is reverted and the next game save is encrypted again.

## What was verified on this build

- Converted a real encrypted save (24,948 B) to plain JSON (194,158 B) and back-loaded it; all 413 vault checksums validated.
- Edited `PIECE` to `12345` in the JSON, launched with the patched crypto, and the value `"PIECE": 12345` was present in the game's memory after load; the main menu rendered completely (no dropped data).
- With the patch attached the game rewrote `save.es3` as plain JSON on its own save (file stayed a `{`-document, size changed 194,158 -> 194,194 after the game recomputed its internal fields).

## Limits / notes

- RVAs are build-specific. They are offsets in `libil2cpp.so`; re-derive them for another version (find the `DecryptAndDecompress` / `CompressAndEncrypt` method-name strings in memory, follow the `MethodInfo+0x20 -> klass` pointer, check the class name is `ES3Saver`).
- The top-level `USER_DATA.hash` is left untouched by the editor; the game tolerates the mismatch on load and recomputes it when it saves (verified). If a future build validates it at load, that check would need reversing.
- "Essence"/"Memory Stage"/"Training Stage" in the Training Grounds UI are derived from unit/facility data, not stored as a single field; edit the underlying unit/facility records (or use `get`/`unit-stat`).
- Keep backups: copy `save.es3` before writing. The tools never touch cloud saves.
- Tested against MuMu (x86_64) with frida-server on `127.0.0.1:27042`. USB/other devices: pass `--endpoint`/`--adb`/`--serial`.
