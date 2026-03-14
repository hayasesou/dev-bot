from __future__ import annotations

import tempfile
import unittest

from app.state_store import FileStateStore


class FileStateStoreAttemptTests(unittest.TestCase):
    def test_create_execution_run_does_not_double_increment_attempt_count_after_create_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileStateStore(tmpdir)
            store.create_run(thread_id=1, parent_message_id=10, channel_id=20)
            issue_key = store.bind_issue(1, "owner/repo", 42)

            store.create_attempt(issue_key)
            store.create_execution_run(issue_key)

            self.assertEqual(1, store.load_meta(issue_key)["attempt_count"])
