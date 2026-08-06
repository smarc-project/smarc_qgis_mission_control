from qgis.PyQt.QtCore import Qt, pyqtSlot
from qgis.PyQt.QtWidgets import QWidget

from ...context.FleetContext import FleetContext
from ..generated.LiveViewWidgetUi import Ui_LiveViewWidget
from .VehicleLiveViewWidget import VehicleLiveViewWidget


class LiveViewWidget(QWidget):
    _fleetContext: FleetContext
    _vehicles: dict[str, VehicleLiveViewWidget]

    def __init__(self, fleetContext: FleetContext,
                 parent: QWidget | None = None):
        super().__init__(parent)

        print("Initializing LiveViewWidget")
        
        self._fleetContext = fleetContext
        self._selected: set[str] = set()
        self._collapsed: set[str] = set()
        self._vehicles: dict[str, VehicleLiveViewWidget] = {}

        print(f"There are currently {self._vehicles} vehicles")

        self.ui = Ui_LiveViewWidget()
        self.ui.setupUi(self)
        self.setupUi2()

        self._fleetContext.state.vehicleDiscovered.connect(self.onVehicleDiscovered)
        self._fleetContext.state.vehicleUpdated.connect(self.onVehicleUpdated)
        self._fleetContext.state.vehicleExpired.connect(self.onVehicleExpired)
        self._fleetContext.state.vehicleHeartbeat.connect(self.onVehicleHeartbeat)
        
    def setupUi2(self):
        # Align items in the scroll area to the top
        self.ui.vehicleListVLayout.setAlignment(Qt.AlignTop)

        # Keep backgrounds default, unfilled color
        self.ui.vehicleListScrollArea.viewport().setAutoFillBackground(False)
        self.ui.vehicleListScrollArea.widget().setAutoFillBackground(False)

        # custom icons are currently implemented via qtdesigner -> resource file
        # custom icons can also be set here, instead of using qtdesigner
        # self.ui.selectAllButton.setIcon(
        #     QIcon(str(ICON_DIR / "collapse_all.svg"))
        # )

        # Helper buttons
        self.ui.selectAllButton.clicked.connect(self.selectAll)
        self.ui.deselectAllButton.clicked.connect(self.deselectAll)
        self.ui.clearTracksButton.clicked.connect(self.clearTracks)
        self.ui.collapseAllButton.clicked.connect(self.collapseAll)
        self.ui.expandAllButton.clicked.connect(self.expandAll)

        self._refreshUiState()

    def selectAll(self):
        print("Selecting all...")
        for vehicle in self._vehicles.values():
            print(self._vehicles.values())
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

    def clearTracks(self):
        print("Clearing tracks...")
        self._fleetContext.mapManager.clearAllVehicleMarkers()
        # for vehicle in self._vehicles.values():

    def onVehicleToggled(self, vehicle: str, value: bool):
        print("LiveViewWidget.onVehicleToggled() called")
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
        else:
            allSelected = len(self._selected) == len(self._vehicles)
            someSelected = len(self._selected) != 0
            allCollapsed = len(self._collapsed) == len(self._vehicles)
            someCollapsed = len(self._collapsed) != 0

            self.ui.selectAllButton.setEnabled(not allSelected)
            self.ui.deselectAllButton.setEnabled(someSelected)

            self.ui.collapseAllButton.setEnabled(not allCollapsed)
            self.ui.expandAllButton.setEnabled(someCollapsed)

            self.ui.clearTracksButton.setEnabled(True)

    @pyqtSlot(str)
    def onVehicleDiscovered(self, vehicleTopic: str):
        print("LiveViewWidget: vehicle discovered")
        print(f"Topic: {vehicleTopic}")

        if not vehicleTopic in self._vehicles:
            widget = VehicleLiveViewWidget(
                vehicleTopic,
                self.ui.vehicleList
            )

            # Set initial button color
            state = self._fleetContext.state.vehicleState(vehicleTopic)
            if state is not None:
                widget.ui.mapColorButton.setColor(state.mapColor)

            # Connect signals
            widget.mapColorChanged.connect(
                self._fleetContext.mapManager.onMapColorChanged
            )
            widget.showOnMapChanged.connect(
                self._fleetContext.mapManager.onShowOnMapChanged
            )
            widget.lookAtRequested.connect(
                self._fleetContext.mapManager.onLookAtRequested
            )
            widget.collapsedChanged.connect(
                self.onVehicleCollapsedChanged
            )
            widget.toggled.connect(
                self.onVehicleToggled
            )            

            self._vehicles[vehicleTopic] = widget
            self.ui.vehicleListVLayout.addWidget(widget)

            # Sync collapsed state with what the widget initializes to
            if widget.isCollapsed():
                self._collapsed.add(vehicleTopic)
            else:
                self._collapsed.discard(vehicleTopic)

            self._refreshUiState()

    @pyqtSlot(str)
    def onVehicleUpdated(self, vehicleTopic: str):
        state = self._fleetContext.state.vehicleState(vehicleTopic)
        assert(state)
        self._vehicles[vehicleTopic].updateState(state)

    @pyqtSlot(str)
    def onVehicleExpired(self, vehicleTopic: str):
        ...

    @pyqtSlot(str)
    def onVehicleHeartbeat(self, vehicleTopic: str):
        if vehicleTopic in self._vehicles:
            self._vehicles[vehicleTopic].onHeartbeat()
