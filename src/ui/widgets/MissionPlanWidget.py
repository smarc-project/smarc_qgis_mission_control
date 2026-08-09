from uuid import UUID

from qgis.core import QgsApplication

from qgis.PyQt.QtCore import QItemSelection, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import (
    QAbstractItemDelegate,
    QDataWidgetMapper,
    QDialog,
    QHeaderView,
    QMessageBox,
    QWidget,
)

from ...domain.tasks import TaskRegistry, UnsupportedTaskCreationError
from ...mission.MissionContext import MissionContext
from ...mission.MissionDocument import MissionDocument
from ...model.MissionParamsModel import MissionParamsModel
from ...model.TaskListModel import TaskListModel
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

        self.ui = Ui_MissionPlanWidget()
        self.ui.setupUi(self)

        self.setup()

    def setup(self) -> None:
        self.taskListModel = TaskListModel()
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

        # Setup the task table
        self.ui.taskList.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ui.taskList.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.ui.taskList.verticalHeader().setDefaultAlignment(Qt.AlignRight)

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
        self.taskListModel.bind(doc)
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
        sel = self.ui.taskList.selectionModel()
        rows = sel.selectedRows()

        # Enable/disable task list buttons as needed
        self.ui.buttonRemoveTask.setEnabled(bool(rows))
        self.ui.buttonMoveTaskUp.setEnabled(bool(rows) and rows[0].row() > 0)
        self.ui.buttonMoveTaskDown.setEnabled(bool(rows) \
            and rows[-1].row() < len(self.taskListModel.items()) - 1)

        if len(rows) > 1:
            self.activateEditorForTask(None)
        elif len(rows) == 0:
            self.activateEditorForTask(None)
        else:
            task = self.taskListModel.item(rows[0].row())
            self.activateEditorForTask(task)

        taskUuids = [self.taskListModel.item(row.row()).uuid for row in rows]
        self.taskSelectionChanged.emit(taskUuids)

    @pyqtSlot()
    def onAddTaskClicked(self):
        doc = self._missionContext.activeDocument()
        if doc is None:
            # TODO: invalid mapping
            return

        dialog = AddTaskDialog()
        if dialog.exec() != QDialog.Accepted:
            return

        try:
            doc.addTask(dialog.type(), dialog.description())
        except UnsupportedTaskCreationError as error:
            QMessageBox.warning(
                self,
                "Unsupported task creation",
                (f"{error}\n\nThis task can currently only be loaded from an existing"
                  " mission file.")
            )

    @pyqtSlot()
    def onRemoveTaskClicked(self):
        doc = self._missionContext.activeDocument()
        if doc is None:
            # TODO: invalid mapping
            return

        rows = self.ui.taskList.selectionModel().selectedRows()
        for row in rows:
            index = rows[0].row()
            doc.deleteTaskAt(index)

    def _resetTaskList(self):
        self.taskListModel.beginResetModel()
        self.taskListModel.endResetModel()
        self.onTaskSelectionChanged(None, None)

    @pyqtSlot(UUID, int)
    def onTaskAdded(self, taskUuid: UUID, row: int):
        # TODO: be more smart about updating the task list
        self._resetTaskList()

        # Select the newly added task
        index = self.taskListModel.index(row, 0)
        self.ui.taskList.setCurrentIndex(index)
        self.ui.taskList.scrollTo(index)

    def onTaskDeleted(self, taskUuid: UUID, row: int):
        # TODO: be more smart about updating the task list
        self._resetTaskList()

        # Select the next task, or the last one
        row = min(self.taskListModel.rowCount() - 1, row)
        if row >= 0:
            index = self.taskListModel.index(row, 0)
            self.ui.taskList.setCurrentIndex(index)
            self.ui.taskList.scrollTo(index)

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
