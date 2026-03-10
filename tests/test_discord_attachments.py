from __future__ import annotations

import unittest

try:
    from app.discord_adapter import _json_safe_value
except ModuleNotFoundError:  # pragma: no cover - depends on local test env
    _json_safe_value = None


@unittest.skipIf(_json_safe_value is None, "_json_safe_value is unavailable")
class DiscordAdapterHelpersTests(unittest.TestCase):
    def test_json_safe_value_decodes_bytes_recursively(self) -> None:
        payload = {
            "session_id": b"sess_123",
            "nested": [b"abc", {"value": b"xyz"}],
        }

        normalized = _json_safe_value(payload)

        self.assertEqual("sess_123", normalized["session_id"])
        self.assertEqual("abc", normalized["nested"][0])
        self.assertEqual("xyz", normalized["nested"][1]["value"])
