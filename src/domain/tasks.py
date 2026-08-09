from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Callable, ClassVar, Type, TypeVar, cast
from uuid import UUID, uuid4

from ..compat import StrEnum
from .jsoncodec import JsonCodec
from .schema import Column, SchemaMixin, Unit
from .waypoints import AUVWaypoint, GeoPoint, Waypoint

__all__ = [
    "Task",
    "TaskRegistry",
    "task",
    "PendingWaypointTask",
    "UnsupportedTaskCreationError"
]


TaskInstanceT = TypeVar("TaskInstanceT", bound="Task")
TaskT = TypeVar("TaskT", bound=Type["Task"])


@dataclass(kw_only=True)
class Task(SchemaMixin):
    """
    This class represents a single task. Task parameters are the annotated fields
    declared by each task subclass.
    """
    description : str
    #: Task UUID is either loaded, or automatically generated.
    uuid        : UUID = field(default_factory = uuid4)
    #: Type is set by subclasses.
    type        : ClassVar[str]

    def toJson(self) -> dict:
        return {
            "description": self.description,
            "task-uuid": str(self.uuid),
            # Confusingly, `type` is stored as `name`
            "name": self.type,
            "params": JsonCodec.encodeSchema(self)
        }

    @classmethod
    def fromJson(cls: Type[TaskInstanceT], data: dict) -> TaskInstanceT:
        if data["name"] != cls.type:
            raise TypeError(f"{cls.__name__} got JSON for type '{data['name']}' but " \
                            f"expected type '{cls.type}'")

        return JsonCodec.decodeSchema(cls, data["params"], extra_kwargs = {
            "description": str(data["description"]),
            "uuid": UUID(data["task-uuid"])
        })


class TaskRegistry:
    registry: dict[str, Type[Task]] = {}

    @classmethod
    def register(cls, typeId: str, taskCls: Type[Task]) -> None:
        prevCls = cls.registry.get(typeId)
        if prevCls:
            raise ValueError(f"Duplicate task type '{typeId}' for "
                             f"{taskCls.__name__} and {prevCls.__name__}")

        cls.registry[typeId] = taskCls

    @classmethod
    def lookup(cls, typeId: str) -> Type[Task]:
        try:
            return cls.registry[typeId]
        except KeyError:
            raise KeyError(f"Unknown task type '{typeId}'") from None

    @classmethod
    def taskFromJson(cls, data: dict) -> Task:
        # NOTE: task "name" is actually the type, e.g. move-to
        return cls.lookup(data["name"]).fromJson(data)


if TYPE_CHECKING:
    from typing_extensions import dataclass_transform
else:
    def dataclass_transform(*args, **kwargs):
        return lambda x: x


@dataclass_transform(kw_only_default=True)
def task(typeId: str) -> Callable[[TaskT], TaskT]:
    def decorate(taskCls: TaskT) -> TaskT:
        if not issubclass(taskCls, Task):
            raise TypeError(f"@task classes must subclass {Task.__name__}")

        taskCls = cast(TaskT, dataclass(kw_only=True)(taskCls))
        taskCls.type = typeId

        TaskRegistry.register(typeId, taskCls)
        return taskCls
    return decorate


@dataclass(frozen=True)
class PendingWaypointTask:
    taskCls: Type[Task]
    fieldName: str
    waypointCls: Type[Waypoint]
    description: str
    taskUuid: UUID
    waypointUuid: UUID


class UnsupportedTaskCreationError(ValueError):
    pass

###############################################################################
# Define your tasks below here
###############################################################################

class MovementSpeedParam(StrEnum):
    # WARA-PS
    # The meaning of these values is system-dependent
    SLOW     = "slow"
    STANDARD = "standard"
    FAST     = "fast"

class SuccorModeParam(StrEnum):
    # as defined in utilities/serial_ping_pkg/.../modem_ping_estimator_node
    ADD = "add"
    REMOVE = "remove"
    CLEAR = "clear"
    PING = "ping"

class AreaTypeParam(StrEnum):
    # WARA-PS
    WATER = "water"
    BEACH = "beach"
    FOREST = "forest"
    FIELD = "field"


@task("move-to")
class MoveToTask(Task):
    #: Speed as specified in WARA-PS
    speed: Annotated[MovementSpeedParam, Column("Speed")] \
        = MovementSpeedParam.STANDARD
    waypoint: Annotated[GeoPoint, Column("Waypoint")]

@task("move-path")
class MovePathTask(Task):
    #: Speed as specified in WARA-PS
    speed: Annotated[MovementSpeedParam, Column("Speed")] \
        = MovementSpeedParam.STANDARD
    waypoints: Annotated[list[GeoPoint], Column("Waypoints")] \
        = field(default_factory = list)

@task("auv-depth-move-to")
class AUVDepthMoveToTask(Task):
    waypoint: Annotated[AUVWaypoint, Column("Waypoint")]

@task("auv-depth-move-path")
class AUVDepthMovePathTask(Task):
    waypoints: Annotated[list[AUVWaypoint], Column("Waypoints")] \
        = field(default_factory = list)

@task("loiter")
class LoiterTask(Task):
    #: TODO
    timeout: Annotated[float, Unit("s"), Column("Timeout")] \
        = .0

@task("custom-task")
class CustomTask(Task):
    action_name: Annotated[str, Column("Action")] \
        = ""
    json_params: Annotated[str, Column("JSON")] \
        = ""


#### Geofence Tasks ####
@task("smarc-start-geofence")
class SmarcStartGeofenceTask(Task):
    ceiling_altitude: Annotated[float, Unit("m"), Column("CeilingAltitude")] \
        = -1.0
    floor_altitude: Annotated[float, Unit("m"), Column("FloorAltitude")] \
        = 1.0
    stay_inside: Annotated[bool, Column("StayInside")] \
        = True
    waypoints: Annotated[list[GeoPoint], Column("Waypoints")] \
        = field(default_factory = list)

@task("smarc-stop-geofence")
class SmarcStopGeofenceTask(Task):
    reset_geofence: Annotated[bool, Column("ResetGeofence")] \
        = True
    reset_islands: Annotated[bool, Column("ResetIslands")] \
        = True

@task("smarc-wait")
class SmarcWaitTask(Task):
    timeout: Annotated[float, Unit("s"), Column("Timeout")] \
        = 0.0

@task("smarc-log")
class SmarcLogTask(Task):
    log_str: Annotated[str, Column("LogStr")] \
        = ""



#### Gimbal Tasks ####
@task("gimbal-set-rpy")
class GimbalSetRPYTask(Task):
    roll: Annotated[float, Unit("°"), Column("Roll")] \
        = 0.0
    pitch: Annotated[float, Unit("°"), Column("Pitch")] \
        = 0.0
    yaw: Annotated[float, Unit("°"), Column("Yaw")] \
        = 0.0

@task("gimbal-stop")
class GimbalStopTask(Task):
    pass




#### ALARS Tasks ####
@task("alars-takeoff")
class AlarsTakeOffTask(Task):
    pass

@task("alars-land")
class AlarsLandTask(Task):
    pass

@task("alars-take-control")
class AlarsTakeControlTask(Task):
    pass

@task("alars-release-control")
class AlarsReleaseControlTask(Task):
    pass


@task("alars-bt")
class AlarsBTTask(Task):
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
    search_position: Annotated[GeoPoint, Column("SearchPosition")]

@task("alars-search")
class AlarsSearchTask(Task):
    search_position: Annotated[GeoPoint, Column("SearchPosition")]

@task("alars-recover")
class AlarsRecoverTask(Task):
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

@task("alars-follow-auv")
class AlarsFollowAUVTask(Task):
    follow_altitude: Annotated[float, Unit("m"), Column("FollowAltitude")] \
        = 15.0
    vulture_radius: Annotated[float, Unit("m"), Column("VultureRadius")] \
        = 0.0
    vulture_speed_deg: Annotated[float, Unit("°/s"), Column("VultureSpeedDeg")] \
        = 10.0
    timeout: Annotated[float, Unit("s"), Column("timeout")] \
        = 30



@task("alars-ping-search")
class AlarsPingSearch(Task):
    modem_to_ping: Annotated[int, Column("ModemToPing")] \
        = 111
    modem_depth: Annotated[float, Unit("m"), Column("ModemDepth")] \
        = 0.0
    dipping_altitude: Annotated[float, Unit("m"), Column("DippingAltitude")] \
        = 0.0
    max_pings: Annotated[int, Column("MaxPings")] \
        = 5
    waypoints: Annotated[list[GeoPoint], Column("Waypoints")] \
        = field(default_factory = list)



@task("deploy")
class DeployPayloadTask(Task):
    unit: Annotated[str, Column("Payload")] \
        = ""

@task("deploy-at")
class DeployPayloadAtTask(Task):
    #: Speed as specified in WARA-PS
    speed: Annotated[MovementSpeedParam, Column("Speed")] \
        = MovementSpeedParam.STANDARD
    unit: Annotated[str, Column("Payload")] \
        = ""
    waypoint: Annotated[GeoPoint, Column("Waypoint")]


# Succorfish stuff
@task("smarc-modem-ping")
class SmarcModemPingTask(Task):
    # one of: add, remove, clear, ping
    mode: Annotated[SuccorModeParam, Column("Mode")] \
        = SuccorModeParam.PING
    modem_id: Annotated[int, Column("ModemID")] \
        = 222
    depth_m: Annotated[float, Unit("m"), Column("Depth")] \
        = 0.0
    retry_count: Annotated[int, Column("RetryCount")] \
        = 3
    task_timeout_s: Annotated[float, Unit("s"), Column("TaskTimeout")] \
        = 30

@task("smarc-stop-modem-ping")
class SmarcStopModemPingTask(Task):
    pass

@task("search-area")
class SearchAreaTask(Task):
    #: Speed as specified in WARA-PS
    speed: Annotated[MovementSpeedParam, Column("Speed")] \
        = MovementSpeedParam.STANDARD
    # TODO: enum?
    spacing: Annotated[float, Unit("m"), Column("Spacing")] \
        = 0.0
    area_type: Annotated[AreaTypeParam, Column("Area type")] \
            = AreaTypeParam.WATER
    target_type: Annotated[str, Column("Target type")] \
        = "Default"
    target_size: Annotated[float, Column("Target size")] \
        = 0.0
    area: Annotated[list[GeoPoint], Column("Area")] \
        = field(default_factory = list)
