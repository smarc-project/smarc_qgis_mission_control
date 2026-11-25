from typing import Type
from uuid import UUID

from qgis.core import QgsApplication

from qgis.PyQt.QtCore import QItemSelection, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QAbstractItemDelegate, QAction, QHeaderView, QWidget

from ...domain.tasks import Task
from ...domain.waypoints import Waypoint
from ...mission.MissionContext import MissionContext
from ...mission.MissionDocument import MissionDocument
from ...model.WaypointListModel import WaypointListModel
from ..generated.WaypointTableWidgetUi import Ui_WaypointTableWidget

__all__ = ['WaypointTableWidget']

class WaypointTableWidget(QWidget):
    _taskCls: Type[Task]
    _model: WaypointListModel
    _moveWaypointAction: QAction
    _rotateWaypointsAction: QAction

    addWaypointRequested = pyqtSignal(QAction, int, UUID, str, bool)
    selectLocationRequested = pyqtSignal(QAction, UUID, bool)
    rotateWaypointsRequested = pyqtSignal(list) # list[UUID]

    def __init__(self, taskCls: Type[Task], fieldName: str, waypointCls: Type[Waypoint],
                 missionContext: MissionContext, parent: QWidget|None = None):
        super().__init__(parent)

        self._taskCls = taskCls
        self._fieldName = fieldName
        self._missionContext = missionContext
        # The waypoint the map tool moves while "Move Waypoint" is pressed.
        self._movingUuid: UUID | None = None

        schema = waypointCls.schema()
        self._model = WaypointListModel(schema, longHeaders = False)

        self.ui = Ui_WaypointTableWidget()
        self.ui.setupUi(self)

        self.setup()

    def setup(self):
        # Model setup
        self.ui.waypointTable.setModel(self._model)
        self.ui.waypointTable.selectionModel().selectionChanged.connect(
            self.onWaypointSelectionChanged)

        # Respect edit mode
        self._missionContext.editModeChanged.connect(
            self.onEditModeChanged
        )
        # Make sure any pending changes are submitted
        self._missionContext.editingAboutToFinish.connect(self.onEditingAboutToFinish)

        # Handling of the waypoint map tools
        self.addWaypointRequested.connect(
            self._missionContext.mapManager.onAddWaypointRequested
        )
        self.selectLocationRequested.connect(
            self._missionContext.mapManager.onSelectLocationRequested
        )
        self.rotateWaypointsRequested.connect(
            self._missionContext.mapManager.onRotateWaypointsRequested
        )

        # Waypoint Table
        self.ui.waypointTable.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self.ui.waypointTable.verticalHeader().setSectionResizeMode(
            QHeaderView.Fixed
        )
        self.ui.waypointTable.verticalHeader().setDefaultAlignment(
            Qt.AlignRight
        )

        # Button "Add Waypoint"
        addWaypointAction = QAction(
            QgsApplication.getThemeIcon("symbologyAdd.svg"),
            "..."
        )
        addWaypointAction.setCheckable(self.ui.buttonAddWaypoint.isCheckable())
        addWaypointAction.toggled.connect(self.onAddWaypointToggled)
        self.ui.buttonAddWaypoint.setDefaultAction(addWaypointAction)

        # Button "Remove Waypoint"
        self.ui.buttonRemoveWaypoint.setIcon(
            QgsApplication.getThemeIcon('symbologyRemove.svg')
        )
        self.ui.buttonRemoveWaypoint.clicked.connect(self.onRemoveWaypointClicked)
        # Button "Move Waypoint": the next map click moves the selected waypoint there.
        self._moveWaypointAction = moveWaypointAction = QAction(
            QgsApplication.getThemeIcon('mActionPanTo.svg'),
            "Move Waypoint"
        )
        moveWaypointAction.setCheckable(True)
        moveWaypointAction.setToolTip(
            "Click on the map to move the selected waypoint there. Right-click to stop.")
        moveWaypointAction.toggled.connect(self.onSelectLocationToggled)
        # The button takes its enabled state from this action, so the action is what gets disabled.
        moveWaypointAction.setEnabled(False)
        self.ui.buttonMoveWaypoint.setDefaultAction(moveWaypointAction)
        # Button "Rotate Waypoints": hands the waypoints to QGIS's own Rotate Feature(s) tool.
        self._rotateWaypointsAction = rotateWaypointsAction = QAction(
            QgsApplication.getThemeIcon('mActionRotatePointSymbols.svg'),
            "Rotate Waypoints"
        )
        rotateWaypointsAction.setToolTip(
            "Rotate the selected waypoints, or all of this task's, on the map: "
            "click, move the mouse to turn them around their centre, click again to drop.")
        rotateWaypointsAction.triggered.connect(self.onRotateWaypointsTriggered)
        rotateWaypointsAction.setEnabled(False)
        self.ui.buttonRotateWaypoints.setDefaultAction(rotateWaypointsAction)
        # Waypoints come and go without a selection change.
        for signal in (self._model.rowsInserted, self._model.rowsRemoved, self._model.modelReset):
            signal.connect(self._refreshRotateEnabled)
        # Button "Move Up"
        self.ui.buttonMoveWaypointUp.setIcon(
            QgsApplication.getThemeIcon('mActionArrowUp.svg')
        )
        # Button "Move Down"
        self.ui.buttonMoveWaypointDown.setIcon(
            QgsApplication.getThemeIcon('mActionArrowDown.svg')
        )

        # Ensure correct state for buttons
        self.onWaypointSelectionChanged(None, None)

    def bind(self, doc: MissionDocument, taskUuid: UUID):
        # A model reset clears the selection without selectionChanged, so stop here.
        self._stopMoving()
        self._model.bind(doc, taskUuid, self._fieldName)

    def unbind(self):
        self._stopMoving()
        self._model.unbind()

    @pyqtSlot(QItemSelection, QItemSelection)
    def onWaypointSelectionChanged(self, selected: QItemSelection | None,
                               deselected: QItemSelection | None) -> None:
        sel = self.ui.waypointTable.selectionModel()
        rows = sel.selectedRows()

        # Enable/disable waypoint table buttons as needed
        self.ui.buttonRemoveWaypoint.setEnabled(bool(rows))
        self._moveWaypointAction.setEnabled(len(rows) == 1)
        self._refreshRotateEnabled()
        # The tool moves one waypoint. A different selection ends it.
        if self._movingUuid is not None and (
                len(rows) != 1 or self._model.item(rows[0].row()).uuid != self._movingUuid):
            self._stopMoving()
        # TODO
        # self.ui.buttonMoveWaypointUp.setEnabled(bool(rows) and rows[0].row() > 0)
        # self.ui.buttonMoveWaypointDown.setEnabled(bool(rows) \
        #     and rows[-1].row() < len(self._model.items()) - 1)

    @pyqtSlot()
    def onEditingAboutToFinish(self):
        editor = self.ui.waypointTable.focusWidget()
        if editor is None or editor is self.ui.waypointTable:
            # No open editor
            return

        self.ui.waypointTable.commitData(editor)
        self.ui.waypointTable.closeEditor(editor, QAbstractItemDelegate.NoHint)

    @pyqtSlot(bool)
    def onEditModeChanged(self, editMode: bool):
        if not editMode:
            self._stopMoving()
        self._model.setEditable(editMode)
        self.ui.waypointTableSideBar.setEnabled(editMode)
        self.ui.waypointTable.setEnabled(editMode)

    @pyqtSlot(bool)
    def onAddWaypointToggled(self, state: bool):
        assert(self._model._task)
        self.addWaypointRequested.emit(
            self.ui.buttonAddWaypoint.defaultAction(),
            self._model.rowCount(), # add after last waypoint
            self._model._task.uuid,
            self._fieldName,
            state
        )

    @pyqtSlot()
    def onRemoveWaypointClicked(self) -> None:
        sel = self.ui.waypointTable.selectionModel()
        indexes = sel.selectedRows()
        self._model.deleteWaypointsAtRows([index.row() for index in indexes])

    @pyqtSlot(bool)
    def onSelectLocationToggled(self, state: bool):
        action = self._moveWaypointAction
        if not state:
            if self._movingUuid is not None:
                uuid, self._movingUuid = self._movingUuid, None
                self.selectLocationRequested.emit(action, uuid, False)
            return
        rows = self.ui.waypointTable.selectionModel().selectedRows()
        if len(rows) != 1:
            action.setChecked(False)
            return
        self._movingUuid = self._model.item(rows[0].row()).uuid
        self.selectLocationRequested.emit(action, self._movingUuid, True)

    def _waypointsToRotate(self) -> list[UUID]:
        """The selected waypoints, or every waypoint of the task when none is selected."""
        rows = [index.row() for index in self.ui.waypointTable.selectionModel().selectedRows()]
        if not rows:
            rows = list(range(self._model.rowCount()))
        return [self._model.item(row).uuid for row in rows]

    @pyqtSlot()
    def _refreshRotateEnabled(self) -> None:
        # Turning one point around itself does nothing.
        self._rotateWaypointsAction.setEnabled(len(self._waypointsToRotate()) >= 2)

    @pyqtSlot()
    def onRotateWaypointsTriggered(self) -> None:
        self._stopMoving()
        self.rotateWaypointsRequested.emit(self._waypointsToRotate())

    def _stopMoving(self) -> None:
        if self._moveWaypointAction.isChecked():
            self._moveWaypointAction.setChecked(False)
