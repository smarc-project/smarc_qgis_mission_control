from uuid import UUID

from qgis.PyQt.QtCore import QAbstractItemModel, QModelIndex, Qt, pyqtSlot

from ..domain.missionplan import TaskGroup
from ..mission.MissionDocument import MissionDocument

__all__ = ["TaskTreeModel"]


class TaskTreeModel(QAbstractItemModel):
    """The mission as a tree. The root row is the plan. Children are tasks or groups."""

    _columns = ["Description", "Type"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: MissionDocument | None = None
        self._ids: dict[int, object] = {}
        self._editable = False

    def bind(self, doc: MissionDocument) -> None:
        self.unbind()
        self._doc = doc
        self._doc.taskAdded.connect(self._reset)
        self._doc.taskDeleted.connect(self._reset)
        self._doc.taskChanged.connect(self._on_task_changed)
        self._reset()

    def unbind(self) -> None:
        if self._doc is not None:
            self._doc.taskAdded.disconnect(self._reset)
            self._doc.taskDeleted.disconnect(self._reset)
            self._doc.taskChanged.disconnect(self._on_task_changed)
        self._doc = None
        self._reset()

    def setEditable(self, editable: bool) -> None:
        self._editable = editable

    def plan(self):
        return None if self._doc is None else self._doc.plan

    def node(self, index: QModelIndex):
        if not index.isValid():
            return None
        return self._ids.get(index.internalId())

    def _remember(self, node) -> int:
        key = id(node)
        self._ids[key] = node
        return key

    def _children_of(self, node) -> list:
        plan = self.plan()
        if node is plan:
            return plan.tasks
        if isinstance(node, TaskGroup):
            return node.children
        return []

    def _reset(self, *_) -> None:
        self.beginResetModel()
        self._ids.clear()
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        plan = self.plan()
        if plan is None:
            return 0
        if not parent.isValid():
            return 1
        return len(self._children_of(self.node(parent)))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._columns)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        plan = self.plan()
        if plan is None or row < 0 or column < 0:
            return QModelIndex()
        if not parent.isValid():
            if row != 0:
                return QModelIndex()
            return self.createIndex(0, column, self._remember(plan))
        children = self._children_of(self.node(parent))
        if row >= len(children):
            return QModelIndex()
        return self.createIndex(row, column, self._remember(children[row]))

    def parent(self, index: QModelIndex) -> QModelIndex:
        node = self.node(index)
        plan = self.plan()
        if node is None or node is plan or plan is None:
            return QModelIndex()
        owner, _row = _owner_and_row(plan, node)
        if owner is None:
            return self.createIndex(0, 0, self._remember(plan))
        _grand, row = _owner_and_row(plan, owner)
        return self.createIndex(row, 0, self._remember(owner))

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        node = self.node(index)
        plan = self.plan()
        if index.column() == 0:
            if node is plan:
                return plan.description or plan.name
            return node.description
        if index.column() == 1:
            if node is plan:
                return plan.name if plan.name in ("seq", "conc") else "seq"
            return node.type
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._columns[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        flags = super().flags(index)
        if self._editable and index.column() == 0 and self.node(index) is not self.plan():
            flags |= Qt.ItemIsEditable
        return flags

    @pyqtSlot(UUID)
    def _on_task_changed(self, task_uuid: UUID) -> None:
        self._reset()


def _owner_and_row(plan, node):
    """Return (parent group or None if the node is directly under the plan, row)."""
    if node in plan.tasks:
        return None, plan.tasks.index(node)

    def walk(children):
        for child in children:
            if not isinstance(child, TaskGroup):
                continue
            if node in child.children:
                return child, child.children.index(node)
            found = walk(child.children)
            if found is not None:
                return found
        return None

    return walk(plan.tasks)
