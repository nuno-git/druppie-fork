"""Pytest bootstrap for the scripts/ test-suite.

``scripts/`` holds standalone scripts (no ``__init__.py``), and some of them
import each other by bare module name (e.g. ``from generate_cas import
render_cas``). Put ``scripts/`` on ``sys.path`` so those bare imports — and the
test imports of ``validate_docs`` / ``generate_cas`` / ``check_mandatory_docs``
— resolve.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
