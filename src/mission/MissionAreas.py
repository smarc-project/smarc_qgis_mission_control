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
    QgsLinePatternFillSymbolLayer,
    QgsPointXY,
    QgsProject,
    QgsProperty,
    QgsRuleBasedRenderer,
    QgsSimpleFillSymbolLayer,
    QgsVectorLayer,
)

from qgis.PyQt.QtCore import QObject, Qt, QVariant, pyqtSlot
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
    layer: QgsVectorLayer
    _activeRenderer: QgsFeatureRenderer
    _inactiveRenderer: QgsFeatureRenderer
    _fields: list[QgsField] = [
        QgsField("task-uuid", QVariant.String),
        QgsField("field-name", QVariant.String),
        QgsField("no-go", QVariant.Bool),
    ]

    #: The geofence server, and a polygon, need at least three corners
    MIN_CORNERS: int = 3
    #: Out of 255, so the map under the area stays readable
    FILL_ALPHA: int = 60
    #: Millimetres on screen
    EDGE_WIDTH: float = 0.6
    SELECTED_EDGE_WIDTH: float = 1.4
    HATCH_SPACING: float = 3.0
    HATCH_WIDTH: float = 0.3
    COLOR_INACTIVE = QColor("#666666")
    COLOR_ACTIVE = QColor("#7040A0")
    COLOR_NO_GO = QColor("#D32F2F")

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
        # A task field such as StayInside can turn a fence into a no-go zone
        self._doc.taskChanged.connect(self.redrawTaskAreas)

    def _createSymbol(self, color: QColor, selectable: bool) -> QgsFillSymbol:
        """A see-through fill with a solid edge, in the task's normal colour."""
        symbol = QgsFillSymbol()
        fillLayer = symbol.symbolLayer(0)
        fill = QColor(color)
        fill.setAlpha(self.FILL_ALPHA)
        fillLayer.setFillColor(fill)
        fillLayer.setStrokeColor(color)
        fillLayer.setStrokeWidth(self.EDGE_WIDTH)
        if selectable:
            # The selected task's edge is thicker; its colour keeps meaning the kind
            fillLayer.setDataDefinedProperty(
                QgsSimpleFillSymbolLayer.PropertyStrokeWidth,
                QgsProperty.fromExpression(f'''
                    CASE WHEN array_contains(@selected_task_uuids, "task-uuid")
                    THEN {self.SELECTED_EDGE_WIDTH}
                    ELSE {self.EDGE_WIDTH} END
                ''')
            )
        return symbol

    def _createNoGoSymbol(self, color: QColor, selectable: bool) -> QgsFillSymbol:
        """The keep-in look with a dashed edge and diagonal lines: you can't be here."""
        symbol = self._createSymbol(color, selectable)
        symbol.symbolLayer(0).setStrokeStyle(Qt.DashLine)
        hatch = QgsLinePatternFillSymbolLayer()
        hatch.setLineAngle(45)
        hatch.setDistance(self.HATCH_SPACING)
        hatch.setColor(color)
        hatch.setLineWidth(self.HATCH_WIDTH)
        symbol.appendSymbolLayer(hatch)
        return symbol

    def _createRenderer(self,
                        keepInColor: QColor,
                        noGoColor: QColor,
                        selectable: bool) -> QgsFeatureRenderer:
        root = QgsRuleBasedRenderer.Rule(None)
        root.appendChild(QgsRuleBasedRenderer.Rule(
            self._createSymbol(keepInColor, selectable),
            filterExp='NOT "no-go"',
            label="Area",
        ))
        root.appendChild(QgsRuleBasedRenderer.Rule(
            self._createNoGoSymbol(noGoColor, selectable),
            filterExp='"no-go"',
            label="No-go zone",
        ))
        return QgsRuleBasedRenderer(root)

    def _createActiveRenderer(self) -> QgsFeatureRenderer:
        return self._createRenderer(self.COLOR_ACTIVE, self.COLOR_NO_GO, True)

    def _createInactiveRenderer(self) -> QgsFeatureRenderer:
        # Grey like the other inactive layers; the hatch still tells the kinds apart
        return self._createRenderer(self.COLOR_INACTIVE, self.COLOR_INACTIVE, False)

    def _setupLayer(self, layerGroup: QgsLayerTreeGroup) -> None:
        self.layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326",
            "Areas",
            "memory",
        )
        self.layer.dataProvider().addAttributes(self._fields)
        self.layer.updateFields()

        # Make the layer non-removable (by users)
        flags = self.layer.flags()
        flags &= ~self.layer.LayerFlag.Removable
        self.layer.setFlags(flags)

        self._activeRenderer = self._createActiveRenderer()
        self._inactiveRenderer = self._createInactiveRenderer()
        self.setActive(True)

        # Added after the waypoints and tracks, so it is drawn under them
        QgsProject.instance().addMapLayer(self.layer, False)
        layerGroup.addLayer(self.layer)

    def setActive(self, active: bool = True) -> None:
        self.layer.setOpacity(1.0 if active else 0.4)
        renderer = self._activeRenderer if active else self._inactiveRenderer
        # Need to clone the reusable renderer, since layer takes ownership of it
        self.layer.setRenderer(renderer.clone())
        self.layer.triggerRepaint()

    def rebuildLayerFromMissionPlan(self, plan: MissionPlan) -> None:
        self.layer.dataProvider().truncate()
        features = [
            feat
            for task in plan.leaves()
            for feat in self._createTaskAreaFeatures(task)
        ]
        if features:
            self.layer.dataProvider().addFeatures(features)

    def _createTaskAreaFeatures(self, task: Task) -> list[QgsFeature]:
        features = []
        for spec, corners in iterTaskAreas(task):
            if len(corners) < self.MIN_CORNERS:
                # Fewer corners enclose nothing; the corner markers still show
                continue
            ring = [QgsPointXY(corner.longitude, corner.latitude) for corner in corners]
            # Close the ring explicitly; the last corner joins back to the first
            ring.append(ring[0])

            feat = QgsFeature(self.layer.fields())
            feat.setGeometry(QgsGeometry.fromPolygonXY([ring]))
            feat.setAttribute("task-uuid", str(task.uuid))
            feat.setAttribute("field-name", spec.name)
            feat.setAttribute("no-go", task.isNoGoArea())
            features.append(feat)
        return features

    def _deleteTaskAreaFeatures(self, taskUuid: UUID) -> bool:
        fids = [
            feat.id()
            for feat in self.layer.getFeatures(f'"task-uuid" = \'{taskUuid}\'')
        ]
        if fids:
            self.layer.dataProvider().deleteFeatures(fids)
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
            self.layer.dataProvider().addFeatures(features)
            updated = True

        if updated:
            self.layer.updateExtents()
            self.layer.triggerRepaint()

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
            self.layer.updateExtents()
            self.layer.triggerRepaint()
