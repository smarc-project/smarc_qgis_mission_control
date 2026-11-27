from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsMapRendererSequentialJob,
    QgsMapSettings,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsRenderContext,
    QgsSymbolLayer,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QImage

# The marker SVGs live in the plugin's Qt resources.
import src.ui.generated.resources_rc  # noqa: F401
from src.context.FleetMapManager import (
    TRACK_POINT_MAX_SIZE_MM,
    TRACK_POINT_MIN_SIZE_MM,
    VEHICLE_MARKER_MAX_SIZE_MM,
    VEHICLE_MARKER_MIN_SIZE_MM,
)

SAM = "waraps/unit/subsurface/simulation/sam1"
CANVAS_PX = 400
DPI = 96
PX_PER_MM = DPI / 25.4
# Antialiasing and the outline stroke add about a pixel on each side.
STROKE_PX = 2
# Map widths in web-mercator meters on the 400 px canvas. At SAM's latitude
# these are about 1:75 000 and 1:55.
ZOOMED_OUT = 20_000.0
ZOOMED_IN = 15.0
# A track of this many points, this far apart (m), heading north into SAM:
# about 3 km, a hundred-odd pixels zoomed out, so most of it is clear of the marker.
LONG_TRACK_POINTS = 600
LONG_TRACK_SPACING = 5.0
METERS_PER_DEGREE_LAT = 111_320
WEB_MERCATOR = QgsCoordinateReferenceSystem("EPSG:3857")
WHITE = QColor("white").rgb()


def _mapSettings(mapWidth: float) -> QgsMapSettings:
    """The live layer on a square map `mapWidth` mercator meters wide, centred on SAM."""
    [layer] = QgsProject.instance().mapLayersByName("SMaRCVehiclePositionLayer")
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(WEB_MERCATOR)
    settings.setOutputSize(QSize(CANVAS_PX, CANVAS_PX))
    settings.setOutputDpi(DPI)
    settings.setBackgroundColor(QColor("white"))
    centre = settings.layerToMapCoordinates(layer, QgsPointXY(11.0, 59.0))
    half = mapWidth / 2
    settings.setExtent(QgsRectangle(
        centre.x() - half,
        centre.y() - half,
        centre.x() + half,
        centre.y() + half,
    ))
    return settings


def _render(mapWidth: float) -> QImage:
    job = QgsMapRendererSequentialJob(_mapSettings(mapWidth))
    job.start()
    job.waitForFinished()
    return job.renderedImage()


def _rowWidthsPx(image: QImage) -> list[int]:
    """Drawn width of each pixel row that has anything drawn, top to bottom."""
    widths = []
    for y in range(image.height()):
        drawn = [x for x in range(image.width()) if image.pixel(x, y) != WHITE]
        if drawn:
            widths.append(drawn[-1] - drawn[0] + 1)
    return widths


def _sizesPx(mapWidth: float) -> tuple[float, float]:
    """The size QGIS gives SAM's marker and its track points, in pixels."""
    [layer] = QgsProject.instance().mapLayersByName("SMaRCVehiclePositionLayer")
    renderer = layer.renderer()
    # Hold the category list: each symbol belongs to its (copied) category.
    categories = renderer.categories()
    symbol = categories[renderer.categoryIndexForLabel(SAM)].symbol()
    settings = _mapSettings(mapWidth)
    context = QgsRenderContext.fromMapSettings(settings)

    def toPx(symbolLayer: QgsSymbolLayer) -> float:
        return context.convertToPainterUnits(
            symbolLayer.size(),
            symbolLayer.sizeUnit(),
            symbolLayer.sizeMapUnitScale(),
        )

    marker, trackPoint = symbol.symbolLayer(0), symbol.symbolLayer(1)
    return toPx(marker), toPx(trackPoint)


def test_vehicle_marker_stays_visible_zoomed_out(fleet):
    states, _ = fleet
    states.move(SAM, 0.0, 59.0)

    markerPx, trackPointPx = _sizesPx(ZOOMED_OUT)
    # A few meters of vehicle is far under a pixel here; the minimum holds it.
    assert abs(markerPx - VEHICLE_MARKER_MIN_SIZE_MM * PX_PER_MM) <= STROKE_PX
    assert abs(trackPointPx - TRACK_POINT_MIN_SIZE_MM * PX_PER_MM) <= STROKE_PX
    # And it is drawn. The SVG's own margin makes it a little narrower than its size.
    assert 0 < max(_rowWidthsPx(_render(ZOOMED_OUT))) <= markerPx + STROKE_PX


def test_vehicle_marker_does_not_fill_the_map_zoomed_in(fleet):
    states, _ = fleet
    states.move(SAM, 0.0, 59.0)

    markerPx, trackPointPx = _sizesPx(ZOOMED_IN)
    # In meters alone SAM would be most of the 400 px map wide.
    assert abs(markerPx - VEHICLE_MARKER_MAX_SIZE_MM * PX_PER_MM) <= STROKE_PX
    assert abs(trackPointPx - TRACK_POINT_MAX_SIZE_MM * PX_PER_MM) <= STROKE_PX
    assert max(_rowWidthsPx(_render(ZOOMED_IN))) <= markerPx + STROKE_PX


def test_a_long_track_stays_narrower_than_the_marker_zoomed_out(fleet):
    states, _ = fleet
    for i in range(LONG_TRACK_POINTS, -1, -1):
        states.move(SAM, 0.0, 59.0 - i * LONG_TRACK_SPACING / METERS_PER_DEGREE_LAT)

    _, trackPointPx = _sizesPx(ZOOMED_OUT)
    rows = _rowWidthsPx(_render(ZOOMED_OUT))
    # The track runs south of the marker, which sits at the top of the drawing.
    trackOnly = rows[len(rows) // 2:]
    assert max(trackOnly) <= trackPointPx + STROKE_PX
    # The marker still stands out of its track instead of being buried in it.
    assert max(rows) >= 2 * max(trackOnly)
