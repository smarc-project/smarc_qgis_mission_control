from qgis.PyQt.QtCore import QModelIndex, Qt, QVariant, pyqtSlot
from qgis.PyQt.QtWidgets import QWidget

from ..domain.missionplan import MissionPlan
from ..mission.MissionDocument import MissionDocument
from .SchemaBasedModel import SchemaBasedModel

__all__ = ["MissionParamsModel"]

class MissionParamsModel(SchemaBasedModel):
    _items: list[MissionPlan]
    _doc: MissionDocument | None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(MissionPlan.schema(), True, parent)
        self._doc = None

    def bind(self, doc: MissionDocument):
        self.unbind()

        self._doc = doc
        self._doc.missionChanged.connect(self.onMissionChanged)
        self.setItems([self._doc.plan])

    def unbind(self):
        if self._doc is not None:
            self._doc.missionChanged.disconnect(self.onMissionChanged)

        self._doc = None
        self.setItems([])

    def setData(self, index: QModelIndex, value: QVariant,
                role: int = Qt.EditRole) -> bool:
        if role != Qt.EditRole or not self.isEditable():
            return False

        col = index.column()

        # retrieve the field specification for schema object
        spec = self._schema.fields[col]
        # retrieve original value (->type)
        original = spec.value(self._doc.plan)

        # cast the incoming object to the original type
        # TODO: move conversion to MissionDocument.setMissionField?
        try:
            typed_value = spec.type()(value) # instead of type(original)(value)
        
        except (ValueError, TypeError):
            return False  # reject invalid input

        self._doc.setMissionField(col, typed_value)

        return True

    @pyqtSlot()
    def onMissionChanged(self):
        if self._doc is None:
            return

        idxStart = self.index(0, 0)
        idxEnd = self.index(0, len(self._schema.fields) - 1)
        self.dataChanged.emit(idxStart, idxEnd, [Qt.DisplayRole, Qt.EditRole])
