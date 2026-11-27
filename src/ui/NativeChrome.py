from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtWidgets import QDockWidget, QMainWindow, QToolBar, QWidget

__all__ = ["NativeChrome"]


class NativeChrome(QObject):
    """Hides the main window's own toolbars and panels, and brings back the ones it hid.

    Only this session changes. QGIS saves the window layout on its way out, so the caller
    restores before that (see the exit blocker in main.py), or the next start would open
    with QGIS's own toolbars and panels still gone.
    """

    def __init__(self, mainWindow: QMainWindow, keep: list[QWidget]) -> None:
        super().__init__(mainWindow)
        self._window = mainWindow
        self._keep = keep
        self._hidden: list[QWidget] = []

    def isHidden(self) -> bool:
        return bool(self._hidden)

    def setHidden(self, hide: bool) -> None:
        if hide:
            self.hide()
        else:
            self.restore()

    def hide(self) -> None:
        if self._hidden:
            return
        for bar in self._bars():
            if bar in self._keep:
                continue
            # The View menu's tick is what the person sees as "this one is open".
            if bar.toggleViewAction().isChecked():
                self._hidden.append(bar)
                bar.setVisible(False)

    def restore(self) -> None:
        for bar in self._hidden:
            # Another plugin can unload while QGIS is hidden and take its toolbar with it.
            if not sip.isdeleted(bar):
                bar.setVisible(True)
        self._hidden = []

    def _bars(self) -> list[QWidget]:
        direct = Qt.FindDirectChildrenOnly
        return [*self._window.findChildren(QToolBar, options=direct),
                *self._window.findChildren(QDockWidget, options=direct)]
