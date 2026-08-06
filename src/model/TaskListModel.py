from uuid import UUID

from qgis.PyQt.QtCore import QModelIndex, Qt, QVariant, pyqtSlot

from ..domain.tasks import Task
from ..mission.MissionDocument import MissionDocument
from .ItemBasedModel import ItemBasedModel

__all__ = ["TaskListModel"]

class TaskListModel(ItemBasedModel):
    _doc: MissionDocument | None
    _items: list[Task]
    _columns: list[str] = ["Description", "Type"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._doc = None

    def bind(self, doc: MissionDocument) -> None:
        self.unbind()

        self._doc = doc

        self.setItems(self._doc.plan.tasks)

        self._doc.taskChanged.connect(self.onTaskChanged)

    def unbind(self) -> None:
        if self._doc is not None:
            self._doc.taskChanged.disconnect(self.onTaskChanged)

        self._doc = None
        self.setItems([])

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        # TODO: integration with undo/redo?
        flags = super().flags(index)
        # Only column "Description" is editable
        if index.column() == 0 and self.isEditable():
            flags |= Qt.ItemIsEditable
        else:
            flags &= ~Qt.ItemIsEditable
        return flags

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal \
            and 0 <= section <= len(self._columns):
                return self._columns[section]

        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> str|None:
        if not index.isValid():
            return None

        if role in (Qt.DisplayRole, Qt.EditRole):
            task = self._items[index.row()]
            if index.column() == 0:
                # Description
                return task.description
            elif index.column() == 1:
                # Type
                return str(task.type)

        return None

    def setData(self, index: QModelIndex, value: QVariant,
                role: int = Qt.EditRole) -> bool:
        if role != Qt.EditRole or not self.isEditable() or self._doc is None:
            return False

        task = self._items[index.row()]
        col = index.column()
        if col == 0:
            self._doc.setTaskDescription(task.uuid, str(value))
            return True
        else:
            # TODO: report an error, this is a bug; only task description can be changed
            pass

        return False

    def _rowForUuid(self, taskUuid: UUID) -> int | None:
        for row, task in enumerate(self.items()):
            if task.uuid == taskUuid:
                return row
        return None

    @pyqtSlot(UUID)
    def onTaskChanged(self, taskUuid: UUID) -> None:
        if self._doc is None:
            return

        taskIndex = self._rowForUuid(taskUuid)
        if taskIndex is None:
            # TODO: change to a task not managed by this model? This shouldn't happen
            return

        idxStart = self.index(taskIndex, 0)
        idxEnd = self.index(taskIndex, self.columnCount() - 1)
        self.dataChanged.emit(idxStart, idxEnd, [Qt.DisplayRole, Qt.EditRole])
