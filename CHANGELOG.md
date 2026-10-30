# Changelog

## 1.3.3

- The bundled adb is copied once to `%LOCALAPPDATA%\DungeonWithinSaveEditor\platform-tools` and run
  from there, instead of from the one-file temp folder. This removes the Windows
  "adb.exe - Application Error (0xc0000142)" popup caused by a background adb server whose
  executable had been deleted with the temp directory.
- That folder is added to `PATH` (and `ADB`) at startup, so Frida spawns the same adb version.

## 1.3.2

- Convert, Encrypt and plain-launch now check frida-server and start the bundled one automatically
  when it is not answering, instead of failing with FridaServerNotRunningError.
- Friendlier message when frida-server cannot be started.

## 1.3.1

- The bundled adb is now always preferred, so a saved path from another PC (or a different adb
  build with a stale server) no longer causes "device not found".
- adb device listing starts the server and retries after a kill-server when the device is hidden.
- Prepare device resolves the serial against the attached devices and gives a clear message when
  nothing is connected.

## 1.3.0

- Zero-install release: bundles `adb.exe` (platform-tools) and `frida-server` 17.24.3 for
  x86_64 and arm64, compressed with xz, with their licenses under `vendor/`.
- New **Prepare device** button: checks root, picks the ABI, pushes frida-server and starts it.
- `find_adb` prefers the bundled adb, so no system install is needed.

## 1.2.0

- Facilities: ability-modifier field plus a modification picker (dropdown + Add, still editable as a
  comma-separated list); the modification list is the card's Ability Modifiers count.
- Facility table shows the bonus index and modification list, and fits without scrolling.

## 1.1.0

- New **Facilities** tab: facility type (facKey), durability (bonus), modification list
  (prefixs, e.g. MOD_BTL_N_RGN) and rank-up per placed facility, with a 49-entry
  facility-type catalog.
- Dark theme UI with sidebar navigation, page headers, cards, global search and status bar.
- Standalone release build attached to GitHub Releases.

## 1.0.0

First public release.

- Encrypted `save.es3` reading by hooking the game's `ES3Saver.DecryptAndDecompress`
  (no AES key shipped; offsets resolved by name and cached per build/ABI).
- Text-preserving JSON editor: only changed scalars are rewritten, so the ES3
  dialect and every unrelated byte stay intact.
- DataVault checksum recomputation (`checksum = checksumSeed XOR values`) and a
  validate action for all 413 vaults.
- Writing back through the game's own `CompressAndEncrypt`, with automatic
  verification (re-decrypt and compare a marker) and rollback on mismatch.
- Tabs: Resources, Units, Abilities, Dark Lord, Variants, Collections,
  Mementos, Advanced, Log.
- Units: level/essence/awake/training, base/grow stats, custom name, trait
  (`prefix`), visual variant (`Irochi`), skin, innate trait display,
  promotion (`RankUp`/`TRANSCEND`), monster replacement by type.
- Abilities: 473-key part catalog, per-slot equip, clone a monster's set.
- Dark Lord: six forms (unlock, level, tokens), aspect stage, per-ability
  authority stage, skin (`lastPlaySkin`), active form via PlayerPrefs.
- Variants: stored variant counts and research levels.
- Collections: counters (costume/codex progress).
- Global search filter across every list.
- Runs from source (`run.bat`) or as a one-file executable (`build.bat`).
