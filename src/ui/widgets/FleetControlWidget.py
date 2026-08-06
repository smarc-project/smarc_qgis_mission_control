from uuid import UUID

from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from qgis.PyQt.QtWidgets import QFrame, QWidget

from ...context.FleetState import FleetState
from ..generated.FleetControlWidgetUi import Ui_FleetControlWidget
from .VehicleCardWidget import VehicleCardWidget

# fmt: off
EMERGENCY_BUTTON_TIMEOUT             = 3000 # ms
EMERGENCY_BUTTON_CLICKS_REQUIRED     = 5
ABORT_MISSION_BUTTON_TIMEOUT         = 3000 # ms
ABORT_MISSION_BUTTON_CLICKS_REQUIRED = 3
# fmt: on


class FleetControlWidget(QFrame):
    uploadMissionPlanRequested = pyqtSignal(set)
    skipTaskRequested = pyqtSignal(dict) # dict[str, UUID]: vehicleTopic → first task UUID
    pauseRequested = pyqtSignal(set)
    continueRequested = pyqtSignal(set)
    abortMissionRequested = pyqtSignal(set)
    emergencyRequested = pyqtSignal(set)
    resetEmergencyRequested = pyqtSignal(set)
    clearTracksRequested = pyqtSignal()

    def __init__(self, fleetState: FleetState, mapManager, parent: QWidget | None = None):
        super().__init__(parent)

        self._fleetState = fleetState
        self._mapManager = mapManager

        self._selected: set[str] = set()
        self._collapsed: set[str] = set()
        self._vehicles: dict[str, VehicleCardWidget] = {}
        self._emergencyClickCounter = 0
        self._abortMissionClickCounter = 0

        self.ui = Ui_FleetControlWidget()
        self.ui.setupUi(self)
        self.setupUi2()

        self._fleetState.vehicleDiscovered.connect(self.addVehicle)
        self._fleetState.vehicleUpdated.connect(self.onVehicleUpdated)
        self._fleetState.vehicleExpired.connect(self.onVehicleExpired)

        self._emergencyButtonTimer = QTimer(self)
        self._emergencyButtonTimer.setSingleShot(True)
        self._emergencyButtonTimer.setInterval(EMERGENCY_BUTTON_TIMEOUT)
        self._emergencyButtonTimer.timeout.connect(self._resetEmergencyClickCount)

        self._abortMissionButtonTimer = QTimer(self)
        self._abortMissionButtonTimer.setSingleShot(True)
        self._abortMissionButtonTimer.setInterval(ABORT_MISSION_BUTTON_TIMEOUT)
        self._abortMissionButtonTimer.timeout.connect(self._resetAbortMissionClickCount)

    def setupUi2(self):
        # Align items in the scroll area to the top
        self.ui.vehicleListVLayout.setAlignment(Qt.AlignTop)

        # Keep backgrounds default, unfilled color
        self.ui.vehicleListScrollArea.viewport().setAutoFillBackground(False)
        self.ui.vehicleListScrollArea.widget().setAutoFillBackground(False)

        # Helper buttons
        self.ui.selectAllButton.clicked.connect(self.selectAll)
        self.ui.deselectAllButton.clicked.connect(self.deselectAll)
        self.ui.clearTracksButton.clicked.connect(self.onClearTracksClicked)
        self.ui.collapseAllButton.clicked.connect(self.collapseAll)
        self.ui.expandAllButton.clicked.connect(self.expandAll)

        # Vehicle controls
        self.ui.uploadMissionPlanButton.clicked.connect(self.onUploadMissionPlanClicked)
        self.ui.skipTaskButton.clicked.connect(self.onSkipTaskClicked)
        self.ui.pauseButton.clicked.connect(self.onPauseClicked)
        self.ui.continueButton.clicked.connect(self.onContinueClicked)
        self.ui.abortMissionButton.clicked.connect(self.onAbortMissionButtonClicked)
        self.ui.emergencyButton.clicked.connect(self.onEmergencyButtonClicked)
        self.ui.resetEmergencyButton.clicked.connect(self.onResetEmergencyButtonClicked)

        # Heartbeat
        self._fleetState.vehicleHeartbeat.connect(self.onVehicleHeartbeat)

        # By default, keep Vehicle Control disabled
        self.ui.vehicleControls.setEnabled(False)

        self._refreshUiState()

    def selectAll(self):
        for vehicle in self._vehicles.values():
            vehicle.setChecked(True)

    def deselectAll(self):
        for vehicle in self._vehicles.values():
            vehicle.setChecked(False)

    def collapseAll(self):
        for vehicle in self._vehicles.values():
            vehicle.setCollapsed(True)

    def expandAll(self):
        for vehicle in self._vehicles.values():
            vehicle.setCollapsed(False)

    def onVehicleToggled(self, vehicle: str, value: bool):
        print("FleetControlWidget.onVehicleToggled() called")
        print(value)

        if value:
            self._selected.add(vehicle)
        else:
            self._selected.discard(vehicle)

        self._refreshUiState()

    def onVehicleCollapsedChanged(self, vehicle: str, value: bool):
        if value:
            self._collapsed.add(vehicle)
        else:
            self._collapsed.discard(vehicle)

        self._refreshUiState()

    def _refreshUiState(self):
        if len(self._vehicles) == 0:
            # nothing is enabled if no cards are available
            self.ui.selectAllButton.setEnabled(False)
            self.ui.deselectAllButton.setEnabled(False)
            self.ui.collapseAllButton.setEnabled(False)
            self.ui.expandAllButton.setEnabled(False)
            self.ui.clearTracksButton.setEnabled(False)
            self.ui.vehicleControls.setEnabled(False)
            self.ui.vehiclesSelectedLabel.setText("No vehicles selected")
        else:
            allSelected = len(self._selected) == len(self._vehicles)
            someSelected = len(self._selected) != 0
            allCollapsed = len(self._collapsed) == len(self._vehicles)
            someCollapsed = len(self._collapsed) != 0

            self.ui.selectAllButton.setEnabled(not allSelected)
            self.ui.deselectAllButton.setEnabled(someSelected)

            self.ui.collapseAllButton.setEnabled(not allCollapsed)
            self.ui.expandAllButton.setEnabled(someCollapsed)

            self.ui.vehicleControls.setEnabled(someSelected)
            if allSelected:
                text = f"All ({len(self._selected)}) vehicles selected"
            elif len(self._selected) > 1:
                text = f"{len(self._selected)} vehicles selected"
            elif len(self._selected) == 1:
                text = "1 vehicle selected"
            else:
                text = "No vehicles selected"
            self.ui.vehiclesSelectedLabel.setText(text)

            self.ui.clearTracksButton.setEnabled(True)

    @pyqtSlot()
    def onUploadMissionPlanClicked(self):
        self.uploadMissionPlanRequested.emit(self._selected)

    @pyqtSlot()
    def onSkipTaskClicked(self):
        targets: dict[str, UUID] = {}
        for vehicleTopic in self._selected:
            state = self._fleetState.vehicleState(vehicleTopic)
            if state is not None and state.executingTasks: # send skipTask signal only if task(s) running
                targets[vehicleTopic] = state.executingTasks[0].uuid
        if targets:
            self.skipTaskRequested.emit(targets)

    @pyqtSlot()
    def onPauseClicked(self):
        self.pauseRequested.emit(self._selected)

    @pyqtSlot()
    def onContinueClicked(self):
        self.continueRequested.emit(self._selected)

    @pyqtSlot()
    def onEmergencyButtonClicked(self):
        self._emergencyClickCounter += 1
        if self._emergencyClickCounter >= EMERGENCY_BUTTON_CLICKS_REQUIRED:
            self.emergencyRequested.emit(self._selected)
            self._resetEmergencyClickCount()
        else:
            x = EMERGENCY_BUTTON_CLICKS_REQUIRED - self._emergencyClickCounter
            self.ui.emergencyButton.setText(f"EMERGENCY ({x})")
            self._emergencyButtonTimer.start()

    @pyqtSlot()
    def onAbortMissionButtonClicked(self):
        self._abortMissionClickCounter += 1
        if self._abortMissionClickCounter >= ABORT_MISSION_BUTTON_CLICKS_REQUIRED:
            self.abortMissionRequested.emit(self._selected)
            self._resetAbortMissionClickCount()
        else:
            x = ABORT_MISSION_BUTTON_CLICKS_REQUIRED - self._abortMissionClickCounter
            self.ui.abortMissionButton.setText(f"Abort Mission ({x})")
            self._abortMissionButtonTimer.start()

    @pyqtSlot()
    def onResetEmergencyButtonClicked(self):
        self.resetEmergencyRequested.emit(self._selected)

    def _resetEmergencyClickCount(self):
        self._emergencyButtonTimer.stop()
        self._emergencyClickCounter = 0
        self.ui.emergencyButton.setText("EMERGENCY")

    def _resetAbortMissionClickCount(self):
        self._abortMissionButtonTimer.stop()
        self._abortMissionClickCounter = 0
        self.ui.abortMissionButton.setText("Abort Mission")

    def addVehicle(self, vehicle: str, tasks = []):
        print("FleetControlWidget.addVehicle() called")

        card = VehicleCardWidget(vehicle, tasks, self.ui.vehicleList)
        card.setProperty("odd", bool(len(self._vehicles) % 2))
        card.toggled.connect(lambda v: self.onVehicleToggled(vehicle, v))
        card.collapsedChanged.connect(
            lambda v: self.onVehicleCollapsedChanged(vehicle, v)
        )

        # lookAt connection
        card.lookAtRequested.connect(self._mapManager.onLookAtRequested)

        self.ui.vehicleListVLayout.addWidget(card)
        self._vehicles[vehicle] = card

        # Sync collapsed state with what the card initializes to
        if card.isCollapsed():
            self._collapsed.add(vehicle)
        else:
            self._collapsed.discard(vehicle)

        self._refreshUiState()

    @pyqtSlot(str)
    def onVehicleUpdated(self, vehicleTopic: str):
        state = self._fleetState.vehicleState(vehicleTopic)
        assert(state)
        self._vehicles[vehicleTopic].updateState(state)

    @pyqtSlot(str)
    def onVehicleExpired(self, vehicleTopic: str):
        ...

    @pyqtSlot(str)
    def onVehicleHeartbeat(self, vehicleTopic: str):
        if vehicleTopic in self._vehicles:
            self._vehicles[vehicleTopic].onHeartbeat()

    @pyqtSlot()
    def onClearTracksClicked(self):
        self.clearTracksRequested.emit()
