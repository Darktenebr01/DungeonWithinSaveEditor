# Dungeon Within Save Editor — Android save editor for resources, monsters, facilities and the Dark Lord

Open-source **save editor for Dungeon Within** on Android (emulator or rooted phone).
Edit gold and resources, monster levels, stats and abilities, facility modifiers, Dark Lord
aspects and variants — and, since **v1.4.7**, work against the *running game*: live save pull,
live Dark Lord base stats, and a run-map jump that moves the day cursor straight to the boss.

Reads decrypt the `ES3E` container locally (no game launch needed), writes go back through the
game's own `CompressAndEncrypt`, and every edit is checksum-validated.

[![Release](https://img.shields.io/github/v/release/Darktenebr01/DungeonWithinSaveEditor?label=download&color=f5a623)](https://github.com/Darktenebr01/DungeonWithinSaveEditor/releases/latest)
[![Version](https://img.shields.io/badge/version-1.4.7-f5a623)](CHANGELOG.md)
[![Tests](https://img.shields.io/badge/tests-25%20passing-2ea043)](tests/test_editor.py)
[![License](https://img.shields.io/github/license/Darktenebr01/DungeonWithinSaveEditor?color=f5a623)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-2a2a2e)](#install-and-run)
[![Game](https://img.shields.io/badge/game-Dungeon%20Within%20v0.7.1-2a2a2e)](#how-it-works)

![Dungeon Within Save Editor — Units tab showing monster levels, traits and variants](docs/units.png)

## How it works

The save is an `ES3E` container encrypted by the game's own code. Reading no longer needs a game
launch: `tools/dw_es3.py` decrypts the container with the constants compiled into `ES3Saver`, which
is what the ACTIVE GAME page uses to poll the device. Writing still goes through the game itself:

1. fills the game's decrypted buffer with your JSON and calls the real `CompressAndEncrypt` on the
   game thread, then writes the ciphertext over `save.es3` with libc;
2. when a read does go through the game (the **Convert encrypted…** button), the editor starts it and
   hooks `ES3Saver.DecryptAndDecompress` to capture the plain JSON the game produced;
3. edits are made textually, touching only the scalar tokens that change, so the ES3 dialect (and
   every unrelated byte) stays intact.

The crypto functions are found by name at runtime and cached per `<game version>:<abi>`, so there
are no hardcoded offsets. `adb` and the device are auto-detected; a networked Frida endpoint can be
entered by hand.

## What you can do

| Screen | What it does |
| --- | --- |
| **Live Dark Lord** (ACTIVE GAME) | Pulls the running game's save every 3 s, decrypts it locally, shows device/build/process/SHA, and starts the Frida base-stat hook for the Dark Lord |
| **Live map** (ACTIVE GAME) | Makes every rendered run-map node selectable and jumps the run's day cursor to a chosen turn (boss/end zone) |
| **Resources** | Edit every `USER_DATA.storage` currency/resource (gold, essence, tokens), searchable |
| **Facilities** | Facility type, ability modifiers (bonus index that drives durability), modifications picked from a dropdown or typed as keys (`prefixs`), rank-up |
| **Units** | Level, essence/EXP, awake and training stage, base/grow stats, custom name, trait, variant (`Irochi`), skin, innate trait display, promotion (`RankUp`/`Transcend`), monster type replacement |
| **Abilities** | Equip `M1`/`S1`/`S2` parts from a 473-key catalog, clone a whole ability set, and edit the **current run** units (`INGAME_DATA`) including their per-part **Ethereal** flag |
| **Dark Lord** | Unlock the six forms, set level/tokens, aspect stage, per-ability authority stage, and the Dark Lord skin |
| **Variants** | Stored variant counts (`NONE`/`BETRAY`) and variant research levels |
| **Collections** | Collection counters used by codex and costume unlocks |
| **Mementos** | Memento buy counts |
| **Advanced** | Get/set any JSON path |
| **Log** | Everything the Frida side reports |

A search box at the top filters every list. **Apply to file** writes the local JSON,
**Encrypt save** turns it back into a normal `ES3E` save, **Validate** recomputes and checks all
413 DataVault checksums.

### Live tools (v1.4.7)

The **ACTIVE GAME** group drives the running game instead of the file:

- **Live Dark Lord** — polls `save.es3` from the device every 3 s and decrypts it locally with
  `tools/dw_es3.py`. The editor buffer is replaced only while it still matches the last snapshots, so
  unsaved edits are never silently discarded.
- **Start live stats** — Frida hook that overrides `UnitTable` base stats for Dark Lord ("Mawang")
  tables (`--hp`, `--str`, `--dex`, `--con`, `--int`, `--wis`, `--cha`). Units and runs created after
  it starts use the new values; the save file is untouched. Cold start ~15 s, later starts ~1 s from
  the cached RVAs.
- **Start map hook** — forces every rendered run-map node to stay clickable and bypasses the
  adjacency check, so any node the map shows can be picked.
- **Jump to turn** — `--turn N` writes `StageData.dayNodeCursor` on Unity's main thread when the map
  loads, jumping the run straight to a chosen turn (1–16; 15 lands on the boss/end zone in testing).

Everything is process-local: stopping a hook or restarting the game restores the normal rules.

![Abilities tab — equipped parts per monster and cloning between monsters](docs/abilities.png)

![Facilities tab — type, ability modifiers, modifications and rank-up](docs/facilities.png)

## Install and run

> Zero-install: the exe ships `adb.exe` and `frida-server` for x86_64/arm64. Enable root on the
device, click **Prepare device**, and the editor pushes and starts everything itself.
>
> Root is mandatory: turn it on in the emulator settings (MuMu / LDPlayer / BlueStacks have a root
> toggle) or use a rooted phone. The app tries `adb root` first, then `su`.

**Download:** the standalone Windows build is in
[Releases](https://github.com/Darktenebr01/DungeonWithinSaveEditor/releases/latest)
(`DungeonWithinSaveEditor.exe`, no Python needed).

From source — requirements: Windows 10/11, Python 3.10+, `adb` (Android platform-tools), and
a rooted device/emulator with `frida-server` running.

```bat
python -m pip install -r requirements.txt
run.bat
```

or manually:

```bat
python main.py
```

To build a standalone executable:

```bat
build.bat
```

The result is `dist\DungeonWithinSaveEditor.exe`.

## Safety

Every operation touches a real save, so the editor:

- writes a `.bak` next to the save before **Apply to file**;
- keeps a backup of the encrypted device save before **Launch game (plain mode)**;
- keeps a `replace-backup-<date>.es3` copy of the device save before **Replace save with file…**;
- verifies the encrypted result by decrypting it again and comparing a marker value (`GOLD` by
  default), and pushes the previous save back if it differs;
- never leaves a plain JSON file on the device after encrypting, because a normal launch would
  then show “Device Data empty” and a cloud conflict.

Use it on single-player saves only, keep your own backups, and prefer **Encrypt save** over plain
mode. This is a fan tool; Dungeon Within belongs to its developers, and this project is not
affiliated with or endorsed by them.

## Frequently asked questions

### Is there a Dungeon Within save editor for Android?

Yes — this one. It runs on Windows and edits the Android save through `adb` and Frida, so it
works with emulators (MuMu, LDPlayer, BlueStacks) and rooted phones, on any ABI.

### How do I edit my Dungeon Within save?

Start the game once so the save exists, connect the device, press **Find save** to decrypt,
change values, then **Apply to file** and **Encrypt save**. The encrypted file is decrypted again
to verify it, and the previous save is restored if verification fails.

### Can I replace my save with a different one?

Yes. In the **Connection** tab, **Replace save with file…** lets you pick any `save.es3` and pushes
it over the device save (the previous one is backed up to
`%LOCALAPPDATA%\DungeonWithinSaveEditor\replace-backup-<date>.es3` first, and the game is closed so
it cannot overwrite the new file). If you pick a plain JSON save instead, it is loaded into the
editor — press **Encrypt save** to write it to the device as a normal `ES3E` save.

### How do I back up my current save?

Use **Export save…** in the **Connection** tab and choose where to write the file. If a save is
loaded it is copied as-is; if nothing is loaded, the save currently on the device is pulled and
written, which backs up the game's own save without opening it first.

Use **Export encrypted save…** to always pull the raw `ES3E` save straight from the device (the
path is auto-detected when the field is empty) — handy when a plain JSON save is open in the editor
and you still want a normal encrypted backup.

### Do I need the encryption key?

No. You never handle keys: reads use the constants recovered from the game (so a pull needs no game launch), and writes are performed by the game itself.

### Does it work after a game update?

Usually. The crypto functions are located by name and offsets are cached per
`<version>:<abi>`; a new build needs one calibration run.

### Can I edit the Dark Lord's live stats?

Yes. **Live Dark Lord → Start live stats** hooks `UnitTable` and overrides the base stats of the
Dark Lord's ("Mawang") tables for units and runs created after the hook starts. It is process-local
and never writes the save.

### Can I skip the run map or jump to the boss?

Yes, with the live map hook: **Start map hook** makes every rendered node selectable, and
**Jump to turn** sets the run's day cursor through `StageData.set_dayNodeCursor` when the map
reloads — `15` lands on the boss/end zone on the current build. Skipped days do not grant their
rewards.

### Does the live editor change my save file?

No. The ACTIVE GAME page only reads the save from the device, and the Frida hooks change memory in
the running process. Writing still happens through the normal **Encrypt save** path.

### Where is the save file?

`/sdcard/Android/data/com.GameCoaster.DungeonWithin/files/save.es3` (the editor probes this path
and updates it if the game changes it).

## Project layout

```
main.py                  entry point
version.py               version constants
tools/dw_save_gui.py     tkinter UI (all tabs)
tools/dw_theme.py        dark theme palette and ttk styles
tools/dw_save_editor.py  text-preserving JSON editor + checksums
tools/dw_save_convert.py decrypt: capture the plain save
tools/dw_save_encrypt.py encrypt: write the edited save back
tools/dw_save_launch.py  plain-save launcher (fallback mode)
tools/dw_android.py      adb / device / Frida discovery
tools/dw_es3.py          ES3E container read/write (local decrypt for live pulls)
tools/dw_live.py         pull the running game's save and decrypt it
tools/dw_live_stats.py   Frida hook: Dark Lord base stats
tools/dw_live_map.py     Frida hook: selectable map nodes + day-cursor jump
tools/dw_methods.py      runtime method offsets, cached per build
tools/dw_names.py        capture monster names from the running game
tools/dw_dump_parts.py   dump live ability/part tables
tools/dw_capture_mawang.py  capture Dark Lord costume data
tools/parts_catalog.json part key catalog
tools/facility_catalog.json facility type catalog
tools/facility_prefixes.json modification key catalog
tools/dw_setup.py       prepare device: push and start bundled frida-server
vendor/                 bundled adb + frida-server (xz) and their licenses
docs/SAVE_EDITOR.md      save format, encryption flow, portability notes
docs/index.html          landing page (GitHub Pages)
tests/                   parser/checksum tests
```

## Development

```bat
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The suite covers the text-preserving parser, DataVault checksums, ES3E container vectors and Dark
Lord editing (**25 tests**).

## Active Game vs Save file

The left navigation is split by data source:

- **ACTIVE GAME** - `Connection` and `Live Dark Lord`. This group reads the running game, never writes it.
  `Live Dark Lord` pulls `save.es3` from the device every 3 seconds, decrypts it locally and shows device,
  game build, process id, container/plain size, SHA and pull time. `Send to editor` loads the snapshot;
  with **Load into the editor when the game saves** enabled the buffer is replaced only while it still
  matches the last pull, so unsaved local edits are kept and the log tells you the game moved on.
- **SAVE FILE** - Resources, Facilities, Units, Abilities, Dark Lord, Variants, Collections, Mementos,
  Advanced. Everything here edits the loaded JSON and is written back with `Encrypt save` (or the
  game-driven conversion).

The Frida live-stat hook sits on the Active Game page and is process-local: it changes the Dark Lord's
`UnitTable` base stats for units/runs created after it starts and never touches the save file.
## Live map: make any rendered node selectable (Frida)

`tools/dw_live_map.py` relaxes the run map while the game is running:

```bat
python -u tools\dw_live_map.py --attach
```

`--turn N` jumps the run's day cursor: the tool hooks `NodesUIContents.LoadDayTasks(StageData)` on the
main thread and calls `StageData.set_dayNodeCursor(N)` before the map builds. The GUI exposes this as
**Jump to turn** + **Start + jump** (default 15). The cursor is applied on the next map load, so finish
the current node or revisit the map once after starting it.
The same hook has **Start map hook / Stop** buttons on the ACTIVE GAME -> Live Dark Lord page, so it
can be used without a terminal.

- `NodeContainer.ApplyVisuals(..., interactable, ...)` is forced to `true`, so nodes the game
  marked unclickable still accept clicks.
- `NodesUIContents.OnClickDayTaskSpot` is replaced with a direct call to
  `NodesUIContents._ConfirmDayNode(pin)`, which is the same method the normal flow calls once it
  accepts a pick, so the map's adjacency/validity check no longer rejects the click.

Reopen the map after starting the tool so the node buttons are rebuilt with the hook active.
It only affects nodes the map actually renders (Dungeon Within builds the current turn only), the
change is process-local, and stopping the tool restores the normal rules.
## Live Dark Lord stats (Frida)

A save only stores the Dark Lord's progression inputs; the six combat stats are built from the Mawang
`UnitTable` when a unit/run is created. `tools/dw_live_stats.py` overrides those table getters for Mawang
tables while the game runs, so the sheet and every unit created afterwards use the boosted values.

```bat
:: spawn the game and hook before a run/unit is built
python -u tools\dw_live_stats.py --str 9999 --dex 9999 --con 9999 --int 9999 ^
    --wis 9999 --cha 9999 --hp 999999

:: or hook an already running game (applies to units/runs created from now on)
python -u tools\dw_live_stats.py --attach --str 5000 --wait 600

:: clear the overrides (hook only, useful to test resolution)
python -u tools\dw_live_stats.py --attach --clear --wait 30
```

- Methods are resolved by managed name (no hardcoded RVAs): the first run takes ~15 s (one metadata pass per name group) and the
  offsets are cached per `<version>:<abi>` under `work/live_stats/live_stats_rvas.json`, so later starts hook in about a second.
- Only tables whose `get_IsMawang()` returns true are modified; enemies and heroes keep their stats.
- The hook is process-local and never writes `save.es3`; restarting the game removes it.
- Instances that already exist (a battle in progress, the current run's units) keep their constructed stats.
  Attach before entering the battle / starting the run so the values are applied when stats are built.
- Verified on v0.7.1 (b.212): a fresh run with `--str 9999` hit for 3008 damage where the base attack was 8-26.
Design and format notes live in [docs/SAVE_EDITOR.md](docs/SAVE_EDITOR.md); release history in
[CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
