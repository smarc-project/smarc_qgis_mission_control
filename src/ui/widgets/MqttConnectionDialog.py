from qgis.PyQt.QtWidgets import QWidget, QDialog

from ..generated.MqttConnectionDialogUi import Ui_MqttConnectionDialog

__all__ = ["MqttConnectionDialog"]


class MqttConnectionDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.ui = Ui_MqttConnectionDialog()
        self.ui.setupUi(self)

        # Disable resizing, ensuring size provided in QtDesigner
        self.setFixedSize(self.size())

    def ip(self) -> str:
        return self.ui.lineEditIp.text().strip()
    
    def setIp(self, ip: str):
        self.ui.lineEditIp.setText(ip)

    def port(self) -> int:
        return int(self.ui.lineEditPort.text().strip())
    
    def setPort(self, port: int):
        self.ui.lineEditPort.setText(str(port))

    def username(self) -> str | None:
        value = self.ui.lineEditUsername.text().strip()
        return value if value else None
    
    def setUsername(self, username: str):
        self.ui.lineEditUsername.setText(username)

    def password(self) -> str | None:
        value = self.ui.lineEditPassword.text().strip()
        return value if value else None
    
    def setPassword(self, password: str):
        self.ui.lineEditPassword.setText(password)

    def context(self) -> str:
        return self.ui.lineEditContext.text().strip()
    
    def setContext(self, context: str):
        self.ui.lineEditContext.setText(context)
