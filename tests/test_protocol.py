import json
import unittest
from unittest.mock import Mock

from simple_remote_control.protocol import handle_request


class ProtocolTests(unittest.TestCase):
    def test_utf8_and_request_id(self):
        dispatch = Mock()
        request = {
            "id": "sélection",
            "method": "select",
            "params": {"layer": "Café", "expression": """strpos("name", 'é') > 0"""},
        }
        frame = json.dumps(request, ensure_ascii=False).encode("utf-8")
        reply = handle_request(frame, dispatch)
        self.assertTrue(reply.endswith(b"\n"))
        self.assertEqual(json.loads(reply), {"id": "sélection", "ok": True})
        dispatch.assert_called_once_with("select", request["params"])

    def test_notification_executes_without_reply(self):
        dispatch = Mock(side_effect=ValueError("No selected features."))
        frame = b'{"method":"zoomToSelection","params":{"layer":0}}'
        self.assertIsNone(handle_request(frame, dispatch))
        dispatch.assert_called_once_with("zoomToSelection", {"layer": 0})

    def test_errors_echo_zero_id(self):
        dispatch = Mock(side_effect=ValueError("Unknown method."))
        frame = b'{"id":0,"method":"unknown","params":{}}'
        self.assertEqual(
            json.loads(handle_request(frame, dispatch)),
            {"id": 0, "ok": False, "error": "Unknown method."},
        )

    def test_malformed_frames_and_invalid_ids_do_not_execute(self):
        dispatch = Mock()
        for frame in (
            b"not JSON",
            b'{"method":"\xff"}',
            b"[]",
            b'{"method":"move","params":{"lat":NaN}}',
            b'{"id":null,"method":"move","params":{}}',
            b'{"id":true,"method":"move","params":{}}',
        ):
            with self.subTest(frame=frame):
                self.assertIsNone(handle_request(frame, dispatch))
        dispatch.assert_not_called()

    def test_invalid_request_shape_gets_error(self):
        dispatch = Mock()
        reply = handle_request(b'{"id":1,"method":"move","params":[]}', dispatch)
        self.assertFalse(json.loads(reply)["ok"])
        dispatch.assert_not_called()
