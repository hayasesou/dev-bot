from __future__ import annotations

import json
import os
import signal
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessRecord:
    issue_key: str
    run_id: str
    pid: int
    pgid: int
    runner_type: str


class ProcessRegistry:
    def __init__(self, runs_root: str) -> None:
        self.root = Path(runs_root) / "processes"
        self.root.mkdir(parents=True, exist_ok=True)

    def register(self, issue_key: str | int, run_id: str, pid: int, runner_type: str) -> ProcessRecord:
        key = str(issue_key)
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = pid
        record = ProcessRecord(
            issue_key=key,
            run_id=run_id,
            pid=pid,
            pgid=pgid,
            runner_type=runner_type,
        )
        records = [item for item in self.load_all(key) if item.get("runner_type") != runner_type]
        records.append(asdict(record))
        self._write_records(key, records)
        return record

    def unregister(self, issue_key: str | int, runner_type: str | None = None) -> None:
        key = str(issue_key)
        path = self._record_path(key)
        if not path.exists():
            return
        if runner_type is None:
            path.unlink()
            return
        remaining = [item for item in self.load_all(key) if item.get("runner_type") != runner_type]
        if remaining:
            self._write_records(key, remaining)
            return
        path.unlink()

    def load(self, issue_key: str | int) -> dict[str, object]:
        key = str(issue_key)
        path = self._record_path(key)
        if not path.exists():
            legacy = self._legacy_record_path(key)
            if not legacy.exists():
                return {}
            return json.loads(legacy.read_text(encoding="utf-8"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            records = payload.get("records") or []
            if records:
                latest = records[-1]
                if isinstance(latest, dict):
                    return latest
            return {}
        return payload

    def load_all(self, issue_key: str | int) -> list[dict[str, object]]:
        key = str(issue_key)
        path = self._record_path(key)
        if not path.exists():
            payload = self.load(key)
            return [payload] if payload else []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            return [item for item in payload["records"] if isinstance(item, dict)]
        if isinstance(payload, dict) and payload:
            return [payload]
        return []

    def terminate(self, issue_key: str | int) -> bool:
        payloads = self.load_all(issue_key)
        if not payloads:
            return False
        stopped = False
        for payload in payloads:
            pgid = self._int_value(payload.get("pgid"))
            pid = self._int_value(payload.get("pid"))
            try:
                if pgid > 0:
                    os.killpg(pgid, signal.SIGTERM)
                    stopped = True
                elif pid > 0:
                    os.kill(pid, signal.SIGTERM)
                    stopped = True
            except ProcessLookupError:
                continue
        self.unregister(issue_key)
        return stopped

    def is_active(self, issue_key: str | int) -> bool:
        payloads = self.load_all(issue_key)
        if not payloads:
            return False
        active_records: list[dict[str, object]] = []
        for payload in payloads:
            pgid = self._int_value(payload.get("pgid"))
            pid = self._int_value(payload.get("pid"))
            try:
                if pgid > 0:
                    os.killpg(pgid, 0)
                    active_records.append(payload)
                    continue
                if pid > 0:
                    os.kill(pid, 0)
                    active_records.append(payload)
            except ProcessLookupError:
                continue
            except PermissionError:
                active_records.append(payload)
        if active_records:
            if len(active_records) != len(payloads):
                self._write_records(str(issue_key), active_records)
            return True
        self.unregister(issue_key)
        return False

    def _record_path(self, issue_key: str) -> Path:
        safe_key = issue_key.replace("/", "__").replace("#", "__")
        return self.root / f"{safe_key}.json"

    def _legacy_record_path(self, issue_key: str) -> Path:
        return self.root.parent / issue_key / "process.json"

    def _write_records(self, issue_key: str, records: list[dict[str, object]]) -> None:
        payload: dict[str, object]
        if len(records) == 1:
            payload = records[0]
        else:
            payload = {"records": records}
        self._record_path(issue_key).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _int_value(self, value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0
