from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import Settings


class WorkspaceManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(settings.workspace_root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare(self, repo_full_name: str, issue_number: int, thread_id: int) -> dict:
        run_root, workspace = self._prepare_root(repo_full_name, thread_id, mode="run")
        branch_name = f"agent/issue-{issue_number}-thread-{thread_id}"
        self._run(["git", "clone", self._clone_url(repo_full_name), str(workspace)])
        default_branch = self._capture(["git", "-C", str(workspace), "remote", "show", "origin"])
        head_branch = "main"
        for line in default_branch.splitlines():
            if "HEAD branch:" in line:
                head_branch = line.split(":", 1)[1].strip()
                break
        self._run(["git", "-C", str(workspace), "checkout", "-b", branch_name, f"origin/{head_branch}"])
        self._run(["git", "-C", str(workspace), "config", "user.name", "dev-bot"])
        self._run(["git", "-C", str(workspace), "config", "user.email", "dev-bot@example.local"])
        return {
            "workspace": str(workspace),
            "branch_name": branch_name,
            "base_branch": head_branch,
            "run_root": str(run_root),
            "artifacts_dir": str(run_root / "artifacts"),
        }

    def prepare_plan_workspace(self, repo_full_name: str, thread_id: int) -> dict:
        run_root, workspace = self._prepare_root(repo_full_name, thread_id, mode="plan")
        self._run(["git", "clone", "--depth", "1", self._clone_url(repo_full_name), str(workspace)])
        default_branch = self._capture(["git", "-C", str(workspace), "remote", "show", "origin"])
        head_branch = "main"
        for line in default_branch.splitlines():
            if "HEAD branch:" in line:
                head_branch = line.split(":", 1)[1].strip()
                break
        return {
            "workspace": str(workspace),
            "base_branch": head_branch,
            "run_root": str(run_root),
        }

    def push_branch(self, workspace: str, branch_name: str) -> None:
        self._run(["git", "-C", workspace, "push", "-u", "origin", branch_name])

    def _prepare_root(self, repo_full_name: str, thread_id: int, *, mode: str) -> tuple[Path, Path]:
        owner, repo = repo_full_name.split("/", 1)
        run_root = self.root / f"{owner}-{repo}" / f"thread-{thread_id}" / mode
        if run_root.exists():
            shutil.rmtree(run_root)
        run_root.mkdir(parents=True, exist_ok=True)
        workspace = run_root / "workspace"
        return run_root, workspace

    def _clone_url(self, repo_full_name: str) -> str:
        return f"https://x-access-token:{self.settings.github_token}@github.com/{repo_full_name}.git"

    def _run(self, cmd: list[str]) -> None:
        subprocess.run(cmd, check=True)

    def _capture(self, cmd: list[str]) -> str:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return completed.stdout
