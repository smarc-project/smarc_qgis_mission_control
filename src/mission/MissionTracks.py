from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFeatureRenderer,
    QgsField,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsLineString,
    QgsMarkerLineSymbolLayer,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsProperty,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsTextBackgroundSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from qgis.PyQt.QtCore import QObject, QSizeF, Qt, QVariant, pyqtSlot
from qgis.PyQt.QtGui import QColor

from ..domain.missionplan import MissionPlan
from ..domain.taskspatial import iterTaskWaypoints
from ..domain.waypoints import Waypoint

if TYPE_CHECKING:
    # Prevent circular dependencies
    from .MissionDocument import MissionDocument

__all__ = ["MissionTracks"]


class MissionTracks(QObject):
    _doc: MissionDocument
    _layer: QgsVectorLayer
    _activeRenderer: QgsFeatureRenderer
    _inactiveRenderer: QgsFeatureRenderer
    _fields: list[QgsField] = [
        QgsField("from-waypoint-uuid", QVariant.String),
        QgsField("to-waypoint-uuid", QVariant.String),
        QgsField("same-task", QVariant.Bool),
    ]

    LABEL_BACKGROUND_OPACITY: float = 0.7
    COLOR_SELECTED_TASK = QColor("#D81B60")
    COLOR_INACTIVE = QColor("#666666")
    COLOR_ACTIVE = QColor("#7040A0")

    def __init__(self, doc: MissionDocument, layerGroup: QgsLayerTreeGroup,
                 parent: QObject | None = None):
        super().__init__(parent)

        self._doc = doc
        self._setupLayer(layerGroup)
        self.rebuildLayerFromMissionPlan(self._doc.plan)

        self._doc.waypointAdded.connect(self.onWaypointAdded)
        self._doc.beforeWaypointDeleted.connect(self.onBeforeWaypointDeleted)
        self._doc.waypointChanged.connect(self.onWaypointChanged)

        self._doc.taskAdded.connect(self.onTaskAdded)
        self._doc.beforeTaskDeleted.connect(self.onBeforeTaskDeleted)

    def _createActiveRenderer(self) -> QgsFeatureRenderer:
        # Setup symbology for the layer
        symbol = QgsSymbol.defaultSymbol(self._layer.geometryType())

        # Default line symbol layer
        lineSymbolLayer = symbol.symbolLayer(0)
        # Same-task connections -> solid lines, otherwise dashed
        lineSymbolLayer.setColor(self.COLOR_ACTIVE)
        lineSymbolLayer.setDataDefinedProperty(
            QgsSimpleLineSymbolLayer.PropertyStrokeStyle,
            QgsProperty.fromExpression(
                "CASE WHEN \"same-task\" THEN 'solid' ELSE 'dash' END"
            )
        )
        lineSymbolLayer.setDataDefinedProperty(
            QgsSimpleMarkerSymbolLayer.PropertyStrokeColor,
            QgsProperty.fromExpression(f'''
                CASE WHEN
                    array_contains(@selected_task_waypoint_uuids, "from-waypoint-uuid")
                    AND array_contains(@selected_task_waypoint_uuids, "to-waypoint-uuid")
                THEN '{self.COLOR_SELECTED_TASK.name()}'
                ELSE '{lineSymbolLayer.color().name()}'
                END
            ''')
        )
        lineSymbolLayer.setDataDefinedProperty(
            QgsSimpleMarkerSymbolLayer.PropertyStrokeWidth,
            QgsProperty.fromExpression(
                '''
                CASE WHEN
                    array_contains(@selected_task_waypoint_uuids, "from-waypoint-uuid")
                    AND array_contains(@selected_task_waypoint_uuids, "to-waypoint-uuid")
                THEN 1
                ELSE 0.45
                END'''
            )
        )

        # Arrow marker
        markerLineSymbolLayer = QgsMarkerLineSymbolLayer()
        markerLineSymbolLayer.setPlacements(Qgis.MarkerLinePlacement.SegmentCenter)
        markerLineSymbolLayer.setRotateSymbols(True)

        arrowSymbol = markerLineSymbolLayer.subSymbol()
        arrowMarkerLayer = arrowSymbol.symbolLayer(0)

        # No outline
        arrowMarkerLayer.setStrokeStyle(Qt.NoPen)
        arrowMarkerLayer.setColor(self.COLOR_ACTIVE)
        # Set the shape
        arrowMarkerLayer.setShape(Qgis.MarkerShape.ArrowHeadFilled)
        arrowMarkerLayer.setDataDefinedProperty(
            QgsSimpleMarkerSymbolLayer.PropertySize,
            QgsProperty.fromExpression('''
                CASE WHEN
                    array_contains(@selected_task_waypoint_uuids, "from-waypoint-uuid")
                    AND array_contains(@selected_task_waypoint_uuids, "to-waypoint-uuid")
                THEN 5
                ELSE 3 END
            ''')
        )
        arrowMarkerLayer.setDataDefinedProperty(
            QgsSimpleMarkerSymbolLayer.PropertyFillColor,
            QgsProperty.fromExpression(f'''
                CASE WHEN
                    array_contains(@selected_task_waypoint_uuids, "from-waypoint-uuid")
                    AND array_contains(@selected_task_waypoint_uuids, "to-waypoint-uuid")
                THEN '{self.COLOR_SELECTED_TASK.name()}'
                ELSE '{arrowMarkerLayer.color().name()}'
                END
            ''')
        )

        symbol.appendSymbolLayer(markerLineSymbolLayer)

        return QgsSingleSymbolRenderer(symbol)

    def _createInactiveRenderer(self) -> QgsFeatureRenderer:
        # Setup symbology for the layer
        symbol = QgsSymbol.defaultSymbol(self._layer.geometryType())

        # Default line symbol layer
        lineSymbolLayer = symbol.symbolLayer(0)
        lineSymbolLayer.setColor(self.COLOR_INACTIVE)
        lineSymbolLayer.setWidth(0.45)
        # Same-task connections -> solid lines, otherwise dashed
        lineSymbolLayer.setDataDefinedProperty(
            QgsSimpleLineSymbolLayer.PropertyStrokeStyle,
            QgsProperty.fromExpression(
                "CASE WHEN \"same-task\" THEN 'solid' ELSE 'dash' END"
            )
        )

        # Arrow marker
        markerLineSymbolLayer = QgsMarkerLineSymbolLayer()
        markerLineSymbolLayer.setPlacements(Qgis.MarkerLinePlacement.SegmentCenter)
        markerLineSymbolLayer.setRotateSymbols(True)

        arrowSymbol = markerLineSymbolLayer.subSymbol()
        arrowMarkerLayer = arrowSymbol.symbolLayer(0)

        # No outline
        arrowMarkerLayer.setStrokeStyle(Qt.NoPen)

        arrowMarkerLayer.setColor(self.COLOR_INACTIVE)
        arrowMarkerLayer.setShape(Qgis.MarkerShape.ArrowHeadFilled)
        arrowMarkerLayer.setSize(3.0)

        symbol.appendSymbolLayer(markerLineSymbolLayer)

        return QgsSingleSymbolRenderer(symbol)

    def _setupLayer(self, layerGroup: QgsLayerTreeGroup) -> None:
        self._layer = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            "Tracks",
            "memory",
        )
        self._layer.dataProvider().addAttributes(self._fields)
        self._layer.updateFields()

        # Make the layer non-removable (by users)
        flags = self._layer.flags()
        flags &= ~self._layer.LayerFlag.Removable
        self._layer.setFlags(flags)

        # Create renderers for both states
        self._activeRenderer = self._createActiveRenderer()
        self._inactiveRenderer = self._createInactiveRenderer()

        # Set label background
        bg = QgsTextBackgroundSettings()
        bg.setEnabled(True)
        bg.setFillColor(QColor("white"))
        bg.setOpacity(self.LABEL_BACKGROUND_OPACITY)
        current_bg_size = bg.size()
        bg.setSize(QSizeF(current_bg_size.width() + 0.5, current_bg_size.height()))
        
        # Distance labels
        fmt = QgsTextFormat()
        fmt.setSize(11)
        fmt.setBackground(bg) # Apply background to format

        settings = QgsVectorLayerSimpleLabeling.defaultSettingsForLayer(self._layer)
        settings.fieldName = "format_number($length, 1) || ' m'"
        settings.isExpression = True
        settings.setFormat(fmt)

        settings.placement = Qgis.LabelPlacement.Line
        settings.placementFlags = Qgis.LabelLinePlacementFlag.AboveLine
        settings.distUnits = Qgis.RenderUnit.Millimeters
        settings.dist = 2.0

        settings.addDirectionSymbol = True
        settings.leftDirectionSymbol = chr(57983)
        settings.rightDirectionSymbol = chr(57982)
        settings.placeDirectionSymbol = QgsPalLayerSettings.SymbolLeftRight
        settings.reverseDirectionSymbol = False

        labeling = QgsVectorLayerSimpleLabeling(settings)
        self._layer.setLabeling(labeling)

        # Make the layer use the proper renderer and labeling
        self.setActive(True)

        # Register the layer with QGIS and add it to the group
        QgsProject.instance().addMapLayer(self._layer, False)
        layerGroup.addLayer(self._layer)

    def setActive(self, active: bool = True) -> None:
        opacity = 1.0 if active else 0.4
        # Layer itself
        self._layer.setOpacity(opacity)

        # Labeling
        self._layer.setLabelsEnabled(active)

        # Renderer
        renderer = self._activeRenderer if active else self._inactiveRenderer
        # Need to clone the reusable renderer, since layer takes ownership of it
        self._layer.setRenderer(renderer.clone())
        self._layer.triggerRepaint()

    def rebuildLayerFromMissionPlan(self, plan: MissionPlan) -> None:
        # Drop all existing features
        self._layer.dataProvider().truncate()

        data = []
        # Discover all the waypoints and their tasks
        for task in plan.tasks:
            for waypoint in iterTaskWaypoints(task):
                data.append((waypoint, task.uuid))

        # Build initial features
        features = []
        for i in range(len(data) - 1):
            waypointFrom, taskFromUuid = data[i]
            waypointTo, taskToUuid = data[i + 1]
            sameTask = taskFromUuid == taskToUuid

            feat = self.createLineFeature(waypointFrom, waypointTo, sameTask)
            features.append(feat)

        if features:
            self._layer.dataProvider().addFeatures(features)

    def createLineFeature(self, fromWaypoint: Waypoint, toWaypoint: Waypoint,
                          sameTask: bool) -> QgsFeature:
        fromPoint = QgsPointXY(fromWaypoint.longitude, fromWaypoint.latitude)
        toPoint = QgsPointXY(toWaypoint.longitude, toWaypoint.latitude)
        geom = QgsGeometry(QgsLineString([fromPoint, toPoint]))

        feat = QgsFeature(self._layer.fields())
        feat.setGeometry(geom)

        attrs = {
            "same-task": sameTask,
            "from-waypoint-uuid": str(fromWaypoint.uuid),
            "to-waypoint-uuid": str(toWaypoint.uuid),
        }
        for key, value in attrs.items():
            feat.setAttribute(key, value)

        return feat

    def lineFeaturesForWaypointUuid(self, waypointUuid: UUID) \
                                    -> tuple[QgsFeature | None, QgsFeature | None]:
        featuresTo = self._layer.getFeatures(
            f'"to-waypoint-uuid" = \'{waypointUuid}\''
        )
        featuresFrom = self._layer.getFeatures(
            f'"from-waypoint-uuid" = \'{waypointUuid}\''
        )

        # TODO: check if >1 features for any UUID?
        featTo = next(iter(featuresTo), None)
        featFrom = next(iter(featuresFrom), None)

        return featTo, featFrom

    @pyqtSlot(UUID, str, UUID)
    def onWaypointAdded(self, taskUuid: UUID, fieldName: str,
                        waypointUuid: UUID) -> None:
        waypoint = self._doc.index.waypointByUuid(waypointUuid)
        if waypoint is None:
            # TODO: invalid mapping
            return

        # Find the surrounding waypoints
        prevWaypoint = self._doc.index.previousWaypointByUuid(waypointUuid)
        nextWaypoint = self._doc.index.nextWaypointByUuid(waypointUuid)

        if not any((prevWaypoint, nextWaypoint)):
            # TODO: invalid mapping
            return

        updated = False
        # Get rid of the existing segment between the surrounding waypoints
        segment: QgsFeature | None
        if prevWaypoint is not None:
            _, segment = self.lineFeaturesForWaypointUuid(prevWaypoint.uuid)
        else:
            segment, _ = self.lineFeaturesForWaypointUuid(nextWaypoint.uuid)

        if segment is not None:
            self._layer.dataProvider().deleteFeatures([segment.id()])
            updated = True

        # Create the new segment(s)
        features = []
        if prevWaypoint is not None:
            prevTaskUuid = self._doc.index.taskUuidByWaypointUuid(prevWaypoint.uuid)
            sameTask = prevTaskUuid == taskUuid
            feat = self.createLineFeature(prevWaypoint, waypoint, sameTask)
            features.append(feat)

        if nextWaypoint is not None:
            nextTaskUuid = self._doc.index.taskUuidByWaypointUuid(nextWaypoint.uuid)
            sameTask = taskUuid == nextTaskUuid

            feat = self.createLineFeature(waypoint, nextWaypoint, sameTask)
            features.append(feat)

        if features:
            self._layer.dataProvider().addFeatures(features)
            updated = True

        # Repaint the layer so changes are visible right away
        if updated:
            self._layer.updateExtents()
            self._layer.triggerRepaint()

    @pyqtSlot(UUID, str, UUID, int)
    def onBeforeWaypointDeleted(self, taskUuid: UUID, fieldName: str,
                                waypointUuid: UUID, index: int) -> None:
        waypoint = self._doc.index.waypointByUuid(waypointUuid)
        if waypoint is None:
            # TODO: invalid mapping
            return

        # Find the surrounding waypoints
        prevWaypoint = self._doc.index.previousWaypointByUuid(waypointUuid)
        nextWaypoint = self._doc.index.nextWaypointByUuid(waypointUuid)

        if not any((prevWaypoint, nextWaypoint)):
            # TODO: invalid mapping
            return

        updated = False
        # Get rid of the existing segments between the surrounding waypoints and this
        # waypoint
        featTo, featFrom = self.lineFeaturesForWaypointUuid(waypointUuid)
        fidsToDelete = [feat.id() for feat in (featTo, featFrom) if feat]
        if fidsToDelete:
            self._layer.dataProvider().deleteFeatures(fidsToDelete)
            updated = True

        # Create the new segment, if needed
        if all((prevWaypoint, nextWaypoint)):
            prevTaskUuid = self._doc.index.taskUuidByWaypointUuid(prevWaypoint.uuid)
            nextTaskUuid = self._doc.index.taskUuidByWaypointUuid(nextWaypoint.uuid)
            sameTask = prevTaskUuid == nextTaskUuid

            feat = self.createLineFeature(prevWaypoint, nextWaypoint, sameTask)
            self._layer.dataProvider().addFeature(feat)
            updated = True

        # Repaint the layer so changes are visible right away
        if updated:
            self._layer.updateExtents()
            self._layer.triggerRepaint()

    @pyqtSlot(UUID)
    def onWaypointChanged(self, waypointUuid: UUID) -> None:
        # TODO: this gets called for parameter changes too, not only movement updates
        waypoint = self._doc.index.waypointByUuid(waypointUuid)
        if waypoint is None:
            # TODO: invalid mapping
            return

        # Reuse existing segments, and update their termination points
        featTo, featFrom = self.lineFeaturesForWaypointUuid(waypointUuid)

        changes: dict[int, QgsGeometry] = {}
        if featTo is not None:
            geom = featTo.geometry()
            geom.moveVertex(waypoint.longitude, waypoint.latitude, 1)
            changes[featTo.id()] = geom

        if featFrom is not None:
            geom = featFrom.geometry()
            geom.moveVertex(waypoint.longitude, waypoint.latitude, 0)
            changes[featFrom.id()] = geom

        if changes:
            self._layer.dataProvider().changeGeometryValues(changes)
            self._layer.updateExtents()
            self._layer.triggerRepaint()

    @pyqtSlot(UUID, int)
    def onTaskAdded(self, taskUuid: UUID, row: int):
        task = self._doc.index.taskByUuid(taskUuid)
        if task is None:
            # TODO: invalid mapping
            return

        waypoints = list(iterTaskWaypoints(task))
        if len(waypoints) == 0:
            # No waypoints on this task
            return

        prevTaskWaypoint = self._doc.index.previousWaypointByUuid(waypoints[0].uuid)
        nextTaskWaypoint = self._doc.index.nextWaypointByUuid(waypoints[-1].uuid)

        # If both previous and next task waypoints exist, there must currently be a
        # single segment between them. We need to get rid of it.
        segment: QgsFeature | None = None
        if prevTaskWaypoint is not None:
            _, segment = self.lineFeaturesForWaypointUuid(prevTaskWaypoint.uuid)
        elif nextTaskWaypoint is not None:
            segment, _ = self.lineFeaturesForWaypointUuid(nextTaskWaypoint.uuid)

        updated = False
        if segment is not None:
            self._layer.dataProvider().deleteFeatures([segment.id()])
            updated = True

        # Collect all the segments
        features: list[QgsFeature] = []

        # Add a segment from the previous task to this one, if needed
        if prevTaskWaypoint is not None:
            feat = self.createLineFeature(prevTaskWaypoint, waypoints[0], False)
            features.append(feat)

        # Build segments inside the task
        thisWaypoint = waypoints[0]
        finalWaypoint = waypoints[-1]
        while thisWaypoint.uuid != finalWaypoint.uuid:
            nextWaypoint = self._doc.index.nextWaypointByUuid(thisWaypoint.uuid)

            # All segments here are part of the same task, by definition
            feat = self.createLineFeature(thisWaypoint, nextWaypoint, True)
            features.append(feat)

            thisWaypoint = nextWaypoint

        # Add a segment from this task to the next one, if needed
        if nextTaskWaypoint is not None:
            feat = self.createLineFeature(waypoints[-1], nextTaskWaypoint, False)
            features.append(feat)

        # No features is possible if this is the first task in the mission plan, and it
        # only has a single waypoint
        if features:
            self._layer.dataProvider().addFeatures(features)
            updated = True

        if updated:
            self._layer.updateExtents()
            self._layer.triggerRepaint()

    @pyqtSlot(UUID)
    def onBeforeTaskDeleted(self, taskUuid: UUID) -> None:
        task = self._doc.index.taskByUuid(taskUuid)
        if task is None:
            # TODO: invalid mapping
            return

        waypoints = list(iterTaskWaypoints(task))
        if len(waypoints) == 0:
            # No waypoints on this task
            return

        prevTaskWaypoint = self._doc.index.previousWaypointByUuid(waypoints[0].uuid)
        nextTaskWaypoint = self._doc.index.nextWaypointByUuid(waypoints[-1].uuid)

        thisWaypoint = prevTaskWaypoint or waypoints[0]
        finalWaypoint = nextTaskWaypoint or waypoints[-1]

        # Collect feature IDs of segments to remove
        fids: list[int] = []
        while thisWaypoint.uuid != finalWaypoint.uuid:
            # Take the "from" segment for each waypoint
            _, feat = self.lineFeaturesForWaypointUuid(thisWaypoint.uuid)
            fids.append(feat.id())
            thisWaypoint = self._doc.index.nextWaypointByUuid(thisWaypoint.uuid)

        updated = False
        # No features is possible if this is the last task with waypoints in the
        # mission plan, and it only has the one waypoint.
        if fids:
            self._layer.dataProvider().deleteFeatures(fids)
            updated = True

        if prevTaskWaypoint and nextTaskWaypoint:
            # Create a new segment between the neighboring tasks.
            # Previous and next waypoints are not from the same task by definition.
            feat = self.createLineFeature(prevTaskWaypoint, nextTaskWaypoint, False)
            self._layer.dataProvider().addFeature(feat)
            updated = True

        if updated:
            self._layer.updateExtents()
            self._layer.triggerRepaint()
