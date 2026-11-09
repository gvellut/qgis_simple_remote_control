import math

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsExpression,
    QgsMapSettings,
    QgsPointXY,
    QgsRectangle,
    QgsTileMatrix,
    QgsVectorLayer,
    QgsVectorTileLayer,
)


def _number(params: dict, key: str) -> float:
    value = params.get(key)
    if type(value) not in (int, float):
        raise ValueError(f"{key} must be a finite number.")
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError(f"{key} must be a finite number.") from error
    if not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number.")
    return value


class MapCommands:
    def __init__(self, canvas, project):
        self._canvas = canvas
        self._project = project
        self._methods = {
            "move": self._move,
            "select": self._select,
            "zoomToSelection": self._zoom_to_selection,
        }

    def dispatch(self, method: str, params: dict) -> int | None:
        command = self._methods.get(method)
        if command is None:
            raise ValueError(f"Unknown method {method!r}.")
        return command(params)

    def _move(self, params: dict) -> None:
        if params.keys() & {"lat", "lon"}:
            if params.keys() & {"x", "y", "crs"}:
                raise ValueError("Use lat and lon or x, y and crs.")
            x, y = _number(params, "lon"), _number(params, "lat")
            if not (-180 <= x <= 180 and -90 <= y <= 90):
                raise ValueError("Latitude or longitude is outside the WGS 84 range.")
            crs_name = "EPSG:4326"
        else:
            x, y = _number(params, "x"), _number(params, "y")
            crs_name = params.get("crs")
            if not isinstance(crs_name, str) or not crs_name.strip():
                raise ValueError("crs must identify a coordinate reference system.")

        scale = None
        if "scale" in params:
            if "z" in params:
                raise ValueError("Use either scale or z.")
            scale = _number(params, "scale")
            if scale <= 0:
                raise ValueError("scale must be positive.")
        elif "z" in params:
            zoom = params["z"]
            if type(zoom) is not int or not 0 <= zoom <= 30:
                raise ValueError("z must be an integer from 0 to 30.")
            scale = QgsTileMatrix.fromWebMercator(zoom).scale()

        source = QgsCoordinateReferenceSystem(crs_name)
        destination = self._canvas.mapSettings().destinationCrs()
        if not source.isValid() or not destination.isValid():
            raise ValueError(
                "The source or map coordinate reference system is invalid."
            )
        transform = QgsCoordinateTransform(source, destination, self._project)
        try:
            center = transform.transform(QgsPointXY(x, y))
        except QgsCsException as error:
            raise ValueError("Could not transform the point to the map CRS.") from error
        if not (math.isfinite(center.x()) and math.isfinite(center.y())):
            raise ValueError(
                "The transformed map coordinates are outside the CRS range."
            )

        self._set_view(center, scale)

    def _set_view(self, center: QgsPointXY, scale: float | None) -> None:
        settings = QgsMapSettings(self._canvas.mapSettings())
        current = settings.extent()
        if current.isEmpty():
            # A new project has no extent or scale to preserve.
            target = QgsRectangle.fromCenterAndSize(center, 1, 1)
            if scale is None:
                scale = QgsTileMatrix.fromWebMercator(2).scale()
        else:
            target = QgsRectangle.fromCenterAndSize(
                center, current.width(), current.height()
            )

        settings.setExtent(target)
        if not settings.hasValidSettings() or not 0 < settings.scale() < math.inf:
            raise ValueError("The point does not produce a usable map extent.")
        if scale is not None:
            target.scale(scale / settings.scale(), center)
            settings.setExtent(target)
            if not settings.hasValidSettings() or not 0 < settings.scale() < math.inf:
                raise ValueError(
                    "The requested scale does not produce a usable extent."
                )

        self._canvas.setExtent(target)
        self._canvas.refresh()

    def _layer(self, params: dict):
        identifier = params.get("layer")
        nodes = self._project.layerTreeRoot().findLayers()
        if isinstance(identifier, str):
            node = next((node for node in nodes if node.name() == identifier), None)
        elif type(identifier) is int:
            node = nodes[identifier] if 0 <= identifier < len(nodes) else None
        else:
            raise ValueError("layer must be a label or a zero-based index.")

        layer = node.layer() if node is not None else None
        if layer is None or not layer.isValid():
            raise ValueError(f"No available layer matches {identifier!r}.")
        return layer

    def _select(self, params: dict) -> int:
        layer = self._layer(params)
        if not isinstance(layer, QgsVectorLayer):
            raise ValueError("Select by expression requires a vector layer.")

        source = params.get("expression")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("expression must be a nonempty QGIS expression.")
        expression = QgsExpression(source)
        if expression.hasParserError():
            raise ValueError(expression.parserErrorString())
        if not expression.prepare(layer.createExpressionContext()):
            raise ValueError(expression.evalErrorString() or "Invalid QGIS expression.")

        layer.selectByExpression(source, Qgis.SelectBehavior.SetSelection)
        return layer.selectedFeatureCount()

    def _zoom_to_selection(self, params: dict) -> None:
        layer = self._layer(params)
        if not isinstance(layer, QgsVectorLayer | QgsVectorTileLayer) or not (
            layer.isSpatial()
        ):
            raise ValueError("Zoom to selection requires a spatial vector layer.")
        if layer.selectedFeatureCount() == 0:
            raise ValueError("The layer has no selected features.")
        self._canvas.zoomToSelected(layer)
