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
        self._fleetContext.state.vehicleReturned.connect(self.onVehicleReturned)
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

    def _shown(self) -> dict[str, VehicleLiveViewWidget]:
        """Rows of the vehicles that are not hidden for being silent."""
        state = self._fleetContext.state
        return {t: w for t, w in self._vehicles.items() if state.isActive(t)}

    def selectAll(self):
        print("Selecting all...")
        for vehicle in self._shown().values():
            vehicle.setChecked(True)

    def deselectAll(self):
        # Hidden rows too: their last position is still on the map.
        for vehicle in self._vehicles.values():
            vehicle.setChecked(False)

    def collapseAll(self):
        for vehicle in self._shown().values():
            vehicle.setCollapsed(True)

    def expandAll(self):
        for vehicle in self._shown().values():
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
        shown = self._shown()
        selected = self._selected & shown.keys()
        collapsed = self._collapsed & shown.keys()
        if len(shown) == 0:
            # nothing is enabled if no cards are available
            self.ui.selectAllButton.setEnabled(False)
            self.ui.deselectAllButton.setEnabled(bool(self._selected))
            self.ui.collapseAllButton.setEnabled(False)
            self.ui.expandAllButton.setEnabled(False)
            self.ui.clearTracksButton.setEnabled(bool(self._vehicles))
        else:
            allSelected = len(selected) == len(shown)
            allCollapsed = len(collapsed) == len(shown)
            someCollapsed = len(collapsed) != 0

            self.ui.selectAllButton.setEnabled(not allSelected)
            self.ui.deselectAllButton.setEnabled(bool(self._selected))

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
        # Only the row goes; the vehicle's last position stays on the map.
        self._setRowShown(vehicleTopic, False)

    @pyqtSlot(str)
    def onVehicleReturned(self, vehicleTopic: str):
        self._setRowShown(vehicleTopic, True)

    def _setRowShown(self, vehicleTopic: str, shown: bool):
        widget = self._vehicles.get(vehicleTopic)
        if widget is None:
            return
        widget.setVisible(shown)
        self._refreshUiState()

    @pyqtSlot(str)
    def onVehicleHeartbeat(self, vehicleTopic: str):
        if vehicleTopic in self._vehicles:
            self._vehicles[vehicleTopic].onHeartbeat()
