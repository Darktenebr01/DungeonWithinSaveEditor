# Contributing

Thanks for taking a look.

## Reporting a bug

Open an issue with:

- the game version (bottom of the title screen, e.g. `v0.7.0 (b.209)`),
- ABI (`x86_64`, `arm64-v8a`, ...),
- what you clicked and what the **Log** tab printed,
- whether you used `Encrypt save` or plain mode.

Never attach your `save.es3` or a decrypted save to an issue — they contain
your whole account state. A log excerpt is enough.

## Pull requests

- Keep the text-preserving editing rule: never re-serialize the whole save.
  `tools/dw_save_editor.py` only rewrites the exact token it changes, and any
  change that breaks that can silently drop data.
- Run the tests before pushing:

  ```bat
  python -m unittest discover -s tests -v
  ```

- Match the existing code style (plain standard library, no new runtime
  dependencies without a reason; the GUI is tkinter only).

## New screens

A tab usually needs three things:

1. a reader in `tools/dw_save_editor.py` returning spans/values,
2. a writer that changes only those spans and calls `recompute_checksums`,
3. a UI section in `tools/dw_save_gui.py` that refreshes from `self.obj`.

Test the writer against a real save copy before opening a PR.
