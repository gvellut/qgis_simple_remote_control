from collections.abc import Callable
import json
import logging

LOGGER = logging.getLogger(__name__)


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant {value}")


def handle_request(frame: bytes, dispatch: Callable[[str, dict], None]) -> bytes | None:
    try:
        request = json.loads(frame.decode("utf-8"), parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(request, dict):
        return None

    has_id = "id" in request
    request_id = request.get("id")
    if has_id and type(request_id) not in (str, int):
        return None

    try:
        method, params = request.get("method"), request.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            raise ValueError("A request needs a method string and a params object.")
        dispatch(method, params)
        reply = {"id": request_id, "ok": True}
    except ValueError as error:
        reply = {"id": request_id, "ok": False, "error": str(error)}
    except Exception:
        LOGGER.exception("Remote control request failed")
        reply = {
            "id": request_id,
            "ok": False,
            "error": "QGIS could not run the command.",
        }

    if has_id:
        serialized = json.dumps(reply, ensure_ascii=False, separators=(",", ":"))
        return serialized.encode("utf-8", errors="backslashreplace") + b"\n"
    return None
