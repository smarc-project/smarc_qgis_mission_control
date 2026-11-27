"""Waypoints are stored in latitude/longitude; the map may be drawn in any projection."""
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)
from qgis.gui import QgsMapCanvas

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def mapToWgs84(canvas: QgsMapCanvas, point: QgsPointXY) -> QgsPointXY:
    """A point in the canvas's map coordinates, as longitude/latitude."""
    mapCrs = canvas.mapSettings().destinationCrs()
    if mapCrs == WGS84:
        return point
    return QgsCoordinateTransform(mapCrs, WGS84, QgsProject.instance()).transform(point)


def wgs84ToMap(canvas: QgsMapCanvas, point: QgsPointXY) -> QgsPointXY:
    """A longitude/latitude point in the canvas's map coordinates."""
    mapCrs = canvas.mapSettings().destinationCrs()
    if mapCrs == WGS84:
        return point
    return QgsCoordinateTransform(WGS84, mapCrs, QgsProject.instance()).transform(point)
