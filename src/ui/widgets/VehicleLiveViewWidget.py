from math import degrees

from qgis.core import QgsApplication

from qgis.PyQt.QtCore import QSignalBlocker, QSize, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QColor, QMovie
from qgis.PyQt.QtWidgets import QWidget

from ...context.FleetState import VehicleState
from ..generated.VehicleLiveViewWidgetUi import Ui_VehicleLiveViewWidget


class VehicleLiveViewWidget(QWidget):
    showOnMapChanged = pyqtSignal(str, bool)
    mapColorChanged = pyqtSignal(str, QColor)
    lookAtRequested = pyqtSignal(str)

    toggled = pyqtSignal(str, bool)
    collapsedChanged = pyqtSignal(str, bool)
    _checked: bool = True
    _collapsed: bool = False

    def __init__(self, vehicleTopic: str, parent: QWidget | None = None):
        super().__init__(parent)

        self._vehicleTopic = vehicleTopic

        self.ui = Ui_VehicleLiveViewWidget()
        self.ui.setupUi(self)

        self.setup()

    def setup(self):
        self.ui.vehicleNameLabel.setText(self._vehicleTopic.split('/')[-1])
        self.ui.modeLabel.setText('Mode')
        self.ui.statusLabel.setText('Status')

        self.ui.lookAtButton.setIcon(
            QgsApplication.getThemeIcon("console/iconSearchEditorConsole.svg")
        )
        self.ui.lookAtButton.clicked.connect(self.onLookAtClicked)

        # Actually render the bottom border
        self.setAttribute(Qt.WA_StyledBackground, True)

        self.ui.mapColorButton.colorChanged.connect(self.onMapColorChanged)

        # Collapse/expand the body contents
        self.ui.collapseExpandButton.clicked.connect(self.toggleCollapsed)
        self.setCollapsed(True)

        # Change header colors when the checkbox is toggled
        self.ui.showOnMapCheckBox.toggled.connect(self.setChecked)
        self.setChecked(False)

        self.heartbeat_gif = QMovie(":/custom_icons/heartbeat.gif")  # if using Qt resources
        self.ui.gifLabel.setFixedSize(32, 32)
        self.heartbeat_gif.setScaledSize(QSize(32, 32))
        self.ui.gifLabel.setMovie(self.heartbeat_gif)

    def updateState(self, state: VehicleState):
        self.ui.modeLabel.setText(f'({state.mode:s})')

        if state.latitude is not None:
            self.ui.latValueLabel.setText(f'{state.latitude:.5f}°')
        else:
            self.ui.latValueLabel.setText('?')
        if state.longitude is not None:
            self.ui.lonValueLabel.setText(f'{state.longitude:.5f}°')
        else:
            self.ui.lonValueLabel.setText('?')
        if state.heading is not None:
            self.ui.headingValueLabel.setText(f'{state.heading:.1f}°')
        else:
            self.ui.headingValueLabel.setText('?')

        if state.depth is not None:
            self.ui.depthValueLabel.setText(f'{state.depth:.1f} m')
        else:
            self.ui.depthValueLabel.setText('?')
        if state.altitude is not None:
            self.ui.altitudeValueLabel.setText(f'{state.altitude:.1f} m')
        else:
            self.ui.altitudeValueLabel.setText('?')
        if state.speed is not None:
            self.ui.speedValueLabel.setText(f'{state.speed:.1f} m/s')
        else:
            self.ui.speedValueLabel.setText('?')

        if state.course is not None:
            self.ui.courseValueLabel.setText(f'{state.course:.1f}°')
        else:
            self.ui.courseValueLabel.setText('?')
        if state.roll is not None:
            # roll is in radians
            self.ui.rollValueLabel.setText(f'{degrees(state.roll):.1f}°')
        else:
            self.ui.rollValueLabel.setText('?')
        if state.pitch is not None:
            # pitch is in radians
            self.ui.pitchValueLabel.setText(f'{degrees(state.pitch):.1f}°')
        else:
            self.ui.pitchValueLabel.setText('?')

        if state.executingTasks is not None:
            if len(state.executingTasks):
                self.ui.taskValueLabel.setText(state.executingTasks[0].type)
                self.ui.statusLabel.setText('Running')
            else:
                self.ui.taskValueLabel.setText('-')
                self.ui.statusLabel.setText('Idle')
        else:
            self.ui.taskValueLabel.setText('?')
            self.ui.statusLabel.setText('Other')

    @pyqtSlot(bool)
    def onShowOnMapChanged(self, state: bool):
        self.showOnMapChanged.emit(self._vehicleTopic, state)

    @pyqtSlot(QColor)
    def onMapColorChanged(self, color: QColor):
        self.mapColorChanged.emit(self._vehicleTopic, color)

    @pyqtSlot()
    def onLookAtClicked(self):
        self.lookAtRequested.emit(self._vehicleTopic)

    def isChecked(self):
        return self._checked

    @pyqtSlot("bool")
    def setChecked(self, value: bool):
        print("VehicleLiveViewWidget.setChecked() is called")

        if self._checked == value:
            return

        self._checked = value
        self.setProperty("checked", value)

        # prevent infinite loops if caused by the checkbox
        with QSignalBlocker(self.ui.showOnMapCheckBox):
            self.ui.showOnMapCheckBox.setChecked(value)

        self._applyStyles()

        # emit change signal
        self.toggled.emit(self._vehicleTopic, value)
        self.showOnMapChanged.emit(self._vehicleTopic, value)

    @pyqtSlot("bool")
    def setCollapsed(self, value: bool):
        if self._collapsed == value:
            return

        self._collapsed = value
        self.setProperty("expanded", not value)

        if value:
            self.ui.collapseExpandButton.setArrowType(Qt.RightArrow)
        else:
            self.ui.collapseExpandButton.setArrowType(Qt.DownArrow)

        # Visibility is inverse of collapsed
        self.ui.body.setVisible(not value)

        # emit change signal
        self.collapsedChanged.emit(self._vehicleTopic, value)

    def isCollapsed(self):
        return self._collapsed
    
    def toggleCollapsed(self):
        self.setCollapsed(not self._collapsed)

    def _applyStyles(self):
        self.setStyleSheet(self.styleSheet())

    @pyqtSlot()
    def onHeartbeat(self):
        self.heartbeat_gif.stop()
        self.heartbeat_gif.jumpToFrame(0)
        self.heartbeat_gif.start()