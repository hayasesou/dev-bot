from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.state_store import FileStateStore


class FileStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = FileStateStore(self.tempdir.name)
        self.store.create_run(thread_id=1, parent_message_id=10, channel_id=20)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_create_execution_run_updates_meta(self) -> None:
        run_id = self.store.create_execution_run(1)

        meta = self.store.load_meta(1)
        self.assertEqual(run_id, meta["current_run_id"])
        self.assertEqual(1, meta["attempt_count"])

    def test_write_execution_artifact_updates_thread_and_run_scope(self) -> None:
        run_id = self.store.create_execution_run(1)
        self.store.write_execution_artifact(1, "plan.json", {"goal": "x"}, run_id)

        self.assertEqual({"goal": "x"}, self.store.load_artifact(1, "plan.json"))
        self.assertEqual({"goal": "x"}, self.store.load_execution_artifact(1, "plan.json", run_id))

    def test_record_failure_writes_agent_and_last_failure(self) -> None:
        payload = self.store.record_failure(
            1,
            stage="plan_generation",
            message="Claude Agent SDK did not return valid JSON.",
            details={
                "repo": "owner/repo",
                "prompt_kind": "plan",
                "session_id": "sess_123",
                "raw_response": "Let me explore",
            },
            stderr=["line1", "line2"],
        )

        self.assertEqual("plan_generation", payload["stage"])
        self.assertEqual("sess_123", payload["details"]["session_id"])
        self.assertEqual(payload, self.store.load_artifact(1, "agent_failure.json"))
        self.assertEqual(payload, self.store.load_artifact(1, "last_failure.json"))

    def test_record_failure_masks_tokens_in_stderr(self) -> None:
        payload = self.store.record_failure(
            1,
            stage="plan_generation",
            message="failed",
            stderr=[
                "Git remote URL: https://x-access-token:secret123@github.com/owner/repo.git",
                "Authorization: Bearer topsecret",
            ],
        )

        self.assertIn("https://[REDACTED]@github.com/owner/repo.git", payload["stderr"][0])
        self.assertNotIn("secret123", payload["stderr"][0])
        self.assertIn("Authorization: [REDACTED]", payload["stderr"][1])

    def test_record_activity_updates_current_and_history(self) -> None:
        payload = self.store.record_activity(
            1,
            phase="workspace",
            summary="workspace ready",
            status="running",
            run_id="run_123",
            details={"path": "/tmp/workspace"},
        )

        self.assertEqual(payload, self.store.load_artifact(1, "current_activity.json"))
        history = self.store.load_artifact(1, "activity_history.json")
        self.assertEqual(1, len(history["items"]))
        self.assertEqual("workspace", history["items"][0]["phase"])

    def test_write_debug_artifact_normalizes_bytes_and_tracks_raw_types(self) -> None:
        path = self.store.write_debug_artifact(
            1,
            "response.json",
            {
                "session_id": b"sess_bytes",
                "structured_output": {"payload": (b"chunk",)},
            },
        )

        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual("sess_bytes", saved["session_id"])
        self.assertEqual(["chunk"], saved["structured_output"]["payload"])
        self.assertEqual("bytes", saved["raw_value_types"]["$.session_id"])

    def test_clear_debug_artifacts_removes_raw_directory(self) -> None:
        self.store.write_debug_artifact(1, "response.json", {"ok": True})

        self.store.clear_debug_artifacts(1)

        self.assertEqual([], self.store.list_debug_artifacts(1))

    def test_bind_issue_persists_issue_key(self) -> None:
        issue_key = self.store.bind_issue(1, "owner/repo", 42)

        meta = self.store.load_meta(1)

        self.assertEqual("owner/repo#42", issue_key)
        self.assertEqual("owner/repo#42", meta["issue_key"])
        self.assertEqual("owner/repo", meta["github_repo"])
        self.assertEqual("42", meta["issue_number"])

    def test_bind_issue_promotes_planning_artifacts_to_issue_latest(self) -> None:
        self.store.write_artifact(1, "requirement_summary.json", {"goal": "ship"})
        self.store.write_artifact(1, "plan.json", {"steps": ["one"]})
        self.store.write_artifact(1, "test_plan.json", {"checks": ["tests"]})
        self.store.append_message(1, "user", "hello")

        issue_key = self.store.bind_issue(1, "owner/repo", 42)

        self.assertEqual({"goal": "ship"}, self.store.load_artifact(issue_key, "requirement_summary.json"))
        self.assertEqual({"steps": ["one"]}, self.store.load_artifact(issue_key, "plan.json"))
        self.assertEqual({"checks": ["tests"]}, self.store.load_artifact(issue_key, "test_plan.json"))
        self.assertEqual({"steps": ["one"]}, self.store.load_artifact(1, "plan.json"))
        issue_conversation = (self.store.issue_dir(issue_key) / "conversation.jsonl").read_text(encoding="utf-8")
        self.assertIn("hello", issue_conversation)

    def test_bind_thread_rejects_conflicting_thread_binding(self) -> None:
        self.store.bind_issue(1, "owner/repo", 42)
        self.store.create_run(thread_id=2, parent_message_id=11, channel_id=21)

        with self.assertRaises(RuntimeError):
            self.store.bind_thread(2, "owner/repo#42")

    def test_bind_thread_rejects_rebinding_thread_to_different_issue(self) -> None:
        self.store.bind_issue(1, "owner/repo", 42)
        self.store.create_issue_record("owner/repo#99")

        with self.assertRaises(RuntimeError):
            self.store.bind_thread(1, "owner/repo#99")

    def test_create_attempt_generates_sequential_attempt_ids(self) -> None:
        issue_key = self.store.bind_issue(1, "owner/repo", 42)

        first = self.store.create_attempt(issue_key)
        second = self.store.create_attempt(issue_key)

        self.assertEqual("att-001", first)
        self.assertEqual("att-002", second)
        self.assertEqual("att-002", self.store.current_attempt_id(issue_key))
        self.assertEqual(2, self.store.load_meta(issue_key)["attempt_count"])

    def test_candidate_dir_is_namespaced_by_attempt_and_candidate(self) -> None:
        issue_key = self.store.bind_issue(1, "owner/repo", 42)
        attempt_id = self.store.create_attempt(issue_key)

        path = self.store.candidate_dir(issue_key, attempt_id, "alt1")

        self.assertEqual(
            self.store.issue_dir(issue_key) / "attempts" / attempt_id / "candidates" / "alt1",
            path,
        )

    def test_write_planning_artifact_uses_issue_planning_namespace(self) -> None:
        issue_key = self.store.bind_issue(1, "owner/repo", 42)

        self.store.write_planning_artifact(issue_key, "plan_v2.json", {"version": 2})

        path = self.store.issue_dir(issue_key) / "planning" / "plan_v2.json"
        self.assertEqual({"version": 2}, json.loads(path.read_text(encoding="utf-8")))

    def test_promote_candidate_to_views_copies_candidate_artifacts(self) -> None:
        issue_key = self.store.bind_issue(1, "owner/repo", 42)
        attempt_id = self.store.create_attempt(issue_key)
        self.store.write_candidate_artifact(
            issue_key,
            attempt_id,
            "alt1",
            "verification_result.json",
            {"status": "success", "hard_checks_pass": True},
        )
        self.store.write_candidate_artifact(
            issue_key,
            attempt_id,
            "alt1",
            "verification.json",
            {"status": "pass"},
        )

        self.store.promote_candidate_to_views(issue_key, attempt_id, "alt1")

        self.assertEqual({"status": "pass"}, self.store.load_artifact(issue_key, "verification.json"))
        self.assertEqual(
            {"status": "success", "hard_checks_pass": True},
            self.store.load_artifact(issue_key, "verification_result.json"),
        )
        views_path = self.store.issue_dir(issue_key) / "views" / "verification.json"
        self.assertEqual({"status": "pass"}, json.loads(views_path.read_text(encoding="utf-8")))
