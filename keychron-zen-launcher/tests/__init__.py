"""Test package.

Puts ``src`` on the path so the suite runs straight from a checkout with
``python3 -m unittest discover -s tests``, with nothing installed.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
