from typing import (get_type_hints, get_args,
                    Type, ClassVar, Annotated)
from dataclasses import dataclass, field, fields
from uuid import UUID, uuid4

from ..compat import StrEnum
from .schema import Schema, SchemaMixin, Unit, Column
from .waypoints import *

__all__ = [
    "Task",
    "TaskType",
    "TaskRegistry",

    "WaypointTask",
    "SingleWaypointTask",
    "MultiWaypointTask",
]

class TaskType(StrEnum):
    """Supported task types. Ordering here influences ordering in the UI."""

    # WARA-PS
    MOVE_TO     = "move-to"
    MOVE_PATH   = "move-path"
    # SEARCH_AREA = "search-area"

    # Custom tasks
    AUV_DEPTH_MOVE_TO   = "auv-depth-move-to"
    AUV_DEPTH_MOVE_PATH = "auv-depth-move-path"
    # AUV_SPIRAL_TO_DEPTH = "auv-spiral-to-depth"
    LOITER              = "loiter"
    # DEPLOY_PAYLOAD  = "deploy-payload"
    CUSTOM              = "custom-task"
    
    # Geofence tasks
    SMARC_START_GEOFENCE = "smarc-start-geofence"
    SMARC_STOP_GEOFENCE = "smarc-stop-geofence"

    # Basic smarc tasks
    SMARC_WAIT = "smarc-wait"
    SMARC_LOG = "smarc-log"

    # Gimbal cam tasks
    GIMBAL_SET_RPY = "gimbal-set-rpy"
    GIMBAL_STOP = "gimbal-stop"
    # for later
    # GIMBAL_SET_GEOPOINT = "gimbal-set-geopoint"
    # GIMBAL_TRACK_IMG_POI = "gimbal-track-img-poi"
    # GIMBAL_TRACK_ODOM_POI = "gimbal-track-odom-poi"



    # Alars tasks
    ALARS_TAKEOFF = "alars-takeoff"
    ALARS_LAND    = "alars-land"
    ALARS_TAKE_CONTROL = "alars-take-control"
    ALARS_RELEASE_CONTROL = "alars-release-control"
    # Requries handling of multiple wps not in a list, so not supported for now
    ALARS_BT = "alars-bt"
    ALARS_SEARCH = "alars-search"
    ALARS_RECOVER = "alars-recover"
    ALARS_FOLLOW_AUV = "alars-follow-auv"


@dataclass
class Task(SchemaMixin):
    """
    This class represent a single task. All other task classes subclass from this. Each
    task has a description, a unique ID and a type associated with it. Tasks can also
    define parameters, which have to be `Annotated`, just like `Waypoint` parameters.
    """
    description : str
    #: Task UUID is either loaded, or automatically generated.
    uuid        : UUID = field(default_factory = uuid4, kw_only = True)
    #: Type is filled in by subclasses.
    type        : ClassVar[TaskType]

    @classmethod
    def fromJson(cls, data: dict):
        # This should always be overwritten, as type field determines the subclass
        raise NotImplementedError

    def toJson(self) -> dict:
        return {
            "description": self.description,
            "task-uuid": str(self.uuid),
            # Confusingly, `type` is stored as `name`
            "name": str(self.type)
        }

class TaskRegistry:
    registry: dict[TaskType, Type[Task]] = {}

    @classmethod
    def register(cls, taskCls: Type[Task]) -> Type[Task]:
        prevCls = cls.registry.get(taskCls.type)
        if prevCls:
            raise ValueError(f"Duplicate task type '{taskCls.type}' for "
                             f"{taskCls.__name__} and {prevCls.__name__}")
        cls.registry[taskCls.type] = taskCls

        return taskCls

    @classmethod
    def lookup(cls, type: TaskType) -> Type[Task]:
        if not type in cls.registry:
            raise KeyError(f"Unknown task type '{type}'")
        return cls.registry[type]

@dataclass
class WaypointTask(Task):
    """Represents a task defined by any number of waypoints."""
    waypointClass: ClassVar[Type[Waypoint]]

@dataclass
class SingleWaypointTask(WaypointTask):
    """Represents a task defined by a single waypoint."""
    waypoint: Waypoint

    @dataclass
    class Pending:
        """A SingleWaypointTask pending creation, awaiting waypoint location."""
        taskCls: Type['SingleWaypointTask']
        description: str
        taskUuid: UUID
        waypointUuid: UUID

@dataclass
class MultiWaypointTask(WaypointTask):
    """Represents a task defined by multiple waypoints."""
    waypoints: list[Waypoint] = field(default_factory = list)

###############################################################################
# Define your tasks below here
###############################################################################

class MovementSpeedParam(StrEnum):
    # WARA-PS
    # The meaning of these values is system-dependent
    SLOW     = "slow"
    STANDARD = "standard"
    FAST     = "fast"

@TaskRegistry.register
@dataclass
class MoveToTask(SingleWaypointTask):
    type          = TaskType.MOVE_TO
    waypointClass = GeoPoint

    # Task Parameters
    #: Speed as specified in WARA-PS
    speed: Annotated[MovementSpeedParam, Column("Speed")] \
         = MovementSpeedParam.STANDARD

    @classmethod
    def fromJson(cls, data: dict) -> 'MoveToTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            waypoint = GeoPoint.fromJson(data["params"]["waypoint"]),
            speed = MovementSpeedParam(data["params"]["speed"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "speed": str(self.speed),
                "waypoint": self.waypoint.toJson()
            }
        }

@TaskRegistry.register
@dataclass
class MovePathTask(MultiWaypointTask):
    type          = TaskType.MOVE_PATH
    waypointClass = GeoPoint

    # Task Parameters
    #: Speed as specified in WARA-PS
    speed: Annotated[MovementSpeedParam, Column("Speed")] \
         = MovementSpeedParam.STANDARD

    @classmethod
    def fromJson(cls, data: dict) -> 'MovePathTask':
        assert(data["name"] == str(cls.type))
        wps = list(map(GeoPoint.fromJson, data["params"]["waypoints"]))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            waypoints = wps,
            speed = MovementSpeedParam(data["params"]["speed"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "speed": str(self.speed),
                "waypoints": [w.toJson() for w in self.waypoints]
            }
        }

@TaskRegistry.register
@dataclass
class AUVDepthMoveToTask(SingleWaypointTask):
    type          = TaskType.AUV_DEPTH_MOVE_TO
    waypointClass = AUVWaypoint

    @classmethod
    def fromJson(cls, data: dict) -> 'AUVDepthMoveToTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            waypoint = AUVWaypoint.fromJson(data["params"]["waypoint"])
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "waypoint": self.waypoint.toJson()
            }
        }

@TaskRegistry.register
@dataclass
class AUVDepthMovePathTask(MultiWaypointTask):
    type          = TaskType.AUV_DEPTH_MOVE_PATH
    waypointClass = AUVWaypoint

    @classmethod
    def fromJson(cls, data: dict) -> 'AUVDepthMovePathTask':
        assert(data["name"] == str(cls.type))
        wps = list(map(AUVWaypoint.fromJson, data["params"]["waypoints"]))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            waypoints = wps
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "waypoints": [w.toJson() for w in self.waypoints]
            }
        }

@TaskRegistry.register
@dataclass
class LoiterTask(Task):
    type = TaskType.LOITER

    # Task Parameters
    #: TODO
    timeout: Annotated[float, Unit("s"), Column("Timeout")] \
           = .0

    @classmethod
    def fromJson(cls, data: dict) -> 'LoiterTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            timeout = float(data["params"]["timeout"])
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "timeout": self.timeout
            }
        }

@TaskRegistry.register
@dataclass
class CustomTask(Task):
    type = TaskType.CUSTOM

    action : Annotated[str, Column("Action")] \
           = ""
    json   : Annotated[str, Column("JSON")] \
           = ""

    @classmethod
    def fromJson(cls, data: dict) -> 'CustomTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            action = str(data["params"]["action-name"]),
            json = str(data["params"]["json-params"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "action-name": self.action,
                "json-params": self.json,
            }
        }


#### Geofence Tasks ####
@TaskRegistry.register
@dataclass
class SmarcStartGeofenceTask(Task):
    type          = TaskType.SMARC_START_GEOFENCE
    waypointClass = GeoPoint

    # Task parameters
    ceiling_altitude: Annotated[float, Unit("m"), Column("CeilingAltitude")] \
           = -1.0
    floor_altitude: Annotated[float, Unit("m"), Column("FloorAltitude")] \
           = 1.0
    stay_inside: Annotated[bool, Column("StayInside")] \
           = True

    @classmethod
    def fromJson(cls, data: dict) -> 'SmarcStartGeofenceTask':
        assert(data["name"] == str(cls.type))
        wps = list(map(GeoPoint.fromJson, data["params"]["waypoints"]))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            waypoints = wps,
            ceiling_altitude = float(data["params"]["ceiling_altitude"]),
            floor_altitude = float(data["params"]["floor_altitude"]),
            stay_inside = bool(data["params"]["stay_inside"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "waypoints": [w.toJson() for w in self.waypoints],
                "ceiling_altitude": self.ceiling_altitude,
                "floor_altitude": self.floor_altitude,
                "stay_inside": self.stay_inside
            }
        }
    
@TaskRegistry.register
@dataclass
class SmarcStopGeofenceTask(Task):
    type = TaskType.SMARC_STOP_GEOFENCE

    # Task parameters
    reset_geofence: Annotated[bool, Column("ResetGeofence")] \
        = True
    reset_islands: Annotated[bool, Column("ResetIslands")] \
        = True

    @classmethod
    def fromJson(cls, data: dict) -> 'SmarcStopGeofenceTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            reset_geofence = bool(data["params"]["reset_geofence"]),
            reset_islands = bool(data["params"]["reset_islands"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "reset_geofence": self.reset_geofence,
                "reset_islands": self.reset_islands,
            }
        }
    

@TaskRegistry.register
@dataclass
class SmarcWaitTask(Task):
    type = TaskType.SMARC_WAIT

    # Task parameters
    timeout: Annotated[float, Unit("s"), Column("Timeout")] \
        = 0.0

    @classmethod
    def fromJson(cls, data: dict) -> 'SmarcWaitTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            timeout = float(data["params"]["timeout"]),
        )   
    
    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "timeout": self.timeout,
            }
        }
    
@TaskRegistry.register
@dataclass
class SmarcLogTask(Task):
    type = TaskType.SMARC_LOG

    # Task parameters
    log_str: Annotated[str, Column("LogStr")] \
        = ""

    @classmethod
    def fromJson(cls, data: dict) -> 'SmarcLogTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            log_str = str(data["params"]["log_str"]),
        )   
    
    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "message": self.log_str,
            }
        }
    
    

#### Gimbal Tasks ####
@TaskRegistry.register
@dataclass
class GimbalSetRPYTask(Task):
    type = TaskType.GIMBAL_SET_RPY

    # Task parameters
    roll: Annotated[float, Unit("°"), Column("Roll")] \
        = 0.0
    pitch: Annotated[float, Unit("°"), Column("Pitch")] \
        = 0.0
    yaw: Annotated[float, Unit("°"), Column("Yaw")] \
        = 0.0

    @classmethod
    def fromJson(cls, data: dict) -> 'GimbalSetRPYTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            roll = float(data["params"]["roll"]),
            pitch = float(data["params"]["pitch"]),
            yaw = float(data["params"]["yaw"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "roll": self.roll,
                "pitch": self.pitch,
                "yaw": self.yaw,
            }
        }
    
@TaskRegistry.register
@dataclass
class GimbalStopTask(Task):
    type          = TaskType.GIMBAL_STOP

    @classmethod
    def fromJson(cls, data: dict) -> 'GimbalStopTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {}
        }
    



#### ALARS Tasks ####
@TaskRegistry.register
@dataclass
class AlarsTakeOffTask(Task):
    type          = TaskType.ALARS_TAKEOFF

    @classmethod
    def fromJson(cls, data: dict) -> 'AlarsTakeOffTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {}
        }
    
@TaskRegistry.register
@dataclass
class AlarsLandTask(Task):
    type          = TaskType.ALARS_LAND

    @classmethod
    def fromJson(cls, data: dict) -> 'AlarsLandTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {}
        }
    
@TaskRegistry.register
@dataclass
class AlarsTakeControlTask(Task):
    type          = TaskType.ALARS_TAKE_CONTROL

    @classmethod
    def fromJson(cls, data: dict) -> 'AlarsTakeControlTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {}
        }
    

@TaskRegistry.register
@dataclass
class AlarsReleaseControlTask(Task):
    type          = TaskType.ALARS_RELEASE_CONTROL

    @classmethod
    def fromJson(cls, data: dict) -> 'AlarsReleaseControlTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {}
        }


@TaskRegistry.register
@dataclass
class AlarsBTTask(Task):
    type = TaskType.ALARS_BT
    waypointsClass = GeoPoint

    # Task parameters
    num_retries: Annotated[int, Column("#Retries")] \
           = 5
    forward_distance: Annotated[float, Unit("m"), Column("ForwardDistance")] \
           = 2.0
    forward_altitude: Annotated[float, Unit("m"), Column("ForwardAltitude")] \
           = 3.0
    dipping_altitude: Annotated[float, Unit("m"), Column("DippingAltitude")] \
           = 7.0
    raising_altitude: Annotated[float, Unit("m"), Column("RaisingAltitude")] \
           = 15.0


    @classmethod
    def fromJson(cls, data: dict) -> 'AlarsBTTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            num_retries = int(data["params"]["num_retries"]),
            search_position = GeoPoint.fromJson(data["params"]["search_position"]),
            forward_distance = float(data["params"]["forward_distance"]),
            forward_altitude = float(data["params"]["forward_altitude"]),
            dipping_altitude = float(data["params"]["dipping_altitude"]),
            raising_altitude = float(data["params"]["raising_altitude"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "num_retries": self.num_retries,
                "search_position": self.search_position.toJson(),
                "forward_distance": self.forward_distance,
                "forward_altitude": self.forward_altitude,
                "dipping_altitude": self.dipping_altitude,
                "raising_altitude": self.raising_altitude,
            }
        }

@TaskRegistry.register
@dataclass
class AlarsSearchTask(Task):
    type = TaskType.ALARS_SEARCH
    waypointClass = GeoPoint

    @classmethod
    def fromJson(cls, data: dict) -> 'AlarsSearchTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            search_position = GeoPoint.fromJson(data["params"]["search_position"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "search_position": self.search_position.toJson(),
            }
        }

@TaskRegistry.register
@dataclass
class AlarsRecoverTask(Task):
    type = TaskType.ALARS_RECOVER

    # Task parameters
    forward_distance: Annotated[float, Unit("m"), Column("ForwardDistance")] \
           = 2.0
    forward_altitude: Annotated[float, Unit("m"), Column("ForwardAltitude")] \
           = 3.0
    dipping_altitude: Annotated[float, Unit("m"), Column("DippingAltitude")] \
           = 7.0
    raising_altitude: Annotated[float, Unit("m"), Column("RaisingAltitude")] \
           = 15.0
    no_buoy_radius: Annotated[float, Unit("m"), Column("NoBuoyRadius")] \
           = -1.0

    @classmethod
    def fromJson(cls, data: dict) -> 'AlarsRecoverTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            forward_distance = float(data["params"]["forward_distance"]),
            forward_altitude = float(data["params"]["forward_altitude"]),
            dipping_altitude = float(data["params"]["dipping_altitude"]),
            raising_altitude = float(data["params"]["raising_altitude"]),
            no_buoy_radius = float(data["params"]["no_buoy_radius"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "forward_distance": self.forward_distance,
                "forward_altitude": self.forward_altitude,
                "dipping_altitude": self.dipping_altitude,
                "raising_altitude": self.raising_altitude,
                "no_buoy_radius": self.no_buoy_radius,
            }
        }
    
@TaskRegistry.register
@dataclass
class AlarsFollowAUVTask(Task):
    type = TaskType.ALARS_FOLLOW_AUV

    # Task parameters
    follow_altitude: Annotated[float, Unit("m"), Column("FollowAltitude")] \
           = 15.0
    vulture_radius: Annotated[float, Unit("m"), Column("VultureRadius")] \
           = 0.0
    vulture_speed_deg: Annotated[float, Unit("°/s"), Column("VultureSpeedDeg")] \
           = 10.0

    @classmethod
    def fromJson(cls, data: dict) -> 'AlarsFollowAUVTask':
        assert(data["name"] == str(cls.type))
        return cls(
            description = str(data["description"]),
            uuid = UUID(data["task-uuid"]),
            follow_altitude = float(data["params"]["follow_altitude"]),
            vulture_radius = float(data["params"]["vulture_radius"]),
            vulture_speed_deg = float(data["params"]["vulture_speed_deg"]),
        )

    def toJson(self) -> dict:
        return super().toJson() | {
            "params": {
                "follow_altitude": self.follow_altitude,
                "vulture_radius": self.vulture_radius,
                "vulture_speed_deg": self.vulture_speed_deg,
            }
        }
