from uuid import UUID

from qgis.PyQt.QtCore import QModelIndex, Qt, QVariant, pyqtSlot

from ..domain.tasks import Task
from ..domain.taskspatial import isWaypointField, isWaypointListField
from ..mission.MissionDocument import MissionDocument
from .SchemaBasedModel import SchemaBasedModel

__all__ = ["WaypointListModel"]

class WaypointListModel(SchemaBasedModel):
    _doc: MissionDocument | None
    _task: Task | None
    _fieldName: str | None
    _isList: bool

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._doc = None
        self._task = None
        self._fieldName = None
        self._isList = False

    def bind(self, doc: MissionDocument, taskUuid: UUID, fieldName: str):
        task = doc.index.taskByUuid(taskUuid)
        if task is None:
            return

        self.unbind()

        self._doc = doc
        self._task = task
        self._fieldName = fieldName


        try:
            field = [
                field for field in type(task).schema().fields
                if field.name == fieldName
            ][0]
        except IndexError:
            field = None
        if field is None or not (isWaypointField(field) or isWaypointListField(field)):
            raise ValueError(f"Task has no waypoint field named '{fieldName}'")

        value = field.value(task)
        self._isList = isWaypointListField(field)
        self.setItems(value if self._isList else [value])

        self._doc.waypointChanged.connect(self.onWaypointChanged)
        self._doc.beforeWaypointAdded.connect(self.onBeforeWaypointAdded)
        self._doc.waypointAdded.connect(self.onWaypointAdded)
        self._doc.beforeWaypointDeleted.connect(self.onBeforeWaypointDeleted)
        self._doc.waypointDeleted.connect(self.onWaypointDeleted)

    def unbind(self):
        if self._doc is not None:
            self._doc.waypointChanged.disconnect(self.onWaypointChanged)
            self._doc.beforeWaypointAdded.disconnect(self.onBeforeWaypointAdded)
            self._doc.waypointAdded.disconnect(self.onWaypointAdded)
            self._doc.beforeWaypointDeleted.disconnect(self.onBeforeWaypointDeleted)
            self._doc.waypointDeleted.disconnect(self.onWaypointDeleted)

        self._doc = None
        self._task = None
        self._fieldName = None
        self._isList = False
        self.setItems([])

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        flags = super().flags(index)
        if self.isEditable():
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value: QVariant,
                role: int = Qt.EditRole) -> bool:
        # TODO: check reference code for editability
        if role != Qt.EditRole or not self.isEditable():
            return False
        if self._doc is None or self._task is None:
            # TODO: invalid mapping
            return False

        col = index.column()
        wp  = self.item(index.row())

        # Special handling for longitude/latitude which actually influence geometry
        # present on the map layer
        field = wp.schema().fields[col]
        # TODO: assumes all fields are floats...
        if float(value) == field.value(wp):
            # No change! Nothing to do.
            return False

        if field.name in ('latitude', 'longitude'):
            if field.name == 'latitude':
                latitude = float(value)
                longitude = wp.longitude
            else:
                latitude = wp.latitude
                longitude = float(value)

            # TODO: have it return bool as status
            self._doc.setWaypointPosition(wp.uuid, latitude, longitude)
            return True
        else:
            # TODO: have it return bool as status
            self._doc.setWaypointField(wp.uuid, col, float(value))
            return True

    def _rowForUuid(self, waypointUuid: UUID) -> int | None:
        for row, waypoint in enumerate(self.items()):
            if waypoint.uuid == waypointUuid:
                return row
        return None

    @pyqtSlot(UUID)
    def onWaypointChanged(self, waypointUuid: UUID):
        if self._doc is None or self._task is None:
            return

        waypointIndex = self._rowForUuid(waypointUuid)
        if waypointIndex is None:
            # Change to a task not managed by this model
            return

        idxStart = self.index(waypointIndex, 0)
        idxEnd = self.index(waypointIndex, self.columnCount() - 1)
        self.dataChanged.emit(idxStart, idxEnd, [Qt.DisplayRole, Qt.EditRole])

    @pyqtSlot(UUID, str, UUID, int)
    def onBeforeWaypointAdded(self, taskUuid: UUID, fieldName: str, waypointUuid: UUID,
                              waypointIndex: int):
        if self._doc is None or self._task is None or not self._isList:
            return

        if taskUuid != self._task.uuid or fieldName != self._fieldName:
            # Change to a task/field not managed by this model
            return

        self.beginInsertRows(QModelIndex(), waypointIndex, waypointIndex)

    @pyqtSlot(UUID, str, UUID)
    def onWaypointAdded(self, taskUuid: UUID, fieldName: str, waypointUuid: UUID):
        if self._doc is None or self._task is None or not self._isList:
            return

        if taskUuid != self._task.uuid or fieldName != self._fieldName:
            # Change to a task/field not managed by this model
            return

        self.endInsertRows()

    @pyqtSlot(UUID, str, UUID, int)
    def onBeforeWaypointDeleted(self, taskUuid: UUID, fieldName: str,
                                waypointUuid: UUID, waypointIndex: int):
        if self._doc is None or self._task is None or not self._isList:
            return

        if taskUuid != self._task.uuid or fieldName != self._fieldName:
            # Change to a task/field not managed by this model
            return

        self.beginRemoveRows(QModelIndex(), waypointIndex, waypointIndex)

    @pyqtSlot(UUID, str, UUID, int)
    def onWaypointDeleted(self, taskUuid: UUID, fieldName: str, waypointUuid: UUID,
                          waypointIndex: int):
        if self._doc is None or self._task is None or not self._isList:
            return

        if taskUuid != self._task.uuid or fieldName != self._fieldName:
            # Change to a task not managed by this model
            return

        self.endRemoveRows()

    def deleteWaypointsAtRows(self, rows: list[int]):
        if self._doc is None or self._task is None or not self._isList:
            return

        if not self.isEditable():
            return

        # Validate row indexes
        for row in rows:
            if row < 0 or row >= self.rowCount():
                return

        uuids = [self.item(row).uuid for row in rows]
        self._doc.deleteWaypoints(uuids)
