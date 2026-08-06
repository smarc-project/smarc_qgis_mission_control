from qgis.core import QgsApplication

from qgis.PyQt.QtCore import QSignalBlocker, QSize, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QMovie
from qgis.PyQt.QtWidgets import QHeaderView, QWidget

from ...context.FleetState import VehicleState
from ...domain.waraps import WaraPsExecutingTask
from ...model.SchemaBasedModel import SchemaBasedModel
from ..generated.VehicleCardWidgetUi import Ui_VehicleCardWidget


class VehicleCardWidget(QWidget):
    toggled = pyqtSignal(bool)
    collapsedChanged = pyqtSignal(bool)
    lookAtRequested = pyqtSignal(str)

    _checked: bool = False
    _collapsed: bool = False

    def __init__(self, name: str, tasks, parent: QWidget | None = None):
        super().__init__(parent)

        self.ui = Ui_VehicleCardWidget()
        self.ui.setupUi(self)
        self.setupUi2()

        self.setName(name.split('/')[-1])
        self._name = name

    def setupUi2(self):
        # Draw own background
        self.ui.header.setAutoFillBackground(True)

        # TODO
        self._taskListModel = SchemaBasedModel(
            schema=WaraPsExecutingTask.schema(),
            longHeaders=True,
            parent=self
        )
        self.ui.taskList.setModel(self._taskListModel)
        # TODO

        # Collapse/expand the body contents
        self.ui.collapseExpandButton.clicked.connect(self.toggleCollapsed)
        self.setCollapsed(True)

        # Change header colors when the checkbox is toggled
        self.ui.cardCheckBox.toggled.connect(self.setChecked)
        self.setChecked(False)

        # Setup display of the task table
        f = self.ui.taskList.font()
        # setFont does not work for horizontal header
        self.ui.taskList.horizontalHeader().setStyleSheet(
            f'font-size: {f.pointSize()}pt'
        )
        self.ui.taskList.verticalHeader().setFont(f)

        self.ui.taskList.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # Minimum will still be enough to fit the text
        self.ui.taskList.verticalHeader().setDefaultSectionSize(0)
        self.ui.taskList.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # self.ui.taskList.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        # self.ui.taskList.verticalHeader().setDefaultAlignment(Qt.AlignRight)
        # self.ui.taskList.verticalHeader().setDefaultAlignment(Qt.AlignCenter)

        # custom heartbeat
        self.heartbeat_gif = QMovie(":/custom_icons/heartbeat.gif")  # if using Qt resources
        self.ui.gifLabel.setFixedSize(32, 32)
        self.heartbeat_gif.setScaledSize(QSize(32, 32))
        self.ui.gifLabel.setMovie(self.heartbeat_gif)

        # look-at button
        self.ui.lookAtButton.setIcon(
            QgsApplication.getThemeIcon("console/iconSearchEditorConsole.svg")
        )
        self.ui.lookAtButton.clicked.connect(self.onLookAtClicked)

    def isChecked(self):
        return self._checked

    @pyqtSlot("bool")
    def setChecked(self, value: bool):
        if self._checked == value:
            return

        self._checked = value
        self.setProperty("checked", value)

        # prevent infinite loops if caused by the checkbox
        with QSignalBlocker(self.ui.cardCheckBox):
            self.ui.cardCheckBox.setChecked(value)

        self._applyStyles()

        self.toggled.emit(value)

    def isCollapsed(self):
        return self._collapsed

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

        self.collapsedChanged.emit(value)

    def toggleCollapsed(self):
        self.setCollapsed(not self._collapsed)

    def name(self) -> str:
        return self.ui.vehicleNameLabel.text()

    def setName(self, name: str):
        self.ui.vehicleNameLabel.setText(name)

    def _applyStyles(self):
        self.setStyleSheet(self.styleSheet())

    def updateState(self, state: VehicleState):
        self.ui.modeLabel.setText(f'({state.mode:s})')

        self._taskListModel.setItems(state.executingTasks)

        if state.executingTasks is not None:
            if len(state.executingTasks):
                self.ui.statusLabel.setText('Running')
            else:
                self.ui.statusLabel.setText('Idle')
        else:
            self.ui.statusLabel.setText('Other')

    @pyqtSlot()
    def onHeartbeat(self):
        self.heartbeat_gif.stop()
        self.heartbeat_gif.jumpToFrame(0)
        self.heartbeat_gif.start()

    @pyqtSlot()
    def onLookAtClicked(self):
        self.lookAtRequested.emit(self._name)