from enum import Enum
from typing import Type

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QDoubleValidator, QIntValidator
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDataWidgetMapper,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

__all__ = ["AutomaticFormWidget"]

class AutomaticFormWidget(QWidget):
    def __init__(self, model, parent: QWidget|None = None):
        super().__init__(parent)
        # TODO: model in two places on same object (_mapper)
        self._model = model

        self._mapper = QDataWidgetMapper()
        self._mapper.setModel(model)
        self._mapper.setSubmitPolicy(QDataWidgetMapper.AutoSubmit)

        self._formLayout: QFormLayout|None = None

    def buildForm(self, form: QWidget):
        # Should never rebuild
        assert(self._formLayout is None)

        self._formLayout = QFormLayout(form)
        self._formLayout.setContentsMargins(0, 0, 0, 0)
        self._formLayout.setLabelAlignment(
            Qt.AlignRight|Qt.AlignTrailing|Qt.AlignVCenter)

        for col, spec in enumerate(self._model.schema().fields):
            label = QLabel(form)
            label.setText(spec.header(preferLong = True) + ":")
            self._formLayout.setWidget(col, QFormLayout.LabelRole, label)

            field = self.createEditorWidget(form, spec.type())
            self._formLayout.setWidget(col, QFormLayout.FieldRole, field)

            if issubclass(spec.type(), Enum):
                self._mapper.addMapping(field, col, b"currentText")
                # field.editTextChanged.connect(self._mapper.submit) # connects on field change (not suitable for manual keyboard input)
                field.lineEdit().editingFinished.connect(self._mapper.submit) # connects on fiel change (enter/focus out)
            else:
                self._mapper.addMapping(field, col)

        self._mapper.toFirst()

    def createEditorWidget(self, parent: QWidget, t: Type):
        widget: QWidget
        if t is int:
            widget = QLineEdit(parent)
            widget.setValidator(QIntValidator())
            return widget
        elif t is float:
            widget = QLineEdit(parent)
            widget.setValidator(QDoubleValidator(widget))
            return widget
        elif issubclass(t, Enum):
            widget = QComboBox(parent)
            for option in t:
                widget.addItem(str(option))
            widget.setEditable(True)
            return widget
        elif t is str:
            widget = QLineEdit(parent)
            return widget
        elif t is bool:
            widget = QCheckBox(parent)
            return widget
        else:
            raise NotImplementedError

    def _setFieldWidgetEditMode(self, fieldWidget: QWidget, editMode: bool):
        # Subclasses can overwrite it to be fancier with how they en/disable widgets
        fieldWidget.setEnabled(editMode)

    def setEditMode(self, editMode: bool):
        self._model.setEditable(editMode)

        for i in range(self._formLayout.rowCount()):
            item = self._formLayout.itemAt(i, QFormLayout.FieldRole)
            if item is None:
                # Just a label on this row
                continue

            self._setFieldWidgetEditMode(item.widget(), editMode)
