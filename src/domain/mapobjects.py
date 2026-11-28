"""Map objects from the WARA-PS map-objects API (AsyncAPI 1.1.2).

Each object is one retained message on `{organization}/general/generic/real/c2/target/positions/{name}`,
where the name ends in -P (point), -R (path) or -A (area: polygon or circle). A new message on the
same topic replaces the object; an empty one clears it, which is also how MQTT drops a retained message.

`duration` is our own addition to the WARA-PS payload: seconds the object stays on the map after it
arrives. Missing or 0 keeps it until it is replaced or cleared.
"""
import json
import math
import re
from dataclasses import dataclass

from ..compat import StrEnum

mapObjectTopicPattern = re.compile(
    r'[^/]+/general/generic/real/c2/target/positions/([^/]+-[PRA])$'
)
# WARA-PS's WebColor.
webColorPattern = re.compile(r'#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$')


class MapObjectShape(StrEnum):
    """The payload's `type` field."""
    POINT = 'point'
    PATH = 'polyline'
    POLYGON = 'area'
    CIRCLE = 'circle'


# The topic suffix says which shapes may be sent on it; polygons and circles share -A.
SHAPES_BY_NAME_SUFFIX = {
    '-P': (MapObjectShape.POINT,),
    '-R': (MapObjectShape.PATH,),
    '-A': (MapObjectShape.POLYGON, MapObjectShape.CIRCLE),
}

# Fewest corners WARA-PS allows for a path and for a polygon.
MIN_PATH_POINTS = 2
MIN_POLYGON_POINTS = 3


@dataclass
class MapObject:
    name: str
    shape: MapObjectShape
    # (latitude, longitude) pairs: one for a point or a circle's centre, the corners otherwise.
    latLons: list[tuple[float, float]]
    radius: float | None = None
    # A web colour ("#RRGGBB"); None draws in the plugin's map-object colour.
    color: str | None = None
    # Seconds on the map after arrival; 0 is until replaced or cleared.
    duration: float = 0.0


def mapObjectNameFromTopic(topic: str) -> str | None:
    """The map object's name (e.g. "dive-site-A") if the topic is a WARA-PS map object's."""
    match = mapObjectTopicPattern.match(topic)
    return match.group(1) if match else None


def _latLon(pair: object) -> tuple[float, float]:
    if not isinstance(pair, list) or len(pair) != 2:
        raise ValueError(f'expected [lat, lon], got {pair!r}')
    lat, lon = (float(value) for value in pair)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f'[lat, lon] out of range: {pair!r}')
    return lat, lon


def _latLonList(pairs: object, minPoints: int) -> list[tuple[float, float]]:
    if not isinstance(pairs, list) or len(pairs) < minPoints:
        raise ValueError(f'expected at least {minPoints} [lat, lon] pairs, got {pairs!r}')
    return [_latLon(pair) for pair in pairs]


def parseMapObject(name: str, payload: bytes) -> MapObject:
    """Read one map-object message; raises ValueError saying what is wrong with it."""
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f'not JSON: {e}') from e
    if not isinstance(data, dict):
        raise ValueError('not a JSON object')

    try:
        shape = MapObjectShape(data.get('type'))
    except ValueError as e:
        raise ValueError(f'unknown type {data.get("type")!r}') from e
    if shape not in SHAPES_BY_NAME_SUFFIX.get(name[-2:], ()):
        raise ValueError(f'a {shape} cannot be sent on a {name[-2:]} topic')

    radius = None
    try:
        if shape == MapObjectShape.PATH:
            latLons = _latLonList(data['line'], MIN_PATH_POINTS)
        elif shape == MapObjectShape.POLYGON:
            latLons = _latLonList(data['area'], MIN_POLYGON_POINTS)
        else:
            latLons = [_latLon([data['lat'], data['lon']])]
        if shape == MapObjectShape.CIRCLE:
            radius = float(data['radius'])
            if not math.isfinite(radius) or radius <= 0:
                raise ValueError(f'radius must be a positive number, got {radius}')
        duration = float(data.get('duration', 0))
    except KeyError as e:
        raise ValueError(f'a {shape} needs {e}') from e
    except TypeError as e:
        raise ValueError(str(e)) from e
    if not math.isfinite(duration) or duration < 0:
        raise ValueError(f'duration must be a number of seconds, 0 or more, got {duration}')

    color = data.get('color')
    if color is not None and not (isinstance(color, str) and webColorPattern.match(color)):
        raise ValueError(f'color must be "#RGB" or "#RRGGBB", got {color!r}')

    return MapObject(
        name=name,
        shape=shape,
        latLons=latLons,
        radius=radius,
        color=color,
        duration=duration,
    )
