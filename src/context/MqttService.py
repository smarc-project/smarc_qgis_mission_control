import json
import os
import re
import socket
import sys
import threading
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot

# Import bundled MQTT
path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'third_party')
sys.path.insert(0, path)
import paho.mqtt.client as mqtt

from ..compat import StrEnum
from ..domain.missionplan import MissionPlan
from ..domain.waraps import WaraPsAvailableTask, WaraPsExecutingTask
from ..domain.waypoints import GeoPoint


@dataclass
class VehicleEvent:
    vehicleTopic: str

@dataclass
class VehicleHeartbeatEvent(VehicleEvent):
    mode: str | None = "Mode"
    pass

@dataclass
class VehicleSensorEvent(VehicleEvent):
    position: GeoPoint | None = None
    heading: float | None = None
    course: float | None = None
    depth: float | None = None
    speed: float | None = None
    roll: float | None = None
    pitch: float | None = None

@dataclass
class VehicleTaskStateEvent(VehicleEvent):
    tasksAvailable: list[WaraPsAvailableTask]
    tasksExecuting: list[WaraPsExecutingTask]

class MqttConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"

class MqttService(QObject):
    connectionStateChanged = pyqtSignal(MqttConnectionState)
    vehicleHeartbeat = pyqtSignal(VehicleHeartbeatEvent)
    vehicleSensorEvent = pyqtSignal(VehicleSensorEvent)
    vehicleTaskStateEvent = pyqtSignal(VehicleTaskStateEvent)

    _client: mqtt.Client | None
    _context: str
    _vehicles: dict[str, dict]

    mqttTopicPattern = re.compile(
        r'([^/]+)/unit/(air|surface|subsurface|command)/(real|simulation|command)/([^/]+)(/.+)$'
    )

    def __init__(self, parent: QObject | None):
        super().__init__(parent)
        self._context = ""
        self._vehicles: dict[str, dict] = {}
        self._connect_rc = None
        self._senderId = "QGIS-MissionControl"  # default, overridable via setSenderId()

        self._connect_event = threading.Event()

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self.onMqttConnect
        self._client.on_connect_fail = self.onMqttConnectFail
        self._client.on_disconnect = self.onMqttDisconnect
        self._client.on_message = self.onMqttMessage

    def connect(self, ip: str, port: int, username: str | None, password: str | None,
                context: str, timeout: float = 5):        
        self.disconnect() # if this is called, self._client -> NoneType
                    
        # Always create a fresh client
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self.onMqttConnect
        self._client.on_connect_fail = self.onMqttConnectFail
        self._client.on_disconnect = self.onMqttDisconnect
        self._client.on_message = self.onMqttMessage

        self._connect_rc = None
        self._connect_event.clear()
        self._context = context

        # TODO: username/password/TLS --> perhaps done now?
        self._client.username_pw_set(username, password)

        try:
            print("Connecting to MQTT...")
            # self._client.connect_async(ip, port)
            self._client.connect(ip, port, keepalive=60)
        except (socket.gaierror, ConnectionRefusedError, TimeoutError, OSError) as e:
            self.connectionStateChanged.emit(MqttConnectionState.DISCONNECTED)
            raise ConnectionError(f"Could not connect to MQTT broker: {e}") from e

        self._client.loop_start()

        if not self._connect_event.wait(timeout):
            self.connectionStateChanged.emit(MqttConnectionState.DISCONNECTED)
            raise TimeoutError("MQTT connection attempt timed out")

        if not self._client.is_connected():
            raise ConnectionError(f"MQTT connection rejected: {self._connect_rc}")

    def disconnect(self):
        if self._client is None:
            return
        try:
            print("Disconnecting from MQTT...")
            self._client.disconnect()
        except Exception:
            pass
        finally:
            self._client.loop_stop()
            self._client = None

    def setSenderId(self, senderId: str):
        self._senderId = senderId or "QGIS-MissionControl"

    def onMqttConnect(self, client, userdata, flags, reason_code, properties):
        self._connect_rc = reason_code

        if reason_code == 0:
            print("MQTT connected successfully")
            print("subscribing to context:", self._context)
            client.subscribe(f"{self._context}/#")

            self.connectionStateChanged.emit(MqttConnectionState.CONNECTED)
        else:
            self.connectionStateChanged.emit(MqttConnectionState.DISCONNECTED)
            print(f"MQTT connection rejected: {reason_code}")

        self._connect_event.set()

    def onMqttConnectFail(self, client, userdata):
        self.connectionStateChanged.emit(MqttConnectionState.DISCONNECTED)
        print("MQTT connection failed")
        self._connect_event.set()

    def onMqttDisconnect(self, client, userdata, flags, reason_code, properties):
        self.connectionStateChanged.emit(MqttConnectionState.DISCONNECTED)
        print(f"MQTT disconnected: {reason_code}")

    def onMqttMessage(self, client, userdata, message):
        match = self.mqttTopicPattern.match(message.topic)
        if not match:
            # Not something we support yet
            return
        root, domain, mode, vehicleName, vehicleSubtopic = match.groups()

        # Reconstruct vehicle topic
        vehicleTopic = f'{root}/unit/{domain}/{mode}/{vehicleName}'

        if vehicleSubtopic == r'/heartbeat':
            data = json.loads(message.payload)
            event = VehicleHeartbeatEvent(
                vehicleTopic = vehicleTopic,
            )
            event.mode = mode
            
            print(event)
            self.vehicleHeartbeat.emit(event)
        elif (match := re.match(r'/sensor/([^/]+)$', vehicleSubtopic)) is not None:
            if not vehicleTopic in self._vehicles:
                self._vehicles[vehicleTopic] = {
                    'sensor': VehicleSensorEvent(vehicleTopic)
                }
            vehicleSensorEvent = self._vehicles[vehicleTopic]['sensor']

            sensor = match.group(1)
            if sensor == 'position':
                data = json.loads(message.payload)
                # Our GeoPoint class expects tolerance, but it is not a standard WARA-PS
                # field, so we mock it to 0. Also, we expect rostype instead of type
                # TODO: carry position not as GeoPoint
                data['tolerance'] = 0
                data['rostype'] = data.pop('type')
                point = GeoPoint.fromJson(data)

                vehicleSensorEvent.position = point

                # print(vehicleSensorEvent)
                # TODO: emit sensor events even if position was not updated?
                self.vehicleSensorEvent.emit(deepcopy(vehicleSensorEvent))
            elif sensor in ['heading', 'course', 'depth', 'speed', 'roll', 'pitch']:
                setattr(vehicleSensorEvent, sensor, float(message.payload))
            elif sensor in ['bt', 'executing_tasks']:
                # explicitly unhandled sensors
                ...
            else:
                # unsupported sensor!
                print(f'unsupported sensor', sensor)
        elif vehicleSubtopic == '/tst_execution_info':
            data = json.loads(message.payload)
            tasksExecuting = [
                WaraPsExecutingTask(
                    description=task['description'],
                    type=task['task-name'],
                    status=task['status'],
                    uuid=UUID(task['task-uuid'])
                ) for task in data['tasks-executing']
            ]
            event = VehicleTaskStateEvent(
                # TODO
                vehicleTopic=vehicleTopic,
                tasksAvailable=[],
                tasksExecuting=tasksExecuting,
            )
            self.vehicleTaskStateEvent.emit(event)
        else:
            # unsupported vehicle subtopic!
            ...

    @pyqtSlot(MissionPlan, set)
    def onPublishMissionPlan(self, plan: MissionPlan, vehicleTopics: set[str]):
        if self._client is None:
            # TODO
            return
        for vehicleTopic in vehicleTopics:
            self.publishMissionPlan(plan, vehicleTopic)

    def publishMissionPlan(self, plan: MissionPlan, vehicleTopic: str):
        if self._client is None:
            # TODO
            return
        topic = f'{vehicleTopic}/tst/command'
        receiver = vehicleTopic.split('/')[-1]
        data = {
            "receiver": receiver,
            "command": "start-tst",
            "tst": plan.toJson() | {
                "common-params": {
                    "execunit": f"/{receiver}",
                    "node-uuid": str(uuid4()),
                },
            },
            "com-uuid": str(uuid4()),
            "sender": self._senderId,
        }
        self._client.publish(topic, json.dumps(data))

    @pyqtSlot(set)
    def onEmergencySignal(self, vehicleTopics: set[str]):
        if self._client is None:
            # TODO
            return
        for vehicleTopic in vehicleTopics:
            self.publishEmergencySignal(vehicleTopic)

    def publishEmergencySignal(self, vehicleTopic: str):
        if self._client is None:
            # TODO
            return
        topic = f'{vehicleTopic}/tst/command'
        receiver = vehicleTopic.split('/')[-1]
        data = {
            'receiver': receiver,
            'signal': '$abort',
            'unit': f'/{receiver}',
            'command': 'signal-unit',
            'com-uuid': str(uuid4()),
            'sender': self._senderId,
        }
        self._client.publish(topic, json.dumps(data))

    @pyqtSlot(set)
    def onResetEmergencySignal(self, vehicleTopics: set[str]):
        if self._client is None:
            # TODO
            return
        for vehicleTopic in vehicleTopics:
            self.publishResetEmergencySignal(vehicleTopic)

    def publishResetEmergencySignal(self, vehicleTopic: str):
        if self._client is None:
            # TODO
            return
        topic = f'{vehicleTopic}/tst/command'
        receiver = vehicleTopic.split('/')[-1]
        data = {
            'receiver': receiver,
            'signal': '$cancel_abort',
            'unit': f'/{receiver}',
            'command': 'signal-unit',
            'com-uuid': str(uuid4()),
            'sender': self._senderId,
        }
        self._client.publish(topic, json.dumps(data))

    @pyqtSlot(set)
    def onSkipTaskSignal(self, targets: dict):
        if self._client is None:
            # TODO
            return
        for vehicleTopic, taskUuid in targets.items():
            self.publishSkipTaskSignal(vehicleTopic, taskUuid)

    def publishSkipTaskSignal(self, vehicleTopic: str, taskUuid: UUID):
        if self._client is None:
            # TODO
            return
        topic = f'{vehicleTopic}/exec/command'
        receiver = vehicleTopic.split('/')[-1]
        data = {
            'signal': '$enough',
            'task-uuid': str(taskUuid),
            'command': 'signal-task',
            'com-uuid': str(uuid4()),
            'sender': self._senderId,
        }
        self._client.publish(topic, json.dumps(data))

    @pyqtSlot(set)
    def onAbortMissionSignal(self, vehicleTopics: set[str]):
        if self._client is None:
            # TODO
            return
        for vehicleTopic in vehicleTopics:
            self.publishAbortMissionSignal(vehicleTopic)

    def publishAbortMissionSignal(self, vehicleTopic: str):
        if self._client is None:
            # TODO
            return
        topic = f'{vehicleTopic}/tst/command'
        receiver = vehicleTopic.split('/')[-1]
        data = {
            'receiver': receiver,
            'signal': '$enough',
            'unit': f'/{receiver}',
            'command': 'signal-unit',
            'com-uuid': str(uuid4()),
            'sender': self._senderId,
        }
        self._client.publish(topic, json.dumps(data))
