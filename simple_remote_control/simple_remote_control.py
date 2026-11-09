from pathlib import Path

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtGui import QAction, QIcon

from .commands import MapCommands
from .server import LocalServer
from .settings import TITLE, OptionsFactory, Settings


class SimpleRemoteControlPlugin:
    def __init__(self, iface):
        self.iface = iface
        commands = MapCommands(iface.mapCanvas(), QgsProject.instance())
        self.server = LocalServer(commands.dispatch)

    def initGui(self) -> None:
        window = self.iface.mainWindow()
        icon_dir = Path(__file__).with_name("icons")
        plugin_icon = QIcon(str(icon_dir / "remote-control.svg"))
        self._start_icon = QIcon(str(icon_dir / "remote-control-start.svg"))
        self._stop_icon = QIcon(str(icon_dir / "remote-control-stop.svg"))
        self._toggle_action = QAction(window)
        self._toggle_action.triggered.connect(self._toggle)
        self.server.running_changed.connect(self._update_action)
        self._update_action(self.server.running)
        self.iface.addToolBarIcon(self._toggle_action)
        self.iface.addPluginToMenu(TITLE, self._toggle_action)

        self._settings_action = QAction(
            QgsApplication.getThemeIcon("/mActionOptions.svg"), "Settings", window
        )
        self._settings_action.triggered.connect(self._open_settings)
        self.iface.addPluginToMenu(TITLE, self._settings_action)
        self._options_factory = OptionsFactory(self.server, plugin_icon)
        self.iface.registerOptionsWidgetFactory(self._options_factory)

        settings = Settings.load()
        if settings.restore_server_state and settings.server_was_running:
            self._start(settings)

    def unload(self) -> None:
        self.server.stop()
        self.server.running_changed.disconnect(self._update_action)
        self.iface.unregisterOptionsWidgetFactory(self._options_factory)
        self._options_factory.deleteLater()
        self.iface.removeToolBarIcon(self._toggle_action)
        for action in (self._toggle_action, self._settings_action):
            self.iface.removePluginMenu(TITLE, action)
            action.deleteLater()

    def _start(self, settings: Settings) -> None:
        try:
            self.server.start(settings.mode, settings.address)
        except (OSError, ValueError) as error:
            self.iface.messageBar().pushCritical(
                TITLE, f"Could not start on {settings.address!r}. {error}"
            )
        else:
            Settings.save_server_state(True)

    def _toggle(self) -> None:
        if self.server.running:
            self.server.stop()
            Settings.save_server_state(False)
        else:
            self._start(Settings.load())

    def _update_action(self, running: bool) -> None:
        self._toggle_action.setText("Stop" if running else "Start")
        self._toggle_action.setIcon(self._stop_icon if running else self._start_icon)
        self._toggle_action.setToolTip(
            "Stop the local remote control server"
            if running
            else "Start the local remote control server"
        )

    def _open_settings(self) -> None:
        self.iface.showOptionsDialog(self.iface.mainWindow(), TITLE)
