import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qgis.core import (
        QgsApplication,
        QgsCoordinateReferenceSystem,
        QgsCoordinateTransform,
        QgsFeature,
        QgsGeometry,
        QgsPointXY,
        QgsProject,
        QgsRasterLayer,
        QgsRectangle,
        QgsSettings,
        QgsTileMatrix,
        QgsVectorLayer,
    )
    from qgis.gui import QgsMapCanvas
    from qgis.PyQt.QtCore import QDir
    from qgis.PyQt.QtNetwork import QLocalSocket
except ModuleNotFoundError as error:
    if error.name == "qgis":
        raise unittest.SkipTest("Requires the QGIS 4 Python runtime.") from error
    raise

from simple_remote_control.commands import MapCommands
from simple_remote_control.server import (
    DEFAULT_ABSOLUTE,
    DEFAULT_NAME,
    MAX_FRAME_BYTES,
    LocalServer,
)
from simple_remote_control.settings import SETTINGS_ROOT, OptionsPage, Settings

PROFILE = tempfile.TemporaryDirectory(prefix="qrc-tests-")
APP = QgsApplication([], True, PROFILE.name)
APP.initQgis()


class MapCommandTests(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.canvas = QgsMapCanvas()
        self.canvas.resize(800, 600)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        self.canvas.setExtent(QgsRectangle(-1e6, -1e6, 1e6, 1e6))
        self.commands = MapCommands(self.canvas, self.project)

    def tearDown(self):
        self.canvas.stopRendering()
        self.canvas.deleteLater()
        self.project.clear()

    def assert_center(self, expected):
        self.assertAlmostEqual(self.canvas.center().x(), expected.x(), places=6)
        self.assertAlmostEqual(self.canvas.center().y(), expected.y(), places=6)

    def test_move_pan_and_both_zoom_options(self):
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(
            wgs84, self.canvas.mapSettings().destinationCrs(), self.project
        )
        expected = transform.transform(QgsPointXY(2.3522, 48.8566))
        original_scale = self.canvas.scale()
        self.commands.dispatch("move", {"lat": 48.8566, "lon": 2.3522})
        self.assert_center(expected)
        self.assertAlmostEqual(self.canvas.scale(), original_scale)

        self.commands.dispatch(
            "move", {"x": 1000, "y": 2000, "crs": "EPSG:3857", "scale": 25000}
        )
        self.assert_center(QgsPointXY(1000, 2000))
        self.assertAlmostEqual(self.canvas.scale(), 25000)

        self.commands.dispatch("move", {"lat": 48.8566, "lon": 2.3522, "z": 14})
        self.assert_center(expected)
        self.assertAlmostEqual(
            self.canvas.scale(), QgsTileMatrix.fromWebMercator(14).scale()
        )

    def test_invalid_move_leaves_view_intact(self):
        original_extent = self.canvas.extent()
        for params in (
            {"lat": 40},
            {"lat": 40, "lon": 2, "x": 2},
            {"lat": 40, "lon": 2, "scale": 0},
            {"lat": 40, "lon": 2, "scale": 1e-300},
            {"lat": 40, "lon": 2, "scale": 1e308},
            {"lat": 40, "lon": 2, "scale": 25000, "z": 14},
            {"lat": 40, "lon": 2, "z": True},
            {"lat": 40, "lon": 2, "z": 31},
            {"lat": 91, "lon": 2},
            {"lat": 40, "lon": float("inf")},
            {"x": 2, "y": 40, "crs": "EPSG:0"},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.commands.dispatch("move", params)
            self.assertEqual(self.canvas.extent(), original_extent)

    def test_move_initializes_blank_canvas(self):
        canvas = QgsMapCanvas()
        self.addCleanup(canvas.deleteLater)
        canvas.resize(800, 600)
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        self.assertTrue(canvas.extent().isEmpty())

        MapCommands(canvas, self.project).dispatch(
            "move", {"x": 1000, "y": 2000, "crs": "EPSG:3857"}
        )
        self.assertEqual(canvas.center(), QgsPointXY(1000, 2000))
        self.assertAlmostEqual(
            canvas.scale() / QgsTileMatrix.fromWebMercator(2).scale(), 1
        )

    def add_places(self, group, name):
        layer = QgsVectorLayer("Point?crs=EPSG:3857&field=name:string", name, "memory")
        self.project.addMapLayer(layer, False)
        node = group.addLayer(layer)
        features = []
        for label, x in (("Café Nord", 1000), ("Café Sud", 2000), ("Museum", 9000)):
            feature = QgsFeature(layer.fields())
            feature.setAttributes([label])
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, x)))
            features.append(feature)
        self.assertTrue(layer.dataProvider().addFeatures(features)[0])
        layer.updateExtents()
        return layer, node

    def test_tree_lookup_selection_and_zoom(self):
        root = self.project.layerTreeRoot()
        group = root.addGroup("Group").addGroup("Nested")
        raster = QgsRasterLayer()
        self.project.addMapLayer(raster, False)
        group.addLayer(raster)
        first, node = self.add_places(group, "source name")
        node.setUseLayerName(False)
        node.setName("Places")
        node.setItemVisibilityChecked(False)
        second, _ = self.add_places(root, "Places")
        second.selectAll()

        expression = """strpos("name", 'Café') > 0"""
        self.commands.dispatch("select", {"layer": "Places", "expression": expression})
        self.assertEqual(first.selectedFeatureCount(), 2)
        self.assertEqual(second.selectedFeatureCount(), 3)

        self.commands.dispatch("zoomToSelection", {"layer": 1})
        self.assert_center(QgsPointXY(1500, 1500))
        self.assertLess(self.canvas.extent().width(), 10000)

        self.commands.dispatch("select", {"layer": 2, "expression": "false"})
        self.assertEqual(second.selectedFeatureCount(), 0)
        with self.assertRaisesRegex(ValueError, "no selected features"):
            self.commands.dispatch("zoomToSelection", {"layer": 2})
        for name in ("places", "source name", -1, True):
            with self.subTest(layer=name), self.assertRaises(ValueError):
                self.commands.dispatch("zoomToSelection", {"layer": name})

        with self.assertRaises(ValueError):
            self.commands.dispatch("select", {"layer": 1, "expression": '"absent" = 3'})
        self.assertEqual(first.selectedFeatureCount(), 2)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        QgsSettings().remove(SETTINGS_ROOT)
        self.addCleanup(QgsSettings().remove, SETTINGS_ROOT)

    def test_settings_remember_both_modes_and_startup_choice(self):
        self.assertEqual(
            Settings.load(), Settings("qt", DEFAULT_NAME, DEFAULT_ABSOLUTE, False)
        )
        server = LocalServer(self.fail)
        page = OptionsPage(server)
        self.assertEqual(page.address_edit.text(), DEFAULT_NAME)
        page.address_edit.setText("custom-name")
        page.mode_combo.setCurrentIndex(1)
        self.assertEqual(page.address_edit.text(), DEFAULT_ABSOLUTE)
        page.address_edit.setText("/tmp/custom.sock")
        page.mode_combo.setCurrentIndex(0)
        self.assertEqual(page.address_edit.text(), "custom-name")
        page.mode_combo.setCurrentIndex(1)
        page.autostart_checkbox.setChecked(True)
        page.apply()

        reloaded = OptionsPage(server)
        self.assertEqual(
            Settings.load(),
            Settings("absolute", "custom-name", "/tmp/custom.sock", True),
        )
        self.assertEqual(reloaded.address_edit.text(), "/tmp/custom.sock")


@unittest.skipUnless(sys.platform in ("darwin", "linux"), "Uses Unix socket paths.")
class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        self.server = LocalServer(
            lambda method, params: self.received.append((method, params))
        )
        self.client = QLocalSocket()
        self.addCleanup(self.server.stop)
        self.addCleanup(self.client.abort)
        self.name = f"qrc-test-{uuid4().hex[:12]}"

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.001)
        self.assertTrue(condition())

    def connect(self):
        self.server.start("qt", self.name)
        self.client.connectToServer(self.name)
        self.wait_for(
            lambda: self.client.state() == QLocalSocket.LocalSocketState.ConnectedState
        )

    def test_fragmented_and_batched_requests_and_stop(self):
        self.connect()
        data = '{"id":0,"method":"select","params":{"layer":"Café"}}\n'.encode()
        split_at = data.index(b"\xc3") + 1
        self.client.write(data[:split_at])
        self.client.flush()
        APP.processEvents()
        self.assertFalse(self.received)
        self.client.write(
            data[split_at:]
            + b'invalid\n{"method":"move","params":{}}\n'
            + b'{"id":"last","method":"move","params":{}}\n'
        )
        self.wait_for(lambda: len(self.received) == 3 and self.client.canReadLine())
        self.assertEqual(
            self.received,
            [("select", {"layer": "Café"}), ("move", {}), ("move", {})],
        )
        self.assertEqual(
            json.loads(bytes(self.client.readLine())), {"id": 0, "ok": True}
        )
        self.wait_for(self.client.canReadLine)
        self.assertEqual(
            json.loads(bytes(self.client.readLine())), {"id": "last", "ok": True}
        )
        self.assertEqual(self.client.bytesAvailable(), 0)
        self.server.stop()
        self.wait_for(
            lambda: (
                self.client.state() == QLocalSocket.LocalSocketState.UnconnectedState
            )
        )
        self.assertFalse((Path(QDir.tempPath()) / self.name).exists())

    def test_oversized_frame_disconnects(self):
        self.connect()
        self.client.write(b" " * (MAX_FRAME_BYTES + 1))
        self.wait_for(
            lambda: (
                self.client.state() == QLocalSocket.LocalSocketState.UnconnectedState
            )
        )
        self.assertFalse(self.received)
        self.assertTrue(self.server.running)

    def test_occupied_address_and_settings_lock(self):
        path = Path("/tmp") / f"{self.name}.sock"
        path.write_text("occupied")
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaisesRegex(OSError, "occupied"):
            self.server.start("absolute", str(path))
        self.assertEqual(path.read_text(), "occupied")
        path.unlink()

        page = OptionsPage(self.server)
        self.server.start("absolute", str(path))
        self.assertFalse(page.mode_combo.isEnabled())
        self.assertFalse(page.address_edit.isEnabled())
        self.assertTrue(page.autostart_checkbox.isEnabled())
        self.server.stop()
        self.assertTrue(page.mode_combo.isEnabled())
        self.assertTrue(page.address_edit.isEnabled())
        self.assertFalse(path.exists())
