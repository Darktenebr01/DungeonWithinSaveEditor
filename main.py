"""Entry point for the Dungeon Within Save Editor."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, 'tools')
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from dw_save_gui import main  # noqa: E402

if __name__ == '__main__':
    main()
