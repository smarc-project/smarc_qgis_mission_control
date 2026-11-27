from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDockWidget, QMainWindow, QToolBar

from src.ui.NativeChrome import NativeChrome


def _window():
    window = QMainWindow()
    bars = {name: window.addToolBar(name) for name in ("File", "Digitizing", "Ours")}
    for name in bars:
        bars[name].setObjectName(name)
    docks = {}
    for name in ("Layers", "Browser", "Mission"):
        dock = QDockWidget(name, window)
        dock.setObjectName(name)
        window.addDockWidget(Qt.LeftDockWidgetArea, dock)
        docks[name] = dock
    window.show()
    return window, bars, docks


def test_hide_keeps_ours_and_restore_brings_back_only_what_was_open(qgis_app):
    window, bars, docks = _window()
    docks["Browser"].hide()  # closed by the person before the toggle
    chrome = NativeChrome(window, keep=[bars["Ours"], docks["Mission"]])

    chrome.setHidden(True)
    qgis_app.processEvents()
    assert chrome.isHidden()
    assert not bars["File"].isVisible() and not bars["Digitizing"].isVisible()
    assert not docks["Layers"].isVisible()
    assert bars["Ours"].isVisible() and docks["Mission"].isVisible()

    chrome.setHidden(False)
    qgis_app.processEvents()
    assert not chrome.isHidden()
    assert bars["File"].isVisible() and docks["Layers"].isVisible()
    assert not docks["Browser"].isVisible()


def test_hiding_twice_does_not_forget_what_to_restore(qgis_app):
    window, bars, docks = _window()
    chrome = NativeChrome(window, keep=[])
    chrome.setHidden(True)
    chrome.setHidden(True)
    chrome.setHidden(False)
    assert bars["File"].isVisible() and docks["Layers"].isVisible()


def test_a_toolbar_deleted_while_hidden_does_not_stop_the_rest_coming_back(qgis_app):
    from qgis.PyQt import sip

    window, bars, docks = _window()
    chrome = NativeChrome(window, keep=[])
    chrome.setHidden(True)
    sip.delete(bars["Digitizing"])  # another plugin unloaded meanwhile

    chrome.setHidden(False)
    assert bars["File"].isVisible() and docks["Layers"].isVisible()


def test_a_toolbar_inside_a_panel_is_not_touched(qgis_app):
    window, bars, docks = _window()
    inner = QToolBar("inner", docks["Mission"])
    inner.show()
    chrome = NativeChrome(window, keep=[docks["Mission"]])
    chrome.setHidden(True)
    assert not inner.isHidden()


def test_qgis_asks_before_exit_and_gets_its_toolbars_back(qgis_app):
    from qgis.PyQt.QtWidgets import QAction

    from src.main import _ShowQgisBeforeExit

    action = QAction("Hide QGIS")
    action.setCheckable(True)
    action.setChecked(True)
    seen = []
    action.toggled.connect(seen.append)

    assert _ShowQgisBeforeExit(action).allowExit() is True
    assert not action.isChecked()
    assert seen == [False]
