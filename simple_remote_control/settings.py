from dataclasses import dataclass

from qgis.core import QgsSettings
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from .server import DEFAULT_ABSOLUTE, DEFAULT_NAME, LocalServer

TITLE = "Simple Remote Control"
SETTINGS_ROOT = "SimpleRemoteControl"


@dataclass(frozen=True)
class Settings:
    mode: str
    qt_name: str
    absolute_path: str
    restore_server_state: bool
    server_was_running: bool

    @classmethod
    def load(cls):
        settings = QgsSettings()
        settings.beginGroup(SETTINGS_ROOT)
        return cls(
            mode=(
                "absolute"
                if settings.value("mode", "qt", type=str) == "absolute"
                else "qt"
            ),
            qt_name=settings.value("qt_name", DEFAULT_NAME, type=str),
            absolute_path=settings.value("absolute_path", DEFAULT_ABSOLUTE, type=str),
            # Keep the existing checkbox preference.
            restore_server_state=settings.value("autostart", False, type=bool),
            server_was_running=settings.value("server_was_running", False, type=bool),
        )

    @staticmethod
    def save_server_state(running: bool) -> None:
        settings = QgsSettings()
        settings.setValue(f"{SETTINGS_ROOT}/server_was_running", running)
        settings.sync()

    @property
    def address(self) -> str:
        return self.qt_name if self.mode == "qt" else self.absolute_path


class OptionsPage(QgsOptionsPageWidget):
    def __init__(self, server: LocalServer, parent=None):
        super().__init__(parent)
        self._server = server
        settings = Settings.load()
        self._mode = settings.mode
        self._addresses = {"qt": settings.qt_name, "absolute": settings.absolute_path}

        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Qt", "qt")
        self.mode_combo.addItem("Absolute", "absolute")
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(self._mode))
        self.address_edit = QLineEdit(settings.address, self)
        self.restore_state_checkbox = QCheckBox("Restore server state on startup", self)
        self.restore_state_checkbox.setChecked(settings.restore_server_state)

        form = QFormLayout()
        form.addRow("Socket mode", self.mode_combo)
        form.addRow("Socket address", self.address_edit)
        form.addRow(self.restore_state_checkbox)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch()

        self.mode_combo.currentIndexChanged.connect(self._change_mode)
        server.running_changed.connect(self._set_address_locked)
        self._set_address_locked(server.running)

    def _change_mode(self) -> None:
        self._addresses[self._mode] = self.address_edit.text()
        self._mode = self.mode_combo.currentData()
        self.address_edit.setText(self._addresses[self._mode])

    def _set_address_locked(self, running: bool) -> None:
        self.mode_combo.setEnabled(not running)
        self.address_edit.setEnabled(not running)

    def apply(self) -> None:
        settings = QgsSettings()
        settings.beginGroup(SETTINGS_ROOT)
        settings.setValue("autostart", self.restore_state_checkbox.isChecked())
        if not self._server.running:
            self._addresses[self._mode] = self.address_edit.text()
            settings.setValue("mode", self._mode)
            settings.setValue("qt_name", self._addresses["qt"])
            settings.setValue("absolute_path", self._addresses["absolute"])


class OptionsFactory(QgsOptionsWidgetFactory):
    def __init__(self, server: LocalServer, icon):
        super().__init__(TITLE, icon, TITLE)
        self._server = server

    def createWidget(self, parent=None):
        return OptionsPage(self._server, parent)
