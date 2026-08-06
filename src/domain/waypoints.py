from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID, uuid4

from .jsoncodec import JsonCodec
from .schema import Column, SchemaMixin, Unit

__all__ = ["Waypoint", "AUVWaypoint", "GeoPoint"]


@dataclass
class Waypoint(SchemaMixin):
    """
    This class represents a bare 2D waypoint, and holds only its location.
    """

    latitude  : Annotated[float, Unit("°"), Column("Lat.", "Latitude" )] \
              = .0
    longitude : Annotated[float, Unit("°"), Column("Lon.", "Longitude")] \
              = .0
    #: Internal use. For associating a `QgsFeatureId` with the waypoint.
    uuid      : UUID = field(default_factory = uuid4, kw_only = True)

    @classmethod
    def fromJson(cls, data: dict):
        """Load a waypoint from mission plan JSON."""
        return JsonCodec.decodeSchema(cls, data)


@dataclass
class AUVWaypoint(Waypoint):
    """
    This class represents waypoints used for autonomous underwater vehicles.
    """

    #: Depth below the sea level. TODO: or below some other level?
    target_depth : Annotated[float, Unit("m"), Column("Depth")] \
                 =    .0
    #: Minimum altitude from the sea floor; takes priority over `target_depth`.
    min_altitude : Annotated[float, Unit("m"), Column("Min. Alt.", "Min. Altitude")] \
                 =    .0
    #: Distance within which the waypoint is considered reached.
    tolerance    : Annotated[float, Unit("m"), Column("Tol.", "Tolerance")] \
                 =  10.0
    #: RPM used while traveling to the waypoint.
    rpm          : Annotated[float, Column("RPM")] \
                 = 500.0
    #: TODO
    timeout      : Annotated[float, Unit("s"), Column("Timeout")] \
                 =    .0

    @classmethod
    def fromJson(cls, data: dict) -> 'AUVWaypoint':
        # make sure not parsing a WARA-PS GeoPoint by accident
        if data.get("rostype") == "GeoPoint":
            raise ValueError(f"GeoPoint data passed to {cls.__name__}")
        return JsonCodec.decodeSchema(cls, data)


@dataclass
class GeoPoint(Waypoint):
    #: Altitude above some reference height, e.g. geoid or water surface.
    altitude  : Annotated[float, Unit("m"), Column("Alt.", "Altitude")] \
              =   .0
    #: Distance within which the waypoint is considered reached.
    #: NOTE: not part of WARA-PS spec
    tolerance : Annotated[float, Unit("m"), Column("Tol.", "Tolerance")] \
              =  10.0

    def toJson(self) -> dict:
        return JsonCodec.encodeSchema(self) | {
            "rostype"   : "GeoPoint",
        }

    @classmethod
    def fromJson(cls, data: dict) -> 'GeoPoint':
        # make sure we ARE parsing a WARA-PS GeoPoint
        if data.get("rostype") != "GeoPoint":
            raise ValueError(f"Non-GeoPoint data passed to {cls.__name__}")
        return JsonCodec.decodeSchema(cls, data)
