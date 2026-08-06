from typing import Type
from uuid import UUID

from qgis.core import QgsApplication

from qgis.PyQt.QtCore import pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QAction, QWidget

from ...domain.tasks import Task
from ...domain.waypoints import Waypoint
from ...mission.MissionContext import MissionContext
from ...mission.MissionDocument import MissionDocument
from ...model.WaypointListModel import WaypointListModel
from ..generated.WaypointFormWidgetUi import Ui_WaypointFormWidget
from .AutomaticFormWidget import AutomaticFormWidget

__all__ = ['WaypointFormWidget']


class WaypointFormWidget(AutomaticFormWidget):
    _taskCls: Type[Task]
    _model: WaypointListModel

    selectLocationRequested = pyqtSignal(QAction, UUID, bool)

    def __init__(self, taskCls: Type[Task], fieldName: str, waypointCls: Type[Waypoint],
                 missionContext: MissionContext, parent: QWidget | None = None):
        schema = waypointCls.schema()
        self._model = WaypointListModel(schema, longHeaders = True)
        super().__init__(self._model, parent)

        self._taskCls = taskCls
        self._fieldName = fieldName
        self._missionContext = missionContext

        self.ui = Ui_WaypointFormWidget()
        self.ui.setupUi(self)

        self.setup()

    def setup(self):
        self.buildForm(self.ui.waypointForm)

        # Respect edit mode
        self._missionContext.editModeChanged.connect(
            self.onEditModeChanged
        )
        # Make sure any pending changes are submitted
        self._missionContext.editingAboutToFinish.connect(self._mapper.submit)

        # Handling of the waypoint map tools
        # TODO:
        self.selectLocationRequested.connect(
            self._missionContext.mapManager.onSelectLocationRequested
        )

        # Button "Select Location"
        selectLocationAction = QAction(
            QgsApplication.getThemeIcon("mActionPanTo.svg"),
            "..."
        )
        selectLocationAction.setCheckable(self.ui.buttonSelectLocation.isCheckable())
        selectLocationAction.toggled.connect(self.onSelectLocationToggled)
        self.ui.buttonSelectLocation.setDefaultAction(selectLocationAction)
        # self.ui.buttonSelectLocation.clicked.connect(self.onSelectLocationToggled)


    def bind(self, doc: MissionDocument, taskUuid: UUID):
        self._model.bind(doc, taskUuid, self._fieldName)
        self._mapper.toFirst()

    def unbind(self):
        self._model.unbind()

    @pyqtSlot(bool)
    def onEditModeChanged(self, editMode: bool):
        self.setEditMode(editMode)
        self.ui.buttonSelectLocation.setEnabled(editMode)

    @pyqtSlot(bool)
    def onSelectLocationToggled(self, state: bool):
        self.selectLocationRequested.emit(
            self.ui.buttonSelectLocation.defaultAction(),
            self._model.item(0).uuid,
            state
        )
