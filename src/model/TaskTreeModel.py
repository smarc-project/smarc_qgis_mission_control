from uuid import UUID

from qgis.PyQt.QtCore import QAbstractItemModel, QModelIndex, Qt, pyqtSignal, pyqtSlot

from ..domain.missionplan import TaskGroup, walk
from ..domain.tasks import Task
from ..mission.MissionDocument import MissionDocument

__all__ = ["TaskTreeModel"]


class TaskTreeModel(QAbstractItemModel):
    """The mission as a tree. The root row is the plan. Children are tasks or groups."""

    _columns = ["Description", "Type"]

    # After the reset that follows an add, with the new node's index, so the view can select it.
    nodeAdded = pyqtSignal(QModelIndex)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: MissionDocument | None = None
        self._ids: dict[int, object] = {}
        self._editable = False

    def bind(self, doc: MissionDocument) -> None:
        self.unbind()
        self._doc = doc
        self._doc.taskAdded.connect(self._on_task_added)
        self._doc.taskDeleted.connect(self._reset)
        self._doc.taskChanged.connect(self._on_task_changed)
        self._reset()

    def unbind(self) -> None:
        if self._doc is not None:
            self._doc.taskAdded.disconnect(self._on_task_added)
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

    def indexOf(self, node, column: int = 0) -> QModelIndex:
        plan = self.plan()
        if plan is None or node is None:
            return QModelIndex()
        if node is plan:
            return self.createIndex(0, column, self._remember(plan))
        location = plan.locate(node)
        if location is None:
            return QModelIndex()
        return self.createIndex(location[1], column, self._remember(node))

    def _node_by_uuid(self, uuid: UUID):
        plan = self.plan()
        for _, _, node in walk(plan.tasks):
            if node.uuid == uuid:
                return node
        return None

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
        location = plan.locate(node)
        if location is None:
            return QModelIndex()
        return self.indexOf(location[0] or plan)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole):
            return None
        node = self.node(index)
        plan = self.plan()
        if index.column() == 0:
            return (plan.description or plan.name) if node is plan else node.description
        if index.column() == 1:
            if node is plan:
                kind = plan.root_kind
            elif isinstance(node, TaskGroup):
                kind = node.kind
            else:
                return node.type
            return kind.value if role == Qt.EditRole else kind.label
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._columns[section]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        flags = super().flags(index)
        # Only a task has an undoable description setter.
        if self._editable and index.column() == 0 and isinstance(self.node(index), Task):
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        node = self.node(index)
        if (role != Qt.EditRole or not self._editable or self._doc is None
                or index.column() != 0 or not isinstance(node, Task)):
            return False
        self._doc.setTaskDescription(node.uuid, str(value))
        return True

    @pyqtSlot(UUID, int)
    def _on_task_added(self, uuid: UUID, _row: int) -> None:
        self._reset()
        self.nodeAdded.emit(self.indexOf(self._node_by_uuid(uuid)))

    @pyqtSlot(UUID)
    def _on_task_changed(self, task_uuid: UUID) -> None:
        # A field edit repaints its row. A reset would collapse the tree under the cursor.
        node = self._node_by_uuid(task_uuid)
        first = self.indexOf(node)
        if first.isValid():
            self.dataChanged.emit(first, self.indexOf(node, len(self._columns) - 1))

