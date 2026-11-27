from qgis.core import QgsApplication

from qgis.PyQt.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from qgis.PyQt.QtWidgets import (
    QAbstractItemDelegate,
    QDataWidgetMapper,
    QDialog,
    QHeaderView,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QToolButton,
    QWidget,
)

from ...domain.missionplan import GroupKind, TaskGroup, walk
from ...domain.tasks import Task, TaskRegistry, UnsupportedTaskCreationError
from ...mission.MissionContext import MissionContext
from ...mission.MissionDocument import MissionDocument
from ...model.MissionParamsModel import MissionParamsModel
from ...model.TaskTreeModel import TaskTreeModel
from ..generated.MissionPlanWidgetUi import Ui_MissionPlanWidget
from .AddTaskDialog import AddTaskDialog
from .TaskEditorWidget import TaskEditorWidget

# Room between the glyphs and the frame. Without it the text sat on the top border.
LINE_EDIT_PADDING_PX = 8
# Below this the tree shows about five rows and stops being the main thing on the panel.
TREE_MIN_HEIGHT_PX = 160
# Share of the splitter the task editor takes when it first appears.
EDITOR_SHARE = 0.4


def _fit_line_edit(edit) -> None:
    edit.ensurePolished()
    frame = edit.style().pixelMetric(QStyle.PM_DefaultFrameWidth, None, edit)
    edit.setMinimumHeight(edit.fontMetrics().height() + frame * 2 + LINE_EDIT_PADDING_PX)


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
        self._editing = False

        self.ui = Ui_MissionPlanWidget()
        self.ui.setupUi(self)

        self.setup()

    def setup(self) -> None:
        self.taskListModel = TaskTreeModel()
        self.ui.taskList.setModel(self.taskListModel)

        self._mapper.addMapping(self.ui.missionPlanDescription, 0)
        self._mapper.addMapping(self.ui.missionPlanTimeout, 1)

        # Respect edit mode
        self._missionContext.editModeChanged.connect(self.onEditModeChanged)
        # Make sure any pending changes are submitted
        self._missionContext.editingAboutToFinish.connect(self.onEditingAboutToFinish)

        # The model resets itself on the document's signals. The view follows the model.
        self.taskListModel.modelReset.connect(self._onTreeReset)
        self.taskListModel.nodeAdded.connect(self._selectIndex)

        # Setup icons for the task buttons
        self.ui.buttonAddTask.setIcon(QgsApplication.getThemeIcon("symbologyAdd.svg"))
        self.ui.buttonRemoveTask.setIcon(
            QgsApplication.getThemeIcon("symbologyRemove.svg")
        )

        # One add control. The menu is the same list as the right-click.
        add_menu = QMenu(self.ui.buttonAddTask)
        self._fill_add_menu(add_menu)
        self.ui.buttonAddTask.setMenu(add_menu)
        self.ui.buttonAddTask.setPopupMode(QToolButton.InstantPopup)
        self.ui.buttonRemoveTask.clicked.connect(self.onRemoveTaskClicked)
        self.ui.taskList.customContextMenuRequested.connect(self.onTaskMenu)
        # The row was shorter than the font, so the glyphs sat on the top border
        # and the timeout looked empty.
        for edit in (self.ui.missionPlanDescription, self.ui.missionPlanTimeout):
            edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            _fit_line_edit(edit)
        # The timeout is a short number. Size it to the font, not to the row.
        timeout = self.ui.missionPlanTimeout
        timeout.setFixedWidth(timeout.fontMetrics().horizontalAdvance("00000.0") + 2 * LINE_EDIT_PADDING_PX)

        # The tree takes the panel. The editor appears only when one task is selected.
        expanding = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ui.taskList.setSizePolicy(expanding)
        self.ui.taskListWidget.setSizePolicy(expanding)
        self.ui.taskList.setMinimumHeight(TREE_MIN_HEIGHT_PX)
        header = self.ui.taskList.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.ui.splitter.setStretchFactor(0, 1)
        self.ui.splitter.setStretchFactor(1, 0)
        self.ui.taskEditorStack.hide()
        # A stack's minimum is its tallest page, shown or not. Size it to the page on screen.
        self.ui.taskEditorStack.currentChanged.connect(self._fitStackToPage)

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
        self._fitStackToPage(self.ui.taskEditorStack.currentIndex())

        # Nothing is editable until a mission is opened for editing.
        self.onEditModeChanged(False)

    @pyqtSlot(MissionDocument)
    def onActiveMissionChanged(self, doc: MissionDocument) -> None:
        self.onEditModeChanged(doc.layerBridge.waypointLayer.isEditable())
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
        self._editing = editMode
        self.ui.missionPlanDescription.setEnabled(editMode)
        self.ui.missionPlanTimeout.setEnabled(editMode)
        # Out of edit mode the add and remove buttons can do nothing, so they are not shown.
        self.ui.taskListSidebar.setEnabled(editMode)
        self.ui.taskListSidebar.setVisible(editMode)
        self.ui.taskList.setToolTip(
            "Right-click to add a task, a sequence, or a concurrent group" if editMode else "")

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

        # Selecting a group selects its children. Deleting the group removes them.
        nodes = [self.taskListModel.node(index)
                 for index in self.ui.taskList.selectionModel().selectedRows()]
        groups = [node for node in nodes if isinstance(node, TaskGroup)]
        inside = {id(child) for group in groups for _, _, child in walk(group.children)}
        for node in nodes:
            if id(node) in inside:
                continue
            if isinstance(node, Task):
                doc.deleteTask(node)
            elif isinstance(node, TaskGroup):
                doc.deleteGroup(node)

    def _onTreeReset(self) -> None:
        self.ui.taskList.expandAll()
        self.onTaskSelectionChanged(None, None)

    def _selectIndex(self, index) -> None:
        if index.isValid():
            self.ui.taskList.setCurrentIndex(index)
            self.ui.taskList.scrollTo(index)

    def _document(self) -> MissionDocument | None:
        return self._missionContext.activeDocument()

    def _mission_root(self):
        doc = self._document()
        return None if doc is None else doc.plan

    def _selected_group(self) -> TaskGroup | None:
        # Family selection highlights the children too. The clicked row stays current.
        node = self.taskListModel.node(self.ui.taskList.currentIndex())
        return node if isinstance(node, TaskGroup) else None

    def _fill_add_menu(self, menu: QMenu) -> None:
        menu.addAction("Task", self.onAddTaskClicked)
        for kind in GroupKind:
            menu.addAction(kind.label, lambda checked=False, kind=kind: self.onAddGroup(kind))

    def onAddGroup(self, kind: GroupKind) -> None:
        doc = self._document()
        if doc is None:
            return
        doc.addGroup(kind, self._selected_group())

    def _select_family(self, index) -> None:
        self._selecting_family = True
        try:
            selection = self.ui.taskList.selectionModel()
            flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
            def select_children(parent) -> None:
                for row in range(self.taskListModel.rowCount(parent)):
                    child = self.taskListModel.index(row, 0, parent)
                    selection.select(child, flags)
                    select_children(child)
            select_children(index)
        finally:
            self._selecting_family = False

    def onTaskMenu(self, pos) -> None:
        if not self._editing:
            return
        menu = QMenu(self.ui.taskList)
        self._fill_add_menu(menu)
        menu.exec(self.ui.taskList.viewport().mapToGlobal(pos))

    def _fitStackToPage(self, current: int) -> None:
        stack = self.ui.taskEditorStack
        for i in range(stack.count()):
            policy = QSizePolicy.Preferred if i == current else QSizePolicy.Ignored
            stack.widget(i).setSizePolicy(policy, policy)
        stack.updateGeometry()

    def activateEditorForTask(self, task: Task | None) -> None:
        if task is None:
            editor = self.ui.taskEditorStack.currentWidget()
            if editor is not None and editor is not self.ui.defaultTaskEditorPage:
                editor.unbind()
            self.ui.taskEditorStack.setCurrentWidget(self.ui.defaultTaskEditorPage)
            self.ui.taskEditorStack.hide()
        else:
            editor = self.taskEditors[task.type]
            doc = self._document()
            if doc is None:
                return
            leaving = self.ui.taskEditorStack.currentWidget()
            # The stack only hides the editor it leaves. Unbinding it stops its map tools,
            # which would otherwise keep editing the task that is no longer shown.
            if leaving is not editor and leaving is not self.ui.defaultTaskEditorPage:
                leaving.unbind()
            editor.bind(doc, task.uuid)
            was_hidden = not self.ui.taskEditorStack.isVisible()
            self.ui.taskEditorStack.setCurrentWidget(editor)
            self.ui.taskEditorStack.show()
            if was_hidden:
                height = max(self.ui.splitter.height(), 1)
                editor_px = int(height * EDITOR_SHARE)
                self.ui.splitter.setSizes([height - editor_px, editor_px])
