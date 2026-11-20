import io
import json
import unittest
from email.message import Message

from smoke_mcp import json_reply


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = "text/event-stream; charset=utf-8"


class TestEventStream(unittest.TestCase):
    def test_priming_event_before_matching_response(self):
        stream = Response(
            b'id: first\r\ndata:\r\n\r\n'
            b': heartbeat\r\n\r\n'
            b'data: {"jsonrpc":"2.0","id":10,"result":{}}\r\n\r\n'
            b'data: {"jsonrpc":"2.0",\r\ndata: "id":11,"result":{}}\r\n\r\n'
        )
        self.assertEqual(json_reply(stream, 11), {"jsonrpc": "2.0", "id": 11, "result": {}})

    def test_empty_events_do_not_satisfy_request(self):
        with self.assertRaisesRegex(ValueError, "No matching MCP reply"):
            json_reply(Response(b"event: message\ndata: \ndata:\n\n"), 11)

    def test_nonempty_malformed_json_is_not_silenced(self):
        with self.assertRaises(json.JSONDecodeError):
            json_reply(Response(b"data: not-json\n\n"), 11)
