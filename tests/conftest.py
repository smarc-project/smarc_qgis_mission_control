"""Headless QGIS for the plugin tests.

Run from the plugin root:

    QT_QPA_PLATFORM=offscreen python3 -m pytest
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import pytest
from qgis.core import QgsApplication
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtGui import QFont, QFontDatabase


class _Iface:
    def __init__(self, canvas: QgsMapCanvas):
        self._canvas = canvas

    def mapCanvas(self):
        return self._canvas

    def setActiveLayer(self, layer) -> bool:
        return True


# Plugin modules bind `from qgis.utils import iface` at import time, which is
# during test collection. The canvas has to exist before that import.
# QgsApplication finds its prefix from the interpreter, or from QGIS_PREFIX_PATH.
# initQgis writes symbology-style.db into the profile. Keep that out of the checkout.
_PROFILE = tempfile.mkdtemp(prefix="qgis-test-profile-")
atexit.register(shutil.rmtree, _PROFILE, True)
_APP = QgsApplication([], False, _PROFILE)
_APP.initQgis()
# A bare QgsApplication has no UI font, and Qt then picks Noto Color Emoji.
# That face's metrics shove Latin text into the top frame of a line edit.
_families = set(QFontDatabase().families())
for _family in ("Ubuntu", "Cantarell", "DejaVu Sans", "Liberation Sans", "Noto Sans"):
    if _family in _families:
        _APP.setFont(QFont(_family, 10))
        break
_CANVAS = QgsMapCanvas()
import qgis.utils
qgis.utils.iface = _Iface(_CANVAS)


@pytest.fixture(scope="session")
def qgis_app():
    yield _APP
