from pathlib import Path

from qgis.core import QgsApplication
from qgis.gui import QgsDockWidget
from qgis.utils import iface

from qgis.PyQt.QtCore import QCoreApplication, pyqtSlot
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

from ...context.FleetContext import FleetContext
from ...domain.missionplan import MissionPlan
from ...mission.MissionContext import MissionContext
from ...mission.MissionDocument import MissionDocument
from ..generated.MissionControlDockWidgetUi import Ui_MissionControlDockWidget
from .FleetControlWidget import FleetControlWidget
from .LiveViewWidget import LiveViewWidget
from .MissionPlanWidget import MissionPlanWidget


class MissionControlDockWidget(QgsDockWidget):
    def __init__(self, missionContext: MissionContext, fleetContext: FleetContext,
                 parent: QWidget | None = None):
        super().__init__(parent)

        self._missionContext = missionContext
        self._fleetContext = fleetContext

        self.ui = Ui_MissionControlDockWidget()
        self.ui.setupUi(self)
        self.setup()

    def setup(self):
        # Setup tabs
        self.ui.tabMissionPlan = MissionPlanWidget(
            self._missionContext,
            self.ui.tabWidget
        )
        self.ui.tabMissionPlan.taskSelectionChanged.connect(
            self._missionContext.onTaskSelectionChanged
        )
        self.ui.tabWidget.addTab(self.ui.tabMissionPlan, "")

        self.ui.tabFleetControl = FleetControlWidget(
            self._fleetContext.state,
            self._fleetContext.mapManager, # for having access to FleetMapManager.onLookAtRequest() from FleetControlWidget
            self.ui.tabWidget
        )
        self.ui.tabFleetControl.uploadMissionPlanRequested.connect(self.onUploadMissionPlanRequested)
        self.ui.tabFleetControl.sendMissionPlanRequested.connect(self.onSendMissionPlanRequested)
        self._fleetContext.mqtt.commandRefused.connect(self.onCommandRefused)
        self.ui.tabFleetControl.abortTasksRequested.connect(
            self._fleetContext.mqtt.onAbortTasksSignal
        )
        self.ui.tabFleetControl.skipTaskRequested.connect(
            self._fleetContext.mqtt.onSkipTaskSignal
        )

        self.ui.tabFleetControl.abortMissionRequested.connect(
            self._fleetContext.mqtt.onAbortMissionSignal
        )
        self.ui.tabFleetControl.emergencyRequested.connect(
            self._fleetContext.mqtt.onEmergencySignal
        )
        self.ui.tabFleetControl.resetEmergencyRequested.connect(
            self._fleetContext.mqtt.onResetEmergencySignal
        )
        self.ui.tabWidget.addTab(self.ui.tabFleetControl, "")

        self.ui.tabLiveView = LiveViewWidget(
            self._fleetContext,
            self.ui.tabWidget
        )
        self.ui.tabWidget.addTab(self.ui.tabLiveView, "")

        # Setup mission plan context
        self._missionContext.firstMissionLoaded.connect(self.onFirstMissionLoaded)
        self._missionContext.missionLoaded.connect(self.onMissionLoaded)
        self._missionContext.activeMissionChanged.connect(
            self.ui.tabMissionPlan.onActiveMissionChanged
        )
        # self._missionContext.loadMissionPlanFromFile(
        #     '/opt/workspace/references/mission-plans/seq-go_out_and_loiter.json'
        # )
        # self._missionContext.loadMissionPlanFromFile(
        #     '/opt/workspace/references/mission-plans/seq-AllTasks.json'
        # )

        # Setup clearTracks signal from FleetControlWidget to FleetContext.mapManager
        self.ui.tabFleetControl.clearTracksRequested.connect(
            self.ui.tabLiveView.clearTracks
        )

        # Setup mission plan controls
        self.ui.buttonEditMissionPlan.setIcon(
            QgsApplication.getThemeIcon("mActionToggleEditing.svg")
        )
        self.ui.buttonNewMissionPlan.setIcon(
            QgsApplication.getThemeIcon("mActionFileNew.svg")
        )
        self.ui.buttonOpenMissionPlan.setIcon(
            QgsApplication.getThemeIcon("mActionFileOpen.svg")
        )
        self.ui.buttonSaveMissionPlan.setIcon(
            QgsApplication.getThemeIcon("mActionFileSave.svg")
        )
        self.ui.buttonSaveMissionPlanAs.setIcon(
            QgsApplication.getThemeIcon("mActionFileSaveAs.svg")
        )

        self.ui.buttonEditMissionPlan.toggled.connect(
            self.onEditMissionPlanButtonToggled
        )
        self._missionContext.editModeChanged.connect(self.onEditModeChanged)

        self.ui.buttonNewMissionPlan.clicked.connect(self.onNewMissionPlan)
        self.ui.buttonOpenMissionPlan.clicked.connect(self.onOpenMissionPlan)
        self.ui.buttonSaveMissionPlan.clicked.connect(self.onSaveMissionPlan)
        # self.ui.buttonSaveMissionPlanAs.clicked.connect(self.onSaveMissionPlanAs)

        self.ui.missionPlanComboBox.currentIndexChanged.connect(
            lambda index: self._missionContext.changeActiveMission(
                    self.ui.missionPlanComboBox.itemData(index)
                )
        )

        self.retranslateUi2()

    def retranslateUi2(self):
        _translate = QCoreApplication.translate
        self.ui.tabWidget.setTabText(
            self.ui.tabWidget.indexOf(self.ui.tabMissionPlan),
            _translate("MissionControlDockWidget", "Mission Pla&n"),
        )
        self.ui.tabWidget.setTabText(
            self.ui.tabWidget.indexOf(self.ui.tabFleetControl),
            _translate("MissionControlDockWidget", "&Fleet Control"),
        )
        self.ui.tabWidget.setTabText(
            self.ui.tabWidget.indexOf(self.ui.tabLiveView),
            _translate("MissionControlDockWidget", "L&ive View"),
        )

    @pyqtSlot(int)
    def onSelectedMissionPlanChanged(self, index: int):
        self._missionContext.setActiveMissionPlan(index)

    @pyqtSlot(MissionDocument)
    def onFirstMissionLoaded(self, doc: MissionDocument):
        # Enable controls that require at least one mission plan to be loaded
        self.ui.missionPlanComboBox.setEnabled(True)
        self.ui.buttonEditMissionPlan.setEnabled(True)
        self.ui.buttonSaveMissionPlan.setEnabled(True)
        # self.ui.buttonSaveMissionPlanAs.setEnabled(True)

    @pyqtSlot(MissionDocument)
    def onMissionLoaded(self, doc: MissionDocument):
        # TODO: filename as name in combo box
        self.ui.missionPlanComboBox.addItem(doc.path.stem, doc.plan.uuid)
        index = self.ui.missionPlanComboBox.count() - 1
        self.ui.missionPlanComboBox.setCurrentIndex(index)

    @pyqtSlot(bool)
    def onEditMissionPlanButtonToggled(self, state: bool):
        doc = self._missionContext.activeDocument()
        if doc is None:
            return

        if state is True:
            # Start editing
            doc.startEditing()
        else:
            # Make sure any pending input field changes are properly recognized
            self._missionContext.prepareToFinishEditing()

            if doc.isModified():
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Question)
                box.setWindowTitle("Mission plan modified")
                box.setText("Commit changes to mission plan?")

                commitButton = box.addButton("Commit", QMessageBox.AcceptRole)
                discardButton = box.addButton(QMessageBox.Discard)
                cancelButton = box.addButton(QMessageBox.Cancel)

                box.setDefaultButton(commitButton)

                box.exec()
                reply = box.clickedButton()

                if reply is commitButton:
                    doc.stopEditing(commit = True)
                elif reply is discardButton:
                    doc.stopEditing(commit = False)
                else:
                    # User changed their mind, restore button state
                    self.ui.buttonEditMissionPlan.setChecked(True)
                    return
            else:
                # No changes anyways
                doc.stopEditing(commit = False)

    @pyqtSlot(bool)
    def onEditModeChanged(self, editMode: bool):
        self.ui.missionPlanComboBox.setDisabled(editMode)
        self.ui.fileButtons.setDisabled(editMode)

    @pyqtSlot()
    def onNewMissionPlan(self):
        dialog = QFileDialog(self, "New Mission Plan")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix(".json")
        dialog.setMimeTypeFilters(["application/json", "application/octet-stream"])
        dialog.setModal(True)
        if dialog.exec() != QDialog.Accepted:
            return

        for file in dialog.selectedFiles():
            name = Path(file).stem
            self._missionContext.newMission(name, file)

    @pyqtSlot()
    def onOpenMissionPlan(self):
        dialog = QFileDialog(self, "Open Mission Plan")
        dialog.setOption(QFileDialog.Option.ReadOnly)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setMimeTypeFilters(["application/json", "application/octet-stream"])
        dialog.setModal(True)
        if dialog.exec() != QDialog.Accepted:
            return

        for file in dialog.selectedFiles():
            self._missionContext.loadMissionFromFile(file)

    @pyqtSlot(set)
    def onUploadMissionPlanRequested(self, receivers: set[str]) -> None:
        doc = self._missionContext.activeDocument()
        if doc is None:
            iface.messageBar().pushWarning(None, "No mission plan is open; nothing was sent.")
            return
        if self._refuseIncompletePlan(doc.plan):
            return
        # A complete plan can still be refused per vehicle, while one of its action
        # servers runs another task; the fleet tab checks that and asks to send.
        self.ui.tabFleetControl.sendPlanUnlessServerBusy(doc.plan, receivers)

    @pyqtSlot(MissionPlan, set)
    def onSendMissionPlanRequested(self, plan: MissionPlan, receivers: set[str]) -> None:
        # Checked again: a plan held back by Override can be edited while it waits.
        if self._refuseIncompletePlan(plan):
            return
        self._fleetContext.mqtt.onPublishMissionPlan(plan, receivers)

    def _refuseIncompletePlan(self, plan: MissionPlan) -> bool:
        """True, with the reason in the message bar, if the officer would refuse the plan."""
        # The officer refuses a TST with an empty seq or conc anywhere, as a plan that was
        # sent before it was finished, so such a plan is not sent at all.
        if not plan.tasks:
            iface.messageBar().pushWarning(None, "The mission plan has no tasks; nothing was sent.")
            return True
        empty = plan.empty_groups()
        if empty:
            names = ", ".join(f'"{group.description}"' for group in empty)
            iface.messageBar().pushWarning(None, f"Empty group {names} in the mission plan; nothing was sent.")
            return True
        return False

    @pyqtSlot(str, str, str)
    def onCommandRefused(self, vehicleTopic: str, refusedWhat: str, reason: str) -> None:
        # Refusals the plugin cannot predict, e.g. a mission it cannot see is still running.
        vehicleName = vehicleTopic.split('/')[-1]
        iface.messageBar().pushWarning(None, f"{vehicleName} refused {refusedWhat}: {reason}")

    @pyqtSlot()
    def onSaveMissionPlan(self):
        self._missionContext.saveMission()
        iface.messageBar().pushSuccess(None, "Mission plan saved")
