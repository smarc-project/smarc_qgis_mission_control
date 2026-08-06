from qgis.PyQt.QtWidgets import QDialog, QWidget

from ...domain.tasks import TaskRegistry
from ..generated.AddTaskDialogUi import Ui_AddTaskDialog

__all__ = ["AddTaskDialog"]


class AddTaskDialog(QDialog, Ui_AddTaskDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setupUi(self)

        # Populate task type list
        for typeId in TaskRegistry.registry.keys():
            self.taskType.addItem(typeId)

        # Disable resizing, ensuring size provided in QtDesigner
        self.setFixedSize(self.size())

    def description(self) -> str:
        return self.taskDescription.text().strip()

    def type(self) -> str:
        return self.taskType.currentText()
