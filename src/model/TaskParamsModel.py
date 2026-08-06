from typing import Type
from uuid import UUID

from qgis.PyQt.QtCore import QModelIndex, Qt, QVariant, pyqtSlot

from ..domain.tasks import Task
from ..mission.MissionDocument import MissionDocument
from .SchemaBasedModel import SchemaBasedModel

__all__ = ["TaskParamsModel"]

class TaskParamsModel(SchemaBasedModel):
    _doc: MissionDocument | None
    _task: Task | None

    def __init__(self, taskCls: Type[Task]):
        super().__init__(taskCls.schema(), longHeaders = True)

        self._doc = None
        self._task = None

    def bind(self, doc: MissionDocument, taskUuid: UUID) -> None:
        task = doc.index.taskByUuid(taskUuid)
        if task is None:
            return

        self.unbind()

        self._doc = doc
        self._task = task

        self.setItems([task])

        self._doc.taskChanged.connect(self.onTaskChanged)

    def unbind(self) -> None:
        if self._doc is not None:
            self._doc.taskChanged.disconnect(self.onTaskChanged)

        self._doc = None
        self._task = None
        self.setItems([])

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        flags = super().flags(index)
        if self.isEditable():
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value: QVariant,
                role: int = Qt.EditRole) -> bool:
        if role != Qt.EditRole or not self.isEditable():
            return False
        if self._doc is None or self._task is None:
            # TODO: invalid mapping
            return False

        col = index.column()
        task = self.item(index.row())

        # Should only ever be scalar fields, as e.g. waypoints, etc. have custom
        # widgets, which will not trigger setData calls
        field = task.schema().fields[col]
        # TODO: a better, unified way of type conversions is in order
        if field.type()(value) == field.value(task):
            # No change! Nothing to do.
            return False

        # TODO: have it return bool as status
        self._doc.setTaskField(task.uuid, col, field.type()(value))
        return True

    @pyqtSlot(UUID)
    def onTaskChanged(self, taskUuid: UUID) -> None:
        if self._doc is None or self._task is None:
            return

        idxStart = self.index(0, 0)
        idxEnd = self.index(0, self.columnCount() - 1)
        self.dataChanged.emit(idxStart, idxEnd, [Qt.DisplayRole, Qt.EditRole])
