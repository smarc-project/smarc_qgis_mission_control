from uuid import UUID

from qgis.core import QgsApplication

from qgis.PyQt.QtCore import QItemSelection, QItemSelectionModel, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import (
    QAbstractItemDelegate,
    QDataWidgetMapper,
    QDialog,
    QHeaderView,
    QMenu,
    QMessageBox,
    QToolButton,
    QTreeView,
    QWidget,
)

from ...domain.missionplan import TaskGroup
from ...domain.tasks import Task, TaskRegistry, UnsupportedTaskCreationError
from ...mission.MissionContext import MissionContext
from ...mission.MissionDocument import MissionDocument
from ...model.MissionParamsModel import MissionParamsModel
from ...model.TaskTreeModel import TaskTreeModel
from ..generated.MissionPlanWidgetUi import Ui_MissionPlanWidget
from .AddTaskDialog import AddTaskDialog
from .TaskEditorWidget import TaskEditorWidget


class MissionPlanWidget(QWidget):
    taskEditors: dict[str, TaskEditorWidget]

    _missionContext: MissionContext

    taskSelectionChanged = pyqtSignal(list)

    def __init__(self, missionContext: MissionContext,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._model = MissionParamsModel(self)
        self._missionContext = missionContext
        self._mapper = QDataWidgetMapper()
        self._mapper.setModel(self._model)
        self.taskEditors = {}
        self._selecting_family = False

        self.ui = Ui_MissionPlanWidget()
        self.ui.setupUi(self)

        self.setup()

    def setup(self) -> None:
        tree = QTreeView(self.ui.taskListWidget)
        tree.setObjectName("taskTree")
        tree.setEditTriggers(self.ui.taskList.editTriggers())
        tree.setSelectionMode(self.ui.taskList.selectionMode())
        tree.setSelectionBehavior(self.ui.taskList.selectionBehavior())
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.horizontalLayout.replaceWidget(self.ui.taskList, tree)
        self.ui.taskList.hide()
        self.ui.taskList.deleteLater()
        self.ui.taskList = tree

        self.taskListModel = TaskTreeModel()
        self.ui.taskList.setModel(self.taskListModel)

        self._mapper.addMapping(self.ui.missionPlanDescription, 0)
        self._mapper.addMapping(self.ui.missionPlanTimeout, 1)

        # Respect edit mode
        self._missionContext.editModeChanged.connect(self.onEditModeChanged)
        # Make sure any pending changes are submitted
        self._missionContext.editingAboutToFinish.connect(self.onEditingAboutToFinish)

        # Signals for refreshing the task list
        self._missionContext.taskAdded.connect(self.onTaskAdded)
        self._missionContext.taskDeleted.connect(self.onTaskDeleted)

        # Setup icons for the task buttons
        self.ui.buttonAddTask.setIcon(QgsApplication.getThemeIcon("symbologyAdd.svg"))
        self.ui.buttonRemoveTask.setIcon(
            QgsApplication.getThemeIcon("symbologyRemove.svg")
        )
        self.ui.buttonMoveTaskUp.setIcon(
            QgsApplication.getThemeIcon("mActionArrowUp.svg")
        )
        self.ui.buttonMoveTaskDown.setIcon(
            QgsApplication.getThemeIcon("mActionArrowDown.svg")
        )

        # Setup event handling for task buttons
        self.ui.buttonAddTask.clicked.connect(self.onAddTaskClicked)
        self.ui.buttonRemoveTask.clicked.connect(self.onRemoveTaskClicked)
        self._addGroupButton("seq", "Sequence")
        self._addGroupButton("conc", "Concurrent")
        self.ui.taskList.customContextMenuRequested.connect(self.onTaskMenu)

        # Setup the task tree
        self.ui.taskList.header().setSectionResizeMode(QHeaderView.Stretch)

        self.ui.taskList.selectionModel().selectionChanged.connect(
            self.onTaskSelectionChanged
        )

        # Create and setup task editor widgets
        for typeId, taskCls in TaskRegistry.registry.items():
            editor = TaskEditorWidget(
                taskCls,
                self._missionContext,
                self.ui.taskEditorStack
            )
            self.taskEditors[typeId] = editor
            self.ui.taskEditorStack.addWidget(editor)

    @pyqtSlot(MissionDocument)
    def onActiveMissionChanged(self, doc: MissionDocument) -> None:
        self._doc = doc
        self.taskListModel.bind(doc)
        self.ui.taskList.expandAll()
        self._model.bind(doc)
        self._mapper.toFirst()
        # Reset task button states
        self.onTaskSelectionChanged(None, None)

    @pyqtSlot()
    def onEditingAboutToFinish(self) -> None:
        # Parameter changes
        self._mapper.submit()

        # Task list (description field) changes
        editor = self.ui.taskList.focusWidget()
        if editor is None or editor is self.ui.taskList:
            # No open editor
            return

        self.ui.taskList.commitData(editor)
        self.ui.taskList.closeEditor(editor, QAbstractItemDelegate.NoHint)

    @pyqtSlot(bool)
    def onEditModeChanged(self, editMode: bool) -> None:
        self.ui.missionPlanDescription.setEnabled(editMode)
        self.ui.missionPlanTimeout.setEnabled(editMode)
        self.ui.taskListSidebar.setEnabled(editMode)

        self.taskListModel.setEditable(editMode)
        self._model.setEditable(editMode)

    @pyqtSlot(QItemSelection, QItemSelection)
    def onTaskSelectionChanged(self, selected: QItemSelection | None,
                               deselected: QItemSelection | None) -> None:
        if self._selecting_family:
            return
        sel = self.ui.taskList.selectionModel()
        rows = sel.selectedRows()
        if len(rows) == 1:
            node = self.taskListModel.node(rows[0])
            if node is not None and not isinstance(node, Task):
                self._select_family(rows[0])
                rows = sel.selectedRows()
        nodes = [self.taskListModel.node(index) for index in rows]
        tasks = [node for node in nodes if isinstance(node, Task)]

        self.ui.buttonRemoveTask.setEnabled(any(node is not self._mission_root() for node in nodes))
        self.ui.buttonMoveTaskUp.setEnabled(False)
        self.ui.buttonMoveTaskDown.setEnabled(False)

        if len(tasks) == 1 and len(nodes) == 1:
            self.activateEditorForTask(tasks[0])
        else:
            self.activateEditorForTask(None)

        self.taskSelectionChanged.emit([task.uuid for task in tasks])

    @pyqtSlot()
    def onAddTaskClicked(self):
        doc = self._document()
        if doc is None:
            # TODO: invalid mapping
            return

        dialog = AddTaskDialog()
        if dialog.exec() != QDialog.Accepted:
            return

        try:
            doc.addTask(dialog.type(), dialog.description(), parent=self._selected_group())
        except UnsupportedTaskCreationError as error:
            QMessageBox.warning(
                self,
                "Unsupported task creation",
                (f"{error}\n\nThis task can currently only be loaded from an existing"
                  " mission file.")
            )

    @pyqtSlot()
    def onRemoveTaskClicked(self):
        doc = self._document()
        if doc is None:
            # TODO: invalid mapping
            return

        rows = self.ui.taskList.selectionModel().selectedRows()
        for index in rows:
            node = self.taskListModel.node(index)
            if isinstance(node, Task):
                doc.deleteTask(node)
            elif isinstance(node, TaskGroup):
                doc.deleteGroup(node)

    def _resetTaskList(self):
        self.taskListModel.beginResetModel()
        self.taskListModel.endResetModel()
        self.onTaskSelectionChanged(None, None)

    @pyqtSlot(UUID, int)
    def onTaskAdded(self, taskUuid: UUID, row: int):
        # TODO: be more smart about updating the task list
        self._resetTaskList()
        self.ui.taskList.expandAll()

    def onTaskDeleted(self, taskUuid: UUID, row: int):
        # TODO: be more smart about updating the task list
        self._resetTaskList()

        # Select the next task, or the last one
        row = min(self.taskListModel.rowCount() - 1, row)
        if row >= 0:
            index = self.taskListModel.index(row, 0)
            self.ui.taskList.setCurrentIndex(index)
            self.ui.taskList.scrollTo(index)

    def _document(self):
        active = self._missionContext.activeDocument()
        if active is not None:
            return active
        return getattr(self, "_doc", None)

    def _mission_root(self):
        doc = self._document()
        return None if doc is None else doc.plan

    def _selected_group(self) -> TaskGroup | None:
        # Family selection highlights the children too. The clicked row stays current.
        node = self.taskListModel.node(self.ui.taskList.currentIndex())
        return node if isinstance(node, TaskGroup) else None

    def _addGroupButton(self, kind: str, label: str) -> None:
        button = QToolButton(self.ui.taskListSidebar)
        button.setText(label)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.clicked.connect(lambda: self.onAddGroup(kind))
        self.ui.verticalLayout_2.addWidget(button)

    def onAddGroup(self, kind: str) -> None:
        doc = self._document()
        if doc is None:
            return
        doc.addGroup(kind, "Sequence" if kind == "seq" else "Concurrent", self._selected_group())

    def _select_family(self, index) -> None:
        self._selecting_family = True
        try:
            selection = self.ui.taskList.selectionModel()
            flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
            def walk(parent) -> None:
                for row in range(self.taskListModel.rowCount(parent)):
                    child = self.taskListModel.index(row, 0, parent)
                    selection.select(child, flags)
                    walk(child)
            walk(index)
        finally:
            self._selecting_family = False

    def onTaskMenu(self, pos) -> None:
        menu = QMenu(self.ui.taskList)
        menu.addAction("Add task", self.onAddTaskClicked)
        menu.addAction("Add sequence", lambda: self.onAddGroup("seq"))
        menu.addAction("Add concurrent", lambda: self.onAddGroup("conc"))
        menu.exec(self.ui.taskList.viewport().mapToGlobal(pos))

    def activateEditorForTask(self, task):
        if task is None:
            editor = self.ui.taskEditorStack.currentWidget()
            if editor is not None and editor is not self.ui.defaultTaskEditorPage:
                editor.unbind()
            self.ui.taskEditorStack.setCurrentWidget(self.ui.defaultTaskEditorPage)
        else:
            editor = self.taskEditors[task.type]
            doc = self._missionContext.activeDocument()
            editor.bind(doc, task.uuid)
            self.ui.taskEditorStack.setCurrentWidget(editor)
