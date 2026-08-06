from typing import Any, Sequence

from qgis.PyQt.QtCore import QAbstractTableModel, QModelIndex, Qt
from qgis.PyQt.QtWidgets import QWidget

__all__ = ["ItemBasedModel"]


class ItemBasedModel(QAbstractTableModel):
    _items: list[Any]
    _editable: bool

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._items = []
        self._editable = False

    def item(self, index: int) -> Any:
        return self._items[index]

    def items(self) -> Sequence[Any]:
        return self._items

    def setItems(self, items: list[Any] | None):
        self.beginResetModel()
        self._items = items if items is not None else []
        self.endResetModel()

    def isEditable(self) -> bool:
        return self._editable

    def setEditable(self, editable: bool):
        if self._editable == editable:
            return

        self._editable = editable

        rows = self.rowCount()
        cols = self.columnCount()
        if not (rows and cols):
            return

        topleft = self.index(0, 0)
        botright = self.index(rows - 1, cols - 1)
        self.dataChanged.emit(topleft, botright, [Qt.EditRole])

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        flags = super().flags(index)
        if self.isEditable():
            flags |= Qt.ItemIsEditable
        return flags

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def removeRows(self, first: int, count: int,
                   parent: QModelIndex = QModelIndex()) -> bool:
        last = first + count
        if first < 0 or count <= 0 or last > len(self._items):
            # Bounds check fail
            return False

        self.beginRemoveRows(parent, first, last - 1)
        # In-place modification propagates changes to the source list, e.g. a waypoint
        # list for a task
        del self._items[first:last]
        self.endRemoveRows()

        return True

    def moveRowsUp(self, first: int, count: int) -> bool:
        # Bounds checks
        if first <= 0 or count <= 0:
            return False

        last = first + count
        if last > len(self._items):
            return False

        # Perform move
        self.beginMoveRows(QModelIndex(), first, last - 1, QModelIndex(), first - 1)
        block = self._items[first:last]
        displaced = self._items[first - 1 : first]
        # In-place modification propagates changes to the source list, e.g. a waypoint
        # list for a task
        self._items[first - 1 : last] = block + displaced
        self.endMoveRows()

        return True

    def moveRowsDown(self, first: int, count: int) -> bool:
        # Bounds checks
        if first < 0 or count <= 0:
            return False

        last = first + count
        if last >= len(self._items):
            return False

        # Perform move
        self.beginMoveRows(QModelIndex(), first, last - 1, QModelIndex(), last + 1)
        block = self._items[first:last]
        displaced = self._items[last : last + 1]
        # In-place modification propagates changes to the source list, e.g. a waypoint
        # list for a task
        self._items[first : last + 1] = displaced + block
        self.endMoveRows()

        return True
