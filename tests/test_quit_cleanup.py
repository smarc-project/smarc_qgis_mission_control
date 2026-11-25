import json
from pathlib import Path
from uuid import uuid4

from qgis.core import QgsProject

from src.domain.missionplan import MissionPlan
from src.domain.tasks import MovePathTask
from src.domain.waypoints import GeoPoint
from src.mission.MissionContext import MissionContext
from src.mission.MissionLayerBridge import MissionLayerBridge


def _plan(name: str) -> MissionPlan:
    task = MovePathTask(description="path", uuid=uuid4(), waypoints=[
        GeoPoint(latitude=59.3, longitude=18.07, uuid=uuid4())])
    return MissionPlan(name=name, description="", tasks=[task])


def _load(context: MissionContext, tmp_path: Path, name: str) -> None:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(_plan(name).toJson()))
    context.loadMissionFromFile(path)


def _smarcGroup():
    return QgsProject.instance().layerTreeRoot().findGroup(MissionLayerBridge.SMARC_GROUP_NAME)


def test_unloading_leaves_no_group_behind_for_qgis_to_trip_over(qgis_app, tmp_path: Path):
    # QGIS removes whatever is left in the layer tree after its layer panel is gone,
    # which crashed it on quit while the plugin's group was still there.
    context = MissionContext()
    _load(context, tmp_path, "one")
    _load(context, tmp_path, "two")
    assert _smarcGroup() is not None

    context.cleanup()

    assert _smarcGroup() is None
    assert QgsProject.instance().layerTreeRoot().children() == []


def test_unloading_after_qgis_closed_the_project_is_quiet(qgis_app, tmp_path: Path):
    # Project > Exit closes the project, deleting our groups, before the plugin unloads.
    context = MissionContext()
    _load(context, tmp_path, "one")
    QgsProject.instance().clear()

    context.cleanup()

    assert _smarcGroup() is None
