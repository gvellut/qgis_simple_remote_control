# /// script
# requires-python = ">=3.12"
# dependencies = ["click>=8.1,<9", "PyQt6>=6.8,<7"]
# ///

import json

import click
from PyQt6.QtCore import QCoreApplication, QDeadlineTimer
from PyQt6.QtNetwork import QLocalSocket

TIMEOUT_MS = 30_000


def send_request(socket_name: str, method: str, params: dict) -> None:
    send_requests(socket_name, [(method, params)])


def send_requests(socket_name: str, requests: list[tuple[str, dict]]) -> None:
    try:
        frames = [
            (
                method,
                json.dumps(
                    {"id": request_id, "method": method, "params": params},
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
                + b"\n",
            )
            for request_id, (method, params) in enumerate(requests, 1)
        ]
    except ValueError as error:
        raise click.UsageError("Coordinates and scale must be finite.") from error

    selected_count = None
    socket = QLocalSocket()
    try:
        socket.connectToServer(socket_name)
        if socket.state() != QLocalSocket.LocalSocketState.ConnectedState and not (
            socket.waitForConnected(TIMEOUT_MS)
        ):
            raise click.ClickException(
                f"Could not connect to {socket_name!r}. {socket.errorString()}"
            )
        for request_id, (method, frame) in enumerate(frames, 1):
            try:
                reply = exchange(socket, request_id, frame)
            except click.ClickException as error:
                if len(requests) == 1:
                    raise
                raise click.ClickException(
                    f"{method} failed. {error.format_message()}"
                ) from error
            if method == "select":
                selected_count = reply.get("selectedCount")
    finally:
        socket.abort()
    click.echo("OK" if selected_count is None else f"OK ({selected_count} selected)")


def exchange(socket: QLocalSocket, request_id: int, request: bytes) -> dict:
    deadline = QDeadlineTimer(TIMEOUT_MS)
    if socket.write(request) != len(request):
        raise click.ClickException(f"Could not send request. {socket.errorString()}")
    while socket.bytesToWrite():
        if deadline.hasExpired() or not socket.waitForBytesWritten(
            deadline.remainingTime()
        ):
            raise click.ClickException(
                f"Could not send request. {socket.errorString()}"
            )
    while not socket.canReadLine():
        if deadline.hasExpired():
            raise click.ClickException("Timed out waiting for QGIS to reply.")
        if not socket.waitForReadyRead(deadline.remainingTime()) and not (
            socket.canReadLine()
        ):
            raise click.ClickException(f"No reply from QGIS. {socket.errorString()}")

    try:
        reply = json.loads(bytes(socket.readLine()).decode("utf-8"))
    except ValueError as error:
        raise click.ClickException("QGIS sent an invalid JSON reply.") from error
    if (
        not isinstance(reply, dict)
        or type(reply.get("id")) is not int
        or reply["id"] != request_id
    ):
        raise click.ClickException("QGIS sent a reply with an unexpected request ID.")
    if reply.get("ok") is not True:
        raise click.ClickException(reply.get("error") or "QGIS rejected the request.")
    return reply


def layer_identifier(layer: str | None, layer_index: int | None) -> str | int:
    if layer is not None and layer_index is None:
        return layer
    if layer is None and layer_index is not None:
        return layer_index
    raise click.UsageError("Specify either --layer or --layer-index.")


@click.group()
@click.option(
    "-s",
    "--socket-name",
    default="qgis-remote-control",
    show_default=True,
    help="Qt server name or absolute socket address.",
)
@click.pass_context
def cli(ctx: click.Context, socket_name: str) -> None:
    """Send a command to the Simple Remote Control plugin for QGIS."""
    ctx.obj = socket_name


@cli.command()
@click.option("--lat", type=click.FloatRange(-90, 90), help="WGS 84 latitude.")
@click.option("--lon", type=click.FloatRange(-180, 180), help="WGS 84 longitude.")
@click.option("--x", type=float, help="X coordinate in the supplied CRS.")
@click.option("--y", type=float, help="Y coordinate in the supplied CRS.")
@click.option("--crs", help="Coordinate reference system, for example EPSG:2154.")
@click.option(
    "--scale",
    type=click.FloatRange(min=0, min_open=True),
    help="Map scale denominator.",
)
@click.option("--z", type=click.IntRange(0, 30), help="Web Mercator zoom level.")
@click.option(
    "--marker", is_flag=True, help="Show a red marker until the next pan or zoom."
)
@click.pass_obj
def move(socket_name, lat, lon, x, y, crs, scale, z, marker):
    """Pan to a point and optionally zoom."""
    if lat is not None and lon is not None and x is None and y is None and crs is None:
        params = {"lat": lat, "lon": lon}
    elif x is not None and y is not None and crs and lat is None and lon is None:
        params = {"x": x, "y": y, "crs": crs}
    else:
        raise click.UsageError("Use --lat and --lon or --x, --y and --crs.")
    if scale is not None and z is not None:
        raise click.UsageError("Use either --scale or --z.")
    if scale is not None:
        params["scale"] = scale
    if z is not None:
        params["z"] = z
    if marker:
        params["marker"] = True
    send_request(socket_name, "move", params)


@cli.command()
@click.option("--layer", help="Exact Layers panel label.")
@click.option(
    "--layer-index", type=click.IntRange(min=0), help="Zero-based tree index."
)
@click.argument("expression")
@click.pass_obj
def select(socket_name, layer, layer_index, expression):
    """Replace a layer's selection using a QGIS expression."""
    send_request(
        socket_name,
        "select",
        {"layer": layer_identifier(layer, layer_index), "expression": expression},
    )


@cli.command()
@click.option("--layer", help="Exact Layers panel label.")
@click.option(
    "--layer-index", type=click.IntRange(min=0), help="Zero-based tree index."
)
@click.pass_obj
def zoom_to_selection(socket_name, layer, layer_index):
    """Zoom to a layer's selected features."""
    send_request(
        socket_name, "zoomToSelection", {"layer": layer_identifier(layer, layer_index)}
    )


@cli.command()
@click.option("--layer", help="Exact Layers panel label.")
@click.option(
    "--layer-index", type=click.IntRange(min=0), help="Zero-based tree index."
)
@click.argument("filename")
@click.pass_obj
def select_photo(socket_name, layer, layer_index, filename):
    """Select by the Name field and zoom. Include the filename extension."""
    identifier = layer_identifier(layer, layer_index)
    # Match the escaping used by QgsExpression.quotedString().
    escaped = (
        filename.replace("\\", "\\\\")
        .replace("'", "''")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    expression = f"\"Name\" = '{escaped}'"
    send_requests(
        socket_name,
        [
            ("select", {"layer": identifier, "expression": expression}),
            ("zoomToSelection", {"layer": identifier}),
        ],
    )


if __name__ == "__main__":
    app = QCoreApplication([])
    cli()
