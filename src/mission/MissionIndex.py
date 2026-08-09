from dataclasses import dataclass, field
from uuid import UUID

from ..domain.missionplan import MissionPlan
from ..domain.tasks import Task
from ..domain.taskspatial import iterTaskWaypoints
from ..domain.waypoints import Waypoint


@dataclass
class MissionIndex:
    plan: MissionPlan
    waypointMap: dict[UUID, Waypoint] = field(default_factory=dict)
    taskMap: dict[UUID, Task] = field(default_factory=dict)
    waypointTaskMap: dict[UUID, UUID] = field(default_factory=dict)

    @classmethod
    def fromMissionPlan(cls, plan: MissionPlan) -> 'MissionIndex':
        index = cls(plan)
        for task in plan.tasks:
            index.registerTask(task)

        return index

    def waypointByUuid(self, waypointUuid: UUID) -> Waypoint | None:
        return self.waypointMap.get(waypointUuid)

    def taskByUuid(self, taskUuid: UUID) -> Task | None:
        return self.taskMap.get(taskUuid)

    def taskUuidByWaypointUuid(self, waypointUuid: UUID) -> UUID | None:
        return self.waypointTaskMap.get(waypointUuid)

    def taskByWaypointUuid(self, waypointUuid: UUID) -> Task | None:
        taskUuid = self.waypointTaskMap.get(waypointUuid)
        if taskUuid is None:
            return None

        return self.taskMap.get(taskUuid)

    def registerTask(self, task: Task):
        self.taskMap[task.uuid] = task
        for waypoint in iterTaskWaypoints(task):
            self.waypointMap[waypoint.uuid] = waypoint
            self.waypointTaskMap[waypoint.uuid] = task.uuid

    def forgetTask(self, taskUuid: UUID):
        task = self.taskByUuid(taskUuid)
        if task is None:
            # TODO: invalid mapping
            return

        for waypoint in iterTaskWaypoints(task):
            del self.waypointMap[waypoint.uuid]
            del self.waypointTaskMap[waypoint.uuid]

        del self.taskMap[taskUuid]

    def registerWaypoint(self, taskUuid: UUID, waypoint: Waypoint):
        task = self.taskByUuid(taskUuid)
        if task is None:
            # TODO: invalid mapping
            return

        self.waypointMap[waypoint.uuid] = waypoint
        self.waypointTaskMap[waypoint.uuid] = taskUuid

    def forgetWaypoint(self, waypointUuid: UUID):
        task = self.taskByWaypointUuid(waypointUuid)
        if task is None:
            # TODO: invalid mapping
            return

        del self.waypointMap[waypointUuid]
        del self.waypointTaskMap[waypointUuid]

    def previousWaypointByUuid(self, waypointUuid: UUID) -> Waypoint | None:
        task = self.taskByWaypointUuid(waypointUuid)
        waypoint = self.waypointByUuid(waypointUuid)
        if not all((task, waypoint)):
            # TODO: invalid mapping
            return None

        waypoints = list(iterTaskWaypoints(task))
        index = waypoints.index(waypoint)

        if index == 0:
            # Previous on a previous task
            taskIndex = self.plan.tasks.index(task)
            taskIndex -= 1
            while taskIndex >= 0:
                task = self.plan.tasks[taskIndex]
                waypoints = list(iterTaskWaypoints(task))
                if len(waypoints):
                    # Task has waypoints, last one is the one we are looking for
                    return waypoints[-1]
                taskIndex -= 1

            # No tasks before this one have waypoints
            return None
        else:
            # Previous waypoint on same task
            return waypoints[index - 1]

    def nextWaypointByUuid(self, waypointUuid: UUID) -> Waypoint | None:
        task = self.taskByWaypointUuid(waypointUuid)
        waypoint = self.waypointByUuid(waypointUuid)
        if not all((task, waypoint)):
            # TODO: invalid mapping
            return None

        waypoints = list(iterTaskWaypoints(task))
        index = waypoints.index(waypoint)

        if index == len(waypoints) - 1:
            # Next on a following task
            taskIndex = self.plan.tasks.index(task)
            taskIndex += 1
            while taskIndex < len(self.plan.tasks):
                task = self.plan.tasks[taskIndex]
                waypoints = list(iterTaskWaypoints(task))
                if len(waypoints):
                    # Task has waypoints, first one is the one we are looking for
                    return waypoints[0]
                taskIndex += 1

            # No tasks before this one have waypoints
            return None
        else:
            # Next waypoint on same task
            return waypoints[index + 1]
