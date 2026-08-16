"""Test fixtures.

These tests exercise bed_api/ only. That layer deliberately has no Home
Assistant imports, so the suite runs against plain bleak without a HA install.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "resident_bed"))
