from pathlib import Path

from src.domain.missionplan import MissionPlan, TaskGroup
from src.domain.tasks import MovePathTask
from src.mission.MissionContext import MissionContext
from src.mission.MissionDocument import MissionDocument
from src.ui.widgets.MissionPlanWidget import MissionPlanWidget


def test_the_task_list_shows_the_plan(qgis_app, tmp_path: Path):
    plan = MissionPlan(
        name="seq",
        description="out and back",
        tasks=[MovePathTask(description="go out")],
    )
    doc = MissionDocument(plan, tmp_path / "mission.json")
    widget = MissionPlanWidget(MissionContext())
    widget.onActiveMissionChanged(doc)
    widget.show()
    qgis_app.processEvents()

    model = widget.taskListModel
    root = model.index(0, 0)
    assert model.data(root) == "out and back"
    assert model.data(model.index(0, 1)) == "seq"
    child = model.index(0, 0, root)
    assert model.data(child) == "go out"
    assert model.data(model.index(0, 1, root)) == "move-path"
    assert widget.ui.taskList.isVisible()


def test_a_concurrent_group_nests_under_the_sequence(qgis_app, tmp_path: Path):
    together = TaskGroup(
        kind="conc",
        description="together",
        children=[
            MovePathTask(description="left"),
            MovePathTask(description="right"),
        ],
    )
    plan = MissionPlan(
        name="seq",
        description="out and back",
        tasks=[MovePathTask(description="go out"), together],
    )
    sent = plan.toJson()
    assert sent["name"] == "seq"
    assert sent["children"][1]["name"] == "conc"
    assert [child["description"] for child in sent["children"][1]["children"]] == ["left", "right"]
    loaded = MissionPlan.fromJson(sent)
    assert loaded.leaves()[1].description == "left"

    doc = MissionDocument(loaded, tmp_path / "mission.json")
    widget = MissionPlanWidget(MissionContext())
    widget.onActiveMissionChanged(doc)
    widget.resize(640, 420)
    widget.ui.taskList.expandAll()
    widget.show()
    qgis_app.processEvents()
    widget.grab().save("/tmp/mission_plan_panel.png")

    root = widget.taskListModel.index(0, 0)
    assert widget.taskListModel.rowCount(root) == 2
    group = widget.taskListModel.index(1, 0, root)
    assert widget.taskListModel.data(group) == "together"
    assert widget.taskListModel.rowCount(group) == 2
    widget.ui.taskList.grab().save("/tmp/mission_tree.png")

    widget.ui.taskList.setCurrentIndex(group)
    qgis_app.processEvents()
    current = widget.taskListModel.node(widget.ui.taskList.currentIndex())
    assert getattr(current, "description", None) == "together"
    selected = widget.ui.taskList.selectionModel().selectedRows()
    labels = sorted(widget.taskListModel.data(index) for index in selected)
    assert labels == ["left", "right", "together"]

    widget.onAddGroup("seq")
    qgis_app.processEvents()
    root = widget.taskListModel.index(0, 0)
    group = widget.taskListModel.index(1, 0, root)
    assert widget.taskListModel.rowCount(group) == 3
    assert widget.taskListModel.data(widget.taskListModel.index(2, 1, group)) == "seq"


def test_a_map_click_task_lands_in_the_selected_group(qgis_app, tmp_path: Path):
    from uuid import uuid4

    from qgis.core import QgsPointXY

    from src.domain.tasks import MoveToTask, PendingWaypointTask
    from src.domain.waypoints import GeoPoint

    group = TaskGroup(kind="conc", description="together")
    plan = MissionPlan(name="seq", description="out", tasks=[group])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    pending = PendingWaypointTask(
        taskCls=MoveToTask,
        fieldName="waypoint",
        waypointCls=GeoPoint,
        description="there",
        taskUuid=uuid4(),
        waypointUuid=uuid4(),
        parentUuid=group.uuid,
    )
    doc.addPendingWaypointTask(pending, QgsPointXY(18.07, 59.35))
    assert doc.plan.tasks[0].children[0].description == "there"
    assert doc.plan.toJson()["children"][0]["children"][0]["name"] == "move-to"
