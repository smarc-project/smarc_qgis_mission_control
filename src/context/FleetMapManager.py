from dataclasses import dataclass

from qgis.PyQt.QtCore import QObject, pyqtSlot, pyqtSignal, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsField, \
    QgsPointXY, QgsCategorizedSymbolRenderer, QgsSymbol, QgsUnitTypes, QgsProperty, \
    QgsRendererCategory, QgsMarkerSymbol, QgsSymbolLayer, QgsSvgMarkerSymbolLayer
from qgis.gui import QgsRubberBand
from qgis.utils import iface

from .FleetState import *


@dataclass
class VehicleMapObject:
    vehicleTopic: str
    trackRubberBand: QgsRubberBand
    lastLongitude: float | None = None
    lastLatitude: float | None = None
    lastFid: int | None = None

class FleetMapManager(QObject):
    vehicleDiscovered = pyqtSignal(str)
    vehicleExpired = pyqtSignal(str)
    vehicleUpdated = pyqtSignal(str)

    _waypointLayer: QgsVectorLayer

    def __init__(self, fleetState: FleetState, parent: QObject | None):
        super().__init__(parent)

        self._vehicles: dict[str, VehicleMapObject] = {}
        self._setupWaypointLayer()

        self._fleetState = fleetState
        self._fleetState.vehicleDiscovered.connect(self.onVehicleDiscovered)
        self._fleetState.vehicleUpdated.connect(self.onVehicleUpdated)

    def _setupWaypointLayer(self):
        qgs = QgsProject.instance()
        # Remove any stale layers
        matching = qgs.mapLayersByName('SMaRCVehiclePositionLayer')
        qgs.removeMapLayers([l.id() for l in matching])

        # Setup our layer
        self._waypointLayer = QgsVectorLayer(
            'point?crs=epsg:4326',
            'SMaRCVehiclePositionLayer',
            'memory'
        )
        self._waypointLayer.dataProvider().addAttributes([
            QgsField('vehicle-name', QVariant.String),
            QgsField('heading', QVariant.Double),
            QgsField('course', QVariant.Double),
            QgsField('depth', QVariant.Double),
            QgsField('altitude', QVariant.Double),
            QgsField('speed', QVariant.Double),
            QgsField('roll', QVariant.Double),
            QgsField('pitch', QVariant.Double),
        ])
        self._waypointLayer.updateFields()

        # Customized renderer which will colorize points for each vehicle
        self._waypointLayer.setRenderer(QgsCategorizedSymbolRenderer("vehicle-name"))

        qgs.addMapLayer(self._waypointLayer)

    def _createVehicleSymbol(self, vehicleTopic: str, color: QColor) -> QgsMarkerSymbol:
        # Pick icon by vehicle type encoded in the topic
        if '/subsurface/' in vehicleTopic:
            svg = ':/custom_icons/auv_marker.svg'
            size = 4
        elif '/surface/' in vehicleTopic:
            svg = ':/custom_icons/usv_marker.svg'
            size = 4
        elif '/air/' in vehicleTopic:
            svg = ':/custom_icons/uav_marker.svg' # can be improved!
            size = 10
        elif '/command/' in vehicleTopic:
            svg = ':/custom_icons/vehicle_marker.svg'
            size = 4
        else:
            svg = ':/custom_icons/vehicle_marker.svg'
            size = 4

        symbol = QgsMarkerSymbol()
        symbol.deleteSymbolLayer(0)  # remove default circle

        svg_layer = QgsSvgMarkerSymbolLayer(svg)
        svg_layer.setSize(size)
        svg_layer.setSizeUnit(QgsUnitTypes.RenderMetersInMapUnits) # alt. QgsUnitTypes.RenderMillimeters
        svg_layer.setFillColor(color)
        svg_layer.setStrokeColor(color.darker(150))
        svg_layer.setStrokeWidth(0.2)

        # Rotate marker by the heading field value
        svg_layer.setDataDefinedProperty(
            QgsSymbolLayer.PropertyAngle,
            QgsProperty.fromField('heading')
        )

        # Keep marker size fixed regardless of map zoom
        symbol.setScaleMethod(QgsSymbol.ScaleArea)
        symbol.appendSymbolLayer(svg_layer)

        return symbol

    @pyqtSlot(str)
    def onVehicleDiscovered(self, vehicleTopic: str):
        if vehicleTopic not in self._vehicles:
            rb = QgsRubberBand(iface.mapCanvas())
            rb.setColor(QColor(0x7F, 0x7F, 0x7F, 200))

            state = self._fleetState.vehicleState(vehicleTopic)
            assert(state)
            
            symbol = self._createVehicleSymbol(vehicleTopic, state.mapColor)

            category = QgsRendererCategory(vehicleTopic, symbol, vehicleTopic, True) # default render state off/false
            self._waypointLayer.renderer().addCategory(category)

            vehicle = VehicleMapObject(
                vehicleTopic=vehicleTopic,
                trackRubberBand=rb,
            )
            self._vehicles[vehicleTopic] = vehicle

    @pyqtSlot(str)
    def onVehicleUpdated(self, vehicleTopic: str):
        state = self._fleetState.vehicleState(vehicleTopic)
        if state is None:
            # TODO: invalid mapping
            return

        vehicle = self._vehicles[vehicleTopic]
        if state.latitude == vehicle.lastLatitude and \
            state.longitude == vehicle.lastLongitude:
            # Position has not changed, no need for a new waypoint
            # TODO: ignore extremely small (sub-cm) changes?
            return

        assert(state.latitude)
        assert(state.longitude)

        vehicle.lastLatitude = state.latitude
        vehicle.lastLongitude = state.longitude

        point = QgsPointXY(state.longitude, state.latitude)
        feat = QgsFeature(self._waypointLayer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(point))
        feat['vehicle-name'] = vehicleTopic
        feat['heading'] = state.heading
        feat['course'] = state.course
        feat['depth'] = state.depth
        feat['altitude'] = state.altitude
        feat['speed'] = state.speed
        feat['roll'] = state.roll
        feat['pitch'] = state.pitch

        self._waypointLayer.dataProvider().addFeature(feat)
        vehicle.trackRubberBand.addPoint(point)
        vehicle.lastFid = feat.id()
        self._waypointLayer.triggerRepaint()

    @pyqtSlot(str, bool)
    def onShowOnMapChanged(self, vehicleTopic: str, state: bool):
        catIdx = self._waypointLayer.renderer().categoryIndexForLabel(vehicleTopic)
        if catIdx < 0:
            # TODO: should this be logged?
            return
        self._waypointLayer.renderer().updateCategoryRenderState(catIdx, state)
        self._waypointLayer.triggerRepaint()

    @pyqtSlot(str, QColor)
    def onMapColorChanged(self, vehicleTopic: str, color: QColor):
        catIdx = self._waypointLayer.renderer().categoryIndexForLabel(vehicleTopic)
        if catIdx < 0:
            # TODO: should this be logged?
            return

        # symbol = QgsSymbol.defaultSymbol(self._waypointLayer.geometryType()) # old
        # symbol.setColor(color) # old
        symbol = self._createVehicleSymbol(vehicleTopic, color)

        state = self._fleetState.vehicleState(vehicleTopic)
        if state is not None:
            state.mapColor = color

        self._waypointLayer.renderer().updateCategorySymbol(catIdx, symbol)
        self._waypointLayer.triggerRepaint()

    @pyqtSlot(str)
    def onLookAtRequested(self, vehicleTopic: str):
        vehicle = self._vehicles.get(vehicleTopic)
        if vehicle is None or vehicle.lastFid is None:
            return

        iface.mapCanvas().zoomToFeatureIds(self._waypointLayer, [vehicle.lastFid])
        iface.mapCanvas().zoomScale(25000) # zoom to fixed scale (e.g. 1:500)

    def clearAllVehicleMarkers(self):
        # Clear all features from the vector layer
        self._waypointLayer.dataProvider().truncate()
        self._waypointLayer.triggerRepaint()

        # Clear all rubber band tracks and reset vehicle positions
        for vehicle in self._vehicles.values():
            vehicle.trackRubberBand.reset()
            vehicle.lastLatitude = None
            vehicle.lastLongitude = None
            vehicle.lastFid = None
