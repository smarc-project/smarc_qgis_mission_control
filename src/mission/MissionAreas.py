from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from qgis.core import (
    QgsFeature,
    QgsFeatureRenderer,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsPointXY,
    QgsProject,
    QgsProperty,
    QgsSimpleFillSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)

from qgis.PyQt.QtCore import QObject, QVariant, pyqtSlot
from qgis.PyQt.QtGui import QColor

from ..domain.missionplan import MissionPlan
from ..domain.tasks import Task
from ..domain.taskspatial import iterTaskAreas

if TYPE_CHECKING:
    # Prevent circular dependencies
    from .MissionDocument import MissionDocument

__all__ = ["MissionAreas"]


class MissionAreas(QObject):
    """
    Draws each area field of a task (a geofence, say) as one filled polygon on its own
    layer. The corners themselves stay on the waypoint layer, so they are moved,
    added and deleted like any waypoint; this layer only follows them.
    """
    _doc: MissionDocument
    _layer: QgsVectorLayer
    _activeRenderer: QgsFeatureRenderer
    _inactiveRenderer: QgsFeatureRenderer
    _fields: list[QgsField] = [
        QgsField("task-uuid", QVariant.String),
        QgsField("field-name", QVariant.String),
    ]

    #: The geofence server, and a polygon, need at least three corners
    MIN_CORNERS: int = 3
    #: Out of 255, so the map under the area stays readable
    FILL_ALPHA: int = 60
    COLOR_SELECTED_TASK = QColor("#D81B60")
    COLOR_INACTIVE = QColor("#666666")
    COLOR_ACTIVE = QColor("#7040A0")

    def __init__(self,
                 doc: MissionDocument,
                 layerGroup: QgsLayerTreeGroup,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._doc = doc
        self._setupLayer(layerGroup)
        self.rebuildLayerFromMissionPlan(self._doc.plan)

        # Corners change through the same document signals as route waypoints, undo
        # and redo included, so following them keeps the polygon in step.
        self._doc.waypointAdded.connect(self.onWaypointAdded)
        self._doc.waypointDeleted.connect(self.onWaypointDeleted)
        self._doc.waypointChanged.connect(self.onWaypointChanged)

        self._doc.taskAdded.connect(self.onTaskAdded)
        self._doc.beforeTaskDeleted.connect(self.onBeforeTaskDeleted)

    def layer(self) -> QgsVectorLayer:
        return self._layer

    def _createRenderer(self, fillColor: str, strokeColor: str) -> QgsFeatureRenderer:
        """A see-through fill with a solid edge; the colours are QGIS expressions."""
        symbol = QgsFillSymbol()
        fillLayer = symbol.symbolLayer(0)
        fillLayer.setStrokeWidth(0.6)
        fillLayer.setDataDefinedProperty(
            QgsSimpleFillSymbolLayer.PropertyFillColor,
            QgsProperty.fromExpression(
                f"set_color_part({fillColor}, 'alpha', {self.FILL_ALPHA})"
            )
        )
        fillLayer.setDataDefinedProperty(
            QgsSimpleFillSymbolLayer.PropertyStrokeColor,
            QgsProperty.fromExpression(strokeColor)
        )
        return QgsSingleSymbolRenderer(symbol)

    def _createActiveRenderer(self) -> QgsFeatureRenderer:
        # Same highlight rule as the waypoint layer: the selected task stands out
        color = f'''
            CASE WHEN array_contains(@selected_task_uuids, "task-uuid")
            THEN '{self.COLOR_SELECTED_TASK.name()}'
            ELSE '{self.COLOR_ACTIVE.name()}' END
        '''
        return self._createRenderer(color, color)

    def _createInactiveRenderer(self) -> QgsFeatureRenderer:
        color = f"'{self.COLOR_INACTIVE.name()}'"
        return self._createRenderer(color, color)

    def _setupLayer(self, layerGroup: QgsLayerTreeGroup) -> None:
        self._layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "Areas",
            "memory",
        )
        self._layer.dataProvider().addAttributes(self._fields)
        self._layer.updateFields()

        # Make the layer non-removable (by users)
        flags = self._layer.flags()
        flags &= ~self._layer.LayerFlag.Removable
        self._layer.setFlags(flags)

        self._activeRenderer = self._createActiveRenderer()
        self._inactiveRenderer = self._createInactiveRenderer()
        self.setActive(True)

        # Added after the waypoints and tracks, so it is drawn under them
        QgsProject.instance().addMapLayer(self._layer, False)
        layerGroup.addLayer(self._layer)

    def setActive(self, active: bool = True) -> None:
        self._layer.setOpacity(1.0 if active else 0.4)
        renderer = self._activeRenderer if active else self._inactiveRenderer
        # Need to clone the reusable renderer, since layer takes ownership of it
        self._layer.setRenderer(renderer.clone())
        self._layer.triggerRepaint()

    def rebuildLayerFromMissionPlan(self, plan: MissionPlan) -> None:
        self._layer.dataProvider().truncate()
        features = [
            feat
            for task in plan.leaves()
            for feat in self._createTaskAreaFeatures(task)
        ]
        if features:
            self._layer.dataProvider().addFeatures(features)

    def _createTaskAreaFeatures(self, task: Task) -> list[QgsFeature]:
        features = []
        for spec, corners in iterTaskAreas(task):
            if len(corners) < self.MIN_CORNERS:
                # Fewer corners enclose nothing; the corner markers still show
                continue
            ring = [QgsPointXY(corner.longitude, corner.latitude) for corner in corners]
            # Close the ring explicitly; the last corner joins back to the first
            ring.append(ring[0])

            feat = QgsFeature(self._layer.fields())
            feat.setGeometry(QgsGeometry.fromPolygonXY([ring]))
            feat.setAttribute("task-uuid", str(task.uuid))
            feat.setAttribute("field-name", spec.name)
            features.append(feat)
        return features

    def _deleteTaskAreaFeatures(self, taskUuid: UUID) -> bool:
        fids = [
            feat.id()
            for feat in self._layer.getFeatures(f'"task-uuid" = \'{taskUuid}\'')
        ]
        if fids:
            self._layer.dataProvider().deleteFeatures(fids)
        return bool(fids)

    def redrawTaskAreas(self, taskUuid: UUID) -> None:
        """Replace the task's polygons with ones built from its corners as they are now."""
        task = self._doc.index.taskByUuid(taskUuid)
        if task is None:
            # Groups have no areas of their own
            return

        updated = self._deleteTaskAreaFeatures(taskUuid)
        features = self._createTaskAreaFeatures(task)
        if features:
            self._layer.dataProvider().addFeatures(features)
            updated = True

        if updated:
            self._layer.updateExtents()
            self._layer.triggerRepaint()

    @pyqtSlot(UUID, str, UUID)
    def onWaypointAdded(self,
                        taskUuid: UUID,
                        fieldName: str,
                        waypointUuid: UUID) -> None:
        self.redrawTaskAreas(taskUuid)

    @pyqtSlot(UUID, str, UUID, int)
    def onWaypointDeleted(self,
                          taskUuid: UUID,
                          fieldName: str,
                          waypointUuid: UUID,
                          index: int) -> None:
        self.redrawTaskAreas(taskUuid)

    @pyqtSlot(UUID)
    def onWaypointChanged(self, waypointUuid: UUID) -> None:
        taskUuid = self._doc.index.taskUuidByWaypointUuid(waypointUuid)
        if taskUuid is not None:
            self.redrawTaskAreas(taskUuid)

    @pyqtSlot(UUID, int)
    def onTaskAdded(self, taskUuid: UUID, row: int) -> None:
        self.redrawTaskAreas(taskUuid)

    @pyqtSlot(UUID)
    def onBeforeTaskDeleted(self, taskUuid: UUID) -> None:
        if self._deleteTaskAreaFeatures(taskUuid):
            self._layer.updateExtents()
            self._layer.triggerRepaint()
