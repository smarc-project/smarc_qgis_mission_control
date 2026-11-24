"""Headless QGIS for the plugin tests.

Run from the plugin root:

    QT_QPA_PLATFORM=offscreen python3 -m pytest
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

import pytest
from qgis.core import QgsApplication
from qgis.gui import QgsMapCanvas


class _Iface:
    def __init__(self, canvas: QgsMapCanvas):
        self._canvas = canvas

    def mapCanvas(self):
        return self._canvas


# Plugin modules bind `from qgis.utils import iface` at import time, which is
# during test collection. The canvas has to exist before that import.
QgsApplication.setPrefixPath("/usr", True)
_APP = QgsApplication([], False)
_APP.initQgis()
_CANVAS = QgsMapCanvas()
import qgis.utils
qgis.utils.iface = _Iface(_CANVAS)


@pytest.fixture(scope="session")
def qgis_app():
    yield _APP
