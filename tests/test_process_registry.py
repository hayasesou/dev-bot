from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.process_registry import ProcessRegistry


class ProcessRegistryTests(unittest.TestCase):
    def test_load_reads_legacy_thread_process_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_dir = Path(tmpdir) / "123"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "issue_key": "123",
                "run_id": "run-1",
                "pid": 999,
                "pgid": 999,
                "runner_type": "codex",
            }
            (legacy_dir / "process.json").write_text(json.dumps(payload), encoding="utf-8")

            registry = ProcessRegistry(tmpdir)

            self.assertEqual(payload, registry.load(123))

    def test_register_keeps_multiple_candidate_records_for_same_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProcessRegistry(tmpdir)

            registry.register("owner/repo#1", "run-1", pid=111, runner_type="codex:primary")
            registry.register("owner/repo#1", "run-1", pid=222, runner_type="codex:alt1")

            records = registry.load_all("owner/repo#1")

            self.assertEqual(2, len(records))
            self.assertEqual({"codex:primary", "codex:alt1"}, {str(item["runner_type"]) for item in records})

    def test_unregister_can_remove_single_candidate_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ProcessRegistry(tmpdir)

            registry.register("owner/repo#1", "run-1", pid=111, runner_type="codex:primary")
            registry.register("owner/repo#1", "run-1", pid=222, runner_type="codex:alt1")

            registry.unregister("owner/repo#1", "codex:primary")

            records = registry.load_all("owner/repo#1")
            self.assertEqual(1, len(records))
            self.assertEqual("codex:alt1", records[0]["runner_type"])
