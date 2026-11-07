# Changelog

## 1.4.7

- Live map can now jump the run's day cursor: `dw_live_map.py --turn N` hooks
  `NodesUIContents.LoadDayTasks(StageData)` on the main thread and calls
  `StageData.set_dayNodeCursor(N)` before the map builds, so the node tree reloads at the requested turn.
  Verified on 0.7.1: from Stage 1-10 the next map load moved to the boss/end-zone emblem.
- The ACTIVE GAME -> Live Dark Lord page has a **Jump to turn** field (default 15) with **Start + jump**,
  which starts the map hook with that turn.

## 1.4.6

- Live map: removed the experimental day-skip code. `IngameMgrAdmin.NextDay` only advances the run's day
  cursor when it runs on Unity's main thread; calling it from Frida's thread faults, and every main-thread
  trigger tried so far (`NodeContainer.Update`, `UnityEngine.Time.get_deltaTime`) could not be resolved in
  this build. The map hook therefore stays selection-only: it makes rendered nodes selectable, but it does
  not move the day cursor, so completing a node the cursor did not reach still snaps the map back.

## 1.4.5

- The ACTIVE GAME -> Live Dark Lord page now has a **Live map** card: Start/Stop for the node-selectable
  hook (`dw_live_map.py`), with a status pill (`resolving i/n`, `active - reopen the run map`, `stopped`).
  It runs as a separate no-window process, logs into the Log tab, and is stopped when the window closes.

## 1.4.4

- New `tools/dw_live_map.py`: while attached to the running game it forces every rendered run-map
  node to be clickable (`NodeContainer.ApplyVisuals`) and replaces the click validator
  (`NodesUIContents.OnClickDayTaskSpot`) with a direct `_ConfirmDayNode(pin)` call. RVAs are resolved
  by managed name and cached per build; stopping the tool restores the normal map rules.

## 1.4.3

- Live-stat start is much faster:
  - cold start resolves the 8 base getters in one metadata pass per name group (Base, IsMawang) instead of one
    full 4 GB scan per method: ~125 s -> ~15 s.
  - the RVA cache is actually used now, and stores module-relative RVAs plus the `libil2cpp.so` size, so a
    later start on the same build installs the hooks in about a second and a different build is re-resolved.
  - growth getters are only resolved when `--growth` is passed.
  - a resolution error now aborts immediately instead of waiting out the 300 s deadline.
- GUI: the live-stat note and status text show the new timings.

## 1.4.2

- No more console windows while the editor runs: every adb/frida helper subprocess (device pull, push,
  convert, plain-mode launch, live-stat hook) is started with `CREATE_NO_WINDOW`, so a windowed
  (`pythonw`, `run.bat`) editor no longer flashes a terminal on each poll or action.
- Push failures now include the adb return code and output instead of an empty `push failed:` line, and a
  failed pre-convert push aborts instead of continuing into the game spawn.
- The live-stat hook process is started with the same no-window flag.

## 1.4.1

- Live Dark Lord page fixes from a live session:
  - the Frida log no longer prints one line per memory-scan step; it shows `resolving i/n` progress,
    the hook result and errors only.
  - `Send to editor` no longer re-triggers itself; it runs one pull and switches the buffer when it lands.
  - Auto-follow now tracks where the buffer came from: a save you opened or converted from disk is never
    replaced by the game's save, and a buffer you edited is kept with a one-time log notice.
  - `adb pull` retries once after `adb connect` for network devices and reports the adb return code and
    output instead of "unknown error".
  - Closing the window terminates the live-stat hook process.

## 1.4.0

- The UI is split into **ACTIVE GAME** and **SAVE FILE** groups. Active Game holds the device/Frida
  connection and a new **Live Dark Lord** page; every save-editing tab (Resources, Units, Abilities,
  Dark Lord, Variants, Collections, Mementos, Advanced) stays under SAVE FILE.
- **Live Dark Lord** always reads the running game: it pulls `save.es3` from the device on a 3 s timer,
  decrypts it with the ES3E container module (`tools/dw_es3.py`) and shows device, game build, process id,
  container/plain sizes, SHA and pull time. "Send to editor" loads that snapshot; auto-follow only replaces
  the buffer while it still matches the last pull, so local edits are never silently discarded.
- The page also owns the Frida live-stat hook (Start/Stop, HP/STR/DEX/CON/INT/WIS/CHA fields), replacing the
  save-only "current run" block that used to error when the save had no run.
- New modules `tools/dw_es3.py` (ES3E decrypt/encrypt, verified against a game-produced container) and
  `tools/dw_live.py` (device pull + decrypt). `requirements.txt` now lists `brotli` and `cryptography`.

## 1.3.9

- Dark Lord stats: the **Dark Lord** tab now edits the persistent stat drivers directly - essence level,
  the form's `Basic` aspect and its own `LC_*` authority stages - with **Max form stats** / **Max all forms**
  shortcuts (values beyond 5 are written as-is for experimentation) and checksum recomputation.
- New tool `tools/dw_live_stats.py`: a spawn/attach Frida hook that overrides `UnitTable` base stats for
  Dark Lord ("Mawang") tables while the game runs. It resolves `get_IsMawang` and `Get*Base`/`Get*Growth`
  by managed name (chunked scans, no hardcoded offsets), caches the RVAs per build, and only rewrites the
  return value when the table reports itself as Mawang. Verified in a fresh run: the Dark Lord's basic
  attack went from 8-26 to 3008 damage with `--str 9999`.
- Current-run `INGAME_DATA.playerMawang` stat editing (`baseEft` / `growEft` / `awakeEft`) when a save
  contains an active run.

## 1.3.8

- The **Abilities** tab has a new source switch: **Saved monsters** or **Current run (INGAME_DATA)**.
  The second one lists the units of the run in progress.
- Current-run parts show their role plus an **Ethereal** column. The game stores that flag as
  `"Ethereal" : 1` on the part's own vault, so the editor can now toggle the flag on a selected part,
  change a part key, add a part (optionally Ethereal) and remove one, with the per-part vault checksums
  recomputed.
- Adding/marking a second Ethereal part of the same family asks first: the game keeps one ethereal Main
  and one ethereal Sub slot and removes the overflow on load.
- The earlier experimental "ethereal slot ids" writer for saved monsters was removed: a save that really
  has an ethereal part (checked against a live one) proves the flag lives on the run unit parts, not in
  `USER_DATA.m_Units[].parts`.

## 1.3.7

- **Abilities** shows the role of each equipped slot (Main, Sub 1, Sub 2) and adds **Clear selected
  slot** next to **Set selected slot**.

## 1.3.6

- New **Replace save with file…** action in the Connection tab: pick any `save.es3` from disk and
  it is pushed over the device save, so a different save can be loaded without converting it
  first. The current device save is pulled to the cache as `replace-backup-<date>.es3` before the
  push, the game is closed so it cannot overwrite the new file, and the pushed file is verified to
  still start with `ES3E`. Plain JSON files are loaded into the editor instead (with a hint to use
  **Encrypt save**), because the normal game only reads the encrypted container.
- New **Export save…** action in the Connection tab: save the current save to any file you choose.
  If a save is loaded (plain JSON or encrypted `ES3E`), that file is copied; otherwise the save
  currently on the device is pulled and written, so the game's own save can be backed up without
  opening it first.
- New **Export encrypted save…** action in the Connection tab: always pulls the raw `save.es3` from
  the device (auto-detecting its path when needed) and writes it to a file you choose, even while a
  plain JSON save is open in the editor.

## 1.3.5

- ABI detection now retries across the adbd restart caused by `adb root`: it reads
  `ro.product.cpu.abi`, then `ro.product.cpu.abilist`, then `uname -m`, waiting for the device
  between attempts. Fixes "device ABI: ?" and "no bundled frida-server for ABI ''".

## 1.3.4

- Prepare device now tries `adb root` before `su`, which is how most emulators expose root
  (MuMu, LDPlayer, BlueStacks). Only if both fail does it stop, with instructions to enable
  the emulator's root setting or use a rooted phone.
- The failure message includes what `adb root` answered, so the cause is visible.

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
