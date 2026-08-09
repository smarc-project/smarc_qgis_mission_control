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

    addWaypointRequested = pyqtSignal(QAction, int, UUID, str, bool)
    selectLocationRequested = pyqtSignal(QAction, UUID, bool)

    def __init__(self, taskCls: Type[Task], fieldName: str, waypointCls: Type[Waypoint],
                 missionContext: MissionContext, parent: QWidget|None = None):
        super().__init__(parent)

        self._taskCls = taskCls
        self._fieldName = fieldName
        self._missionContext = missionContext

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
        # Ensure correct state for buttons
        self.onWaypointSelectionChanged(None, None)

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
        # Button "Move Waypoint"
        self.ui.buttonMoveWaypoint.setIcon(
            QgsApplication.getThemeIcon('mActionPanTo.svg')
        )
        # Button "Move Up"
        self.ui.buttonMoveWaypointUp.setIcon(
            QgsApplication.getThemeIcon('mActionArrowUp.svg')
        )
        # Button "Move Down"
        self.ui.buttonMoveWaypointDown.setIcon(
            QgsApplication.getThemeIcon('mActionArrowDown.svg')
        )

    def bind(self, doc: MissionDocument, taskUuid: UUID):
        self._model.bind(doc, taskUuid, self._fieldName)

    def unbind(self):
        self._model.unbind()

    @pyqtSlot(QItemSelection, QItemSelection)
    def onWaypointSelectionChanged(self, selected: QItemSelection | None,
                               deselected: QItemSelection | None) -> None:
        sel = self.ui.waypointTable.selectionModel()
        rows = sel.selectedRows()

        # Enable/disable waypoint table buttons as needed
        self.ui.buttonRemoveWaypoint.setEnabled(bool(rows))
        self.ui.buttonMoveWaypoint.setEnabled(len(rows) == 1)
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
        self.selectLocationRequested.emit(
            self.ui.buttonMoveWaypoint.defaultAction(),
            # TODO: not index 0, check selection
            self._model.item(0).uuid,
            state
        )
