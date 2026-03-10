"""Integration tests for FileStateStore with real filesystem I/O."""

from __future__ import annotations

import json
import tempfile
import unittest

from app.state_store import FileStateStore


class StateStoreIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.store = FileStateStore(self.tmp)

    def _init_thread(self, thread_id: int) -> None:
        """Initialize a thread with meta.json (required for update_status etc.)."""
        self.store.create_run(thread_id=thread_id, parent_message_id=0, channel_id=0)

    def test_full_lifecycle_create_update_read(self) -> None:
        """Test creating a thread, updating status, writing artifacts, and reading back."""
        thread_id = 100
        self._init_thread(thread_id)
        self.store.update_status(thread_id, "queued")

        meta = self.store.load_meta(thread_id)
        self.assertEqual(meta["status"], "queued")

        self.store.update_status(thread_id, "running")
        meta = self.store.load_meta(thread_id)
        self.assertEqual(meta["status"], "running")

    def test_execution_run_artifacts_persist(self) -> None:
        """Test that execution artifacts are written and readable."""
        thread_id = 200
        self._init_thread(thread_id)
        self.store.update_status(thread_id, "running")
        run_id = self.store.create_execution_run(thread_id)

        artifacts_dir = self.store.execution_artifacts_dir(thread_id, run_id)
        self.assertTrue(artifacts_dir.exists())

        plan = {"goal": "test", "steps": ["step1"]}
        self.store.write_execution_artifact(thread_id, "plan.json", plan, run_id)

        plan_path = artifacts_dir / "plan.json"
        self.assertTrue(plan_path.exists())
        loaded = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["goal"], "test")

    def test_failure_recording_and_masking(self) -> None:
        """Test that failure recording masks sensitive tokens."""
        thread_id = 300
        self._init_thread(thread_id)
        self.store.update_status(thread_id, "running")

        self.store.record_failure(
            thread_id,
            stage="test_stage",
            message="Error with token=ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            details={"extra": "info"},
        )

        last_failure = self.store.load_artifact(thread_id, "last_failure.json")
        self.assertIn("stage", last_failure)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz1234567890", json.dumps(last_failure))

    def test_bind_issue_persists_across_reads(self) -> None:
        """Test that binding an issue is persisted and retrievable."""
        thread_id = 400
        self._init_thread(thread_id)
        self.store.bind_issue(thread_id, "owner/repo", 42)

        meta = self.store.load_meta(thread_id)
        self.assertEqual(meta.get("issue_key"), "owner/repo#42")

    def test_multiple_threads_are_isolated(self) -> None:
        """Test that different threads don't interfere with each other."""
        self._init_thread(1)
        self._init_thread(2)
        self.store.update_status(1, "queued")
        self.store.update_status(2, "running")

        meta1 = self.store.load_meta(1)
        meta2 = self.store.load_meta(2)

        self.assertEqual(meta1["status"], "queued")
        self.assertEqual(meta2["status"], "running")
