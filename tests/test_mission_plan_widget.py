from pathlib import Path

from qgis.gui import QgsMapCanvas, QgsMapTool

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

from src.domain.missionplan import GroupKind, MissionPlan, TaskGroup
from src.domain.tasks import MovePathTask
from src.mission.MissionContext import MissionContext
from src.mission.MissionDocument import MissionDocument
from src.ui.widgets.MissionPlanWidget import MissionPlanWidget
from src.ui.widgets.WaypointTableWidget import WaypointTableWidget


def _open(plan: MissionPlan, tmp_path: Path) -> tuple[MissionPlanWidget, MissionDocument]:
    """Open the plan the way the dock does: from a file, through the context."""
    import json

    path = tmp_path / "mission.json"
    path.write_text(json.dumps(plan.toJson()))
    context = MissionContext()
    widget = MissionPlanWidget(context)
    context.activeMissionChanged.connect(widget.onActiveMissionChanged)
    context.loadMissionFromFile(path)
    context.changeActiveMission(plan.uuid)
    return widget, context.activeDocument()


def test_the_task_list_shows_the_plan(qgis_app, tmp_path: Path):
    plan = MissionPlan(
        name=GroupKind.SEQ.value,
        description="out and back",
        tasks=[MovePathTask(description="go out")],
    )
    widget, doc = _open(plan, tmp_path)
    widget.show()
    qgis_app.processEvents()

    model = widget.taskListModel
    root = model.index(0, 0)
    assert model.data(root) == "out and back"
    assert model.data(model.index(0, 1)) == "Sequence"
    child = model.index(0, 0, root)
    assert model.data(child) == "go out"
    assert model.data(model.index(0, 1, root)) == "move-path"
    assert widget.ui.taskList.isVisible()
    assert widget.ui.missionPlanTimeout.text() == "300.0"
    assert not widget.ui.taskListSidebar.isVisible()
    assert not widget.ui.taskEditorStack.isVisible()
    widget.ui.taskList.setCurrentIndex(child)
    qgis_app.processEvents()
    assert widget.ui.taskEditorStack.isVisible()
    # A dock about 520 px tall holds the panel. The tallest hidden editor must not count.
    assert widget.minimumSizeHint().height() <= 520


def test_a_concurrent_group_nests_under_the_sequence(qgis_app, tmp_path: Path):
    together = TaskGroup(
        kind=GroupKind.CONC,
        description="together",
        children=[
            MovePathTask(description="left"),
            MovePathTask(description="right"),
        ],
    )
    plan = MissionPlan(
        name=GroupKind.SEQ.value,
        description="out and back",
        tasks=[MovePathTask(description="go out"), together],
    )
    sent = plan.toJson()
    assert sent["name"] == "seq"
    assert sent["children"][1]["name"] == "conc"
    assert [child["description"] for child in sent["children"][1]["children"]] == ["left", "right"]
    loaded = MissionPlan.fromJson(sent)
    assert loaded.leaves()[1].description == "left"

    widget, doc = _open(loaded, tmp_path)
    widget.resize(480, 520)
    widget.ui.taskList.expandAll()
    widget.show()
    qgis_app.processEvents()

    root = widget.taskListModel.index(0, 0)
    assert widget.taskListModel.rowCount(root) == 2
    group = widget.taskListModel.index(1, 0, root)
    assert widget.taskListModel.data(group) == "together"
    assert widget.taskListModel.rowCount(group) == 2

    widget.ui.taskList.setCurrentIndex(group)
    qgis_app.processEvents()
    current = widget.taskListModel.node(widget.ui.taskList.currentIndex())
    assert current.description == "together"
    selected = widget.ui.taskList.selectionModel().selectedRows()
    labels = sorted(widget.taskListModel.data(index) for index in selected)
    assert labels == ["left", "right", "together"]
    assert widget.ui.missionPlanTimeout.text() == "300.0"

    doc.startEditing()
    widget.onAddGroup(GroupKind.SEQ)
    qgis_app.processEvents()
    root = widget.taskListModel.index(0, 0)
    group = widget.taskListModel.index(1, 0, root)
    assert widget.taskListModel.rowCount(group) == 3
    assert widget.taskListModel.data(widget.taskListModel.index(2, 1, group)) == "Sequence"


def test_a_map_click_task_lands_in_the_selected_group(qgis_app, tmp_path: Path):
    from uuid import uuid4

    from qgis.core import QgsPointXY

    from src.domain.tasks import MoveToTask, PendingWaypointTask
    from src.domain.waypoints import GeoPoint

    group = TaskGroup(kind=GroupKind.CONC, description="together")
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[group])
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


def _move_to(description: str):
    from uuid import uuid4

    from src.domain.tasks import MoveToTask
    from src.domain.waypoints import GeoPoint

    return MoveToTask(description=description, uuid=uuid4(),
                      waypoint=GeoPoint(latitude=59.35, longitude=18.07, uuid=uuid4()))


def test_deleting_the_only_waypoint_of_a_grouped_task_deletes_the_task(qgis_app, tmp_path: Path):
    task = _move_to("there")
    group = TaskGroup(kind=GroupKind.CONC, description="together", children=[task])
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[group])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    doc.startEditing()

    doc.deleteWaypoint(task.waypoint.uuid)

    assert group.children == []
    assert doc.layerBridge.featureIdForWaypointUuid(task.waypoint.uuid) is None


def _track_segments(doc: MissionDocument) -> int:
    return doc.layerBridge.tracks._layer.featureCount()


def test_deleting_a_group_takes_its_waypoints_and_undo_brings_them_back(qgis_app, tmp_path: Path):
    left, right = _move_to("left"), _move_to("right")
    group = TaskGroup(kind=GroupKind.CONC, description="together", children=[left, right])
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out",
                       tasks=[_move_to("before"), group, _move_to("after")])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    doc.startEditing()
    stack = doc.layerBridge.waypointLayer.undoStack()
    assert _track_segments(doc) == 3

    doc.deleteGroup(group)
    assert [task.description for task in plan.tasks] == ["before", "after"]
    assert _track_segments(doc) == 1
    for task in (left, right):
        assert doc.index.taskByUuid(task.uuid) is None
        assert doc.layerBridge.featureIdForWaypointUuid(task.waypoint.uuid) is None

    stack.undo()
    assert plan.tasks[1] is group and group.children == [left, right]
    assert _track_segments(doc) == 3
    for task in (left, right):
        assert doc.index.taskByUuid(task.uuid) is task
        assert doc.layerBridge.featureIdForWaypointUuid(task.waypoint.uuid) is not None

    stack.redo()
    assert _track_segments(doc) == 1


def test_the_rail_and_the_menu_only_work_in_edit_mode(qgis_app, tmp_path: Path):
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[])
    widget, doc = _open(plan, tmp_path)
    widget.show()
    qgis_app.processEvents()
    assert not widget.ui.taskListSidebar.isVisible()
    assert not widget.ui.missionPlanDescription.isEnabled()

    doc.startEditing()
    qgis_app.processEvents()
    assert widget.ui.taskListSidebar.isVisible()
    assert widget.ui.missionPlanDescription.isEnabled()


def test_renaming_a_task_in_the_tree_keeps_the_tree_open(qgis_app, tmp_path: Path):
    together = TaskGroup(kind=GroupKind.CONC, description="together",
                         children=[MovePathTask(description="left")])
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[together])
    widget, doc = _open(plan, tmp_path)
    widget.show()
    doc.startEditing()
    qgis_app.processEvents()
    model = widget.taskListModel
    group = model.index(0, 0, model.index(0, 0))
    left = model.index(0, 0, group)
    widget.ui.taskList.setCurrentIndex(left)

    assert not model.flags(group) & Qt.ItemIsEditable
    assert model.setData(left, "port")
    qgis_app.processEvents()

    assert doc.plan.tasks[0].children[0].description == "port"
    assert widget.ui.taskList.isExpanded(group)
    assert model.node(widget.ui.taskList.currentIndex()).description == "port"


def _path(description: str, latitude: float) -> MovePathTask:
    from uuid import uuid4

    from src.domain.waypoints import GeoPoint

    return MovePathTask(description=description, uuid=uuid4(), waypoints=[
        GeoPoint(latitude=latitude + step, longitude=18.07, uuid=uuid4()) for step in (0.0, 0.01, 0.02)])


def _editing_first_path(qgis_app, tmp_path: Path) -> tuple[
        MissionPlanWidget, MissionDocument, QgsMapCanvas, QgsMapTool, WaypointTableWidget]:
    """Two paths and two move-tos, in edit mode, the first path's editor shown, the user on Pan."""
    import qgis.utils
    from qgis.gui import QgsMapToolPan

    plan = MissionPlan(name=GroupKind.SEQ.value, description="out",
                       tasks=[_path("first", 59.30), _path("second", 59.40),
                              _move_to("there"), _move_to("there too")])
    widget, doc = _open(plan, tmp_path)
    widget.show()
    doc.startEditing()
    canvas = qgis.utils.iface.mapCanvas()
    users_tool = QgsMapToolPan(canvas)
    canvas.setMapTool(users_tool)
    root = widget.taskListModel.index(0, 0)
    widget.ui.taskList.setCurrentIndex(widget.taskListModel.index(0, 0, root))
    qgis_app.processEvents()
    table = widget.taskEditors["move-path"].findChild(WaypointTableWidget)
    return widget, doc, canvas, users_tool, table


def _start_move(table: WaypointTableWidget) -> QAction:
    from qgis.PyQt.QtCore import QItemSelectionModel

    table.ui.waypointTable.selectionModel().select(
        table.ui.waypointTable.model().index(1, 0),
        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
    move = table.ui.buttonMoveWaypoint.defaultAction()
    move.setChecked(True)
    return move


def test_selecting_another_path_stops_the_tool(qgis_app, tmp_path: Path):
    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    action = _start_move(table)
    assert canvas.mapTool() is not users_tool
    root = widget.taskListModel.index(0, 0)

    widget.ui.taskList.setCurrentIndex(widget.taskListModel.index(1, 0, root))

    assert not action.isChecked()
    assert canvas.mapTool() is users_tool


def test_selecting_a_task_of_another_type_stops_the_tool(qgis_app, tmp_path: Path):
    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    action = _start_move(table)
    root = widget.taskListModel.index(0, 0)

    widget.ui.taskList.setCurrentIndex(widget.taskListModel.index(2, 0, root))

    # The path's editor is hidden now. Its tool must not keep editing that path.
    assert not action.isChecked()
    assert canvas.mapTool() is users_tool


def test_adding_a_task_stops_the_tool(qgis_app, tmp_path: Path):
    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    action = _start_move(table)

    doc.addTask("smarc-wait", "pause")

    assert not action.isChecked()
    assert canvas.mapTool() is users_tool


def test_adding_a_map_click_task_stops_the_tool_and_then_hands_the_map_back(qgis_app, tmp_path: Path):
    from qgis.core import QgsPointXY

    from src.mission.MissionMapManager import PickInitialWaypointTool

    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    action = _start_move(table)

    doc.addTask("move-to", "here")

    assert not action.isChecked()
    assert isinstance(canvas.mapTool(), PickInitialWaypointTool)
    doc.parent().mapManager.onPickInitialWaypointToolMapClicked(QgsPointXY(18.1, 59.5), Qt.LeftButton)
    assert doc.plan.tasks[-1].description == "here"
    assert not action.isChecked()
    assert canvas.mapTool() is users_tool


def _start_add(table: WaypointTableWidget) -> QAction:
    add = table.ui.buttonAddWaypoint.defaultAction()
    add.setChecked(True)
    return add


def test_selecting_another_path_stops_add_waypoint(qgis_app, tmp_path: Path):
    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    add = _start_add(table)
    assert canvas.mapTool() is not users_tool
    root = widget.taskListModel.index(0, 0)

    widget.ui.taskList.setCurrentIndex(widget.taskListModel.index(1, 0, root))

    # Left on, the next click would add a waypoint to the path no longer shown.
    assert not add.isChecked()
    assert canvas.mapTool() is users_tool


def test_selecting_another_move_to_stops_select_location(qgis_app, tmp_path: Path):
    from src.ui.widgets.WaypointFormWidget import WaypointFormWidget

    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    root = widget.taskListModel.index(0, 0)
    widget.ui.taskList.setCurrentIndex(widget.taskListModel.index(2, 0, root))
    form = widget.taskEditors["move-to"].findChild(WaypointFormWidget)
    selectLocation = form.ui.buttonSelectLocation.defaultAction()
    selectLocation.setChecked(True)
    assert canvas.mapTool() is not users_tool

    widget.ui.taskList.setCurrentIndex(widget.taskListModel.index(3, 0, root))

    assert not selectLocation.isChecked()
    assert canvas.mapTool() is users_tool


def test_leaving_edit_mode_stops_add_waypoint_and_select_location(qgis_app, tmp_path: Path):
    from src.ui.widgets.WaypointFormWidget import WaypointFormWidget

    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    add = _start_add(table)
    form = widget.taskEditors["move-to"].findChild(WaypointFormWidget)

    doc.stopEditing(False)
    assert not add.isChecked()
    assert canvas.mapTool() is users_tool

    doc.startEditing()
    root = widget.taskListModel.index(0, 0)
    widget.ui.taskList.setCurrentIndex(widget.taskListModel.index(2, 0, root))
    selectLocation = form.ui.buttonSelectLocation.defaultAction()
    selectLocation.setChecked(True)
    doc.stopEditing(False)
    assert not selectLocation.isChecked()
    assert canvas.mapTool() is users_tool


def test_stopping_a_tool_after_the_users_tool_was_deleted_leaves_the_canvas_empty(qgis_app, tmp_path: Path):
    from qgis.core import QgsPointXY

    from qgis.PyQt import sip

    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    move = _start_move(table)
    sip.delete(users_tool)

    # Right-click, called directly: an error raised inside a Qt slot would only be printed.
    doc.parent().mapManager.onSelectLocationToolMapClicked(QgsPointXY(18.0, 59.0), Qt.RightButton)

    assert not move.isChecked()
    assert canvas.mapTool() is None


def test_adding_a_path_while_add_waypoint_is_on_puts_the_next_waypoints_in_the_new_path(qgis_app, tmp_path: Path):
    """Clemens's #120: after adding a path, map clicks still added waypoints to the previous one."""
    from qgis.core import QgsPointXY

    widget, doc, canvas, users_tool, table = _editing_first_path(qgis_app, tmp_path)
    first = doc.plan.leaves()[0]
    first_count = len(first.waypoints)
    add = _start_add(table)

    doc.addTask("move-path", "new path")
    qgis_app.processEvents()

    # The old path's tool is off, so a click does not edit the old path.
    assert not add.isChecked()
    assert canvas.mapTool() is users_tool
    # The editor now shows the new path; its Add Waypoint adds there.
    new_path = doc.plan.leaves()[-1]
    assert new_path.description == "new path"
    _start_add(table)
    doc.parent().mapManager.onAddWaypointToolMapClicked(QgsPointXY(18.1, 59.5), Qt.LeftButton)
    assert len(first.waypoints) == first_count
    assert len(new_path.waypoints) == 1
