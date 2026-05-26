from typing import Type
from enum import Enum

from qgis.PyQt.QtCore import Qt, pyqtSlot, pyqtSignal
from qgis.PyQt.QtGui import QIntValidator, QDoubleValidator
from qgis.PyQt.QtWidgets import QWidget, QFormLayout, QLabel, QComboBox, QLineEdit, QDataWidgetMapper, QCheckBox

from ...domain.schema import Schema

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
            return widget
        elif t is str:
            widget = QLineEdit(parent)
            return widget
        elif t is bool:
            widget = QCheckBox(parent)
            return widget
        else:
            raise NotImplementedError
