# Security

This project edits local game save files through the game process itself.
It ships **no game binaries, no game assets and no encryption keys**.

## What it touches

- It reads and writes `save.es3` on the connected Android device through adb.
- It attaches Frida to the running game to call two functions the game itself
  uses (`DecryptAndDecompress` / `CompressAndEncrypt`).
- Everything else is local text editing.

## What it does not do

- No network access of its own, no telemetry, no uploads.
- No account credentials are read or stored.

## Reporting a problem

If you find a case where the editor writes a save the game cannot load, open an
issue with the game version, ABI and the relevant log lines. Keep a backup: the
editor writes `.bak` files, and `Encrypt save` restores the previous save when
its verification step fails.
