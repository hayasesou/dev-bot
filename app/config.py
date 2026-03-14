from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

load_dotenv()


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    openai_api_key: str = ""
    discord_bot_token: str = Field(min_length=1)
    discord_guild_id: str = Field(min_length=1)
    discord_status_channel_id: str = Field(min_length=1)
    requirements_channel_id: str = ""
    workspace_root: str = "/tmp/dev-bot-workspaces"
    state_dir: str = "./runs"
    log_level: str = "INFO"
    github_app_id: str = Field(min_length=1)
    github_app_private_key_path: str = Field(min_length=1)
    github_app_installation_id: str = Field(min_length=1)
    github_owner: str = ""
    github_repo: str = ""
    github_project_id: str = ""
    github_project_state_field_id: str = ""
    github_project_state_option_ids: str = ""
    github_project_plan_field_id: str = ""
    github_project_plan_option_ids: str = ""
    github_token: str = ""
    anthropic_api_key: str = ""
    planning_lane_enabled: bool = True
    max_implementation_iterations: int = 5
    max_concurrent_runs: int = 5
    codex_bin: str = "codex"
    codex_app_server_command: str = "codex app-server"
    codex_model: str = "gpt-5.4"
    claude_agent_max_buffer_size: int = 5 * 1024 * 1024
    approval_timeout_seconds: int = 900
    scheduler_poll_interval_seconds: int = 15

    @field_validator(
        "discord_bot_token",
        "discord_guild_id",
        "discord_status_channel_id",
        "github_app_id",
        "github_app_private_key_path",
        "github_app_installation_id",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator(
        "workspace_root",
        "state_dir",
        "requirements_channel_id",
        "github_owner",
        "github_repo",
        "github_project_id",
        "github_project_state_field_id",
        "github_project_state_option_ids",
        "github_project_plan_field_id",
        "github_project_plan_option_ids",
        "log_level",
        "codex_app_server_command",
        "codex_model",
    )
    @classmethod
    def _strip_optional(cls, value: str) -> str:
        return value.strip()

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", ""),
            discord_guild_id=os.getenv("DISCORD_GUILD_ID", ""),
            discord_status_channel_id=os.getenv("DISCORD_STATUS_CHANNEL_ID", ""),
            requirements_channel_id=os.getenv("REQUIREMENTS_CHANNEL_ID", ""),
            workspace_root=os.getenv("WORKSPACE_ROOT", "/tmp/dev-bot-workspaces"),
            state_dir=os.getenv("STATE_DIR", os.getenv("RUNS_ROOT", "./runs")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            github_app_id=os.getenv("GITHUB_APP_ID", ""),
            github_app_private_key_path=os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", ""),
            github_app_installation_id=os.getenv("GITHUB_APP_INSTALLATION_ID", ""),
            github_owner=os.getenv("GITHUB_OWNER", ""),
            github_repo=os.getenv("GITHUB_REPO", ""),
            github_project_id=os.getenv("GITHUB_PROJECT_ID", ""),
            github_project_state_field_id=os.getenv("GITHUB_PROJECT_STATE_FIELD_ID", ""),
            github_project_state_option_ids=os.getenv("GITHUB_PROJECT_STATE_OPTION_IDS", ""),
            github_project_plan_field_id=os.getenv("GITHUB_PROJECT_PLAN_FIELD_ID", ""),
            github_project_plan_option_ids=os.getenv("GITHUB_PROJECT_PLAN_OPTION_IDS", ""),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            planning_lane_enabled=_env_flag("PLANNING_LANE_ENABLED", True),
            max_implementation_iterations=_parse_int("MAX_IMPLEMENTATION_ITERATIONS", 5),
            max_concurrent_runs=_parse_int("MAX_CONCURRENT_RUNS", 5),
            codex_bin=os.getenv("CODEX_BIN", "codex"),
            codex_app_server_command=os.getenv("CODEX_APP_SERVER_COMMAND", "codex app-server"),
            codex_model=os.getenv("CODEX_MODEL", "gpt-5.4"),
            claude_agent_max_buffer_size=_parse_int("CLAUDE_AGENT_MAX_BUFFER_SIZE", 5 * 1024 * 1024),
            approval_timeout_seconds=_parse_int("APPROVAL_TIMEOUT_SECONDS", 900),
            scheduler_poll_interval_seconds=_parse_int("SCHEDULER_POLL_INTERVAL_SECONDS", 15),
        )

    @property
    def runs_root(self) -> str:
        return self.state_dir

    def ensure_runtime_paths(self) -> None:
        workspace = Path(self.workspace_root).expanduser()
        workspace.mkdir(parents=True, exist_ok=True)
        if not workspace.is_dir():
            raise RuntimeError(f"WORKSPACE_ROOT is not a directory: {workspace}")

        state_dir = Path(self.state_dir).expanduser()
        state_dir.mkdir(parents=True, exist_ok=True)
        if not state_dir.is_dir():
            raise RuntimeError(f"STATE_DIR is not a directory: {state_dir}")

        key_path = Path(self.github_app_private_key_path).expanduser()
        try:
            key_path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - filesystem errors are environment dependent
            raise RuntimeError(f"GITHUB_APP_PRIVATE_KEY_PATH is not readable: {key_path}") from exc


def validate_settings(settings: Settings) -> list[str]:
    missing: list[str] = []
    required = {
        "DISCORD_BOT_TOKEN": getattr(settings, "discord_bot_token", ""),
        "DISCORD_GUILD_ID": getattr(settings, "discord_guild_id", ""),
        "DISCORD_STATUS_CHANNEL_ID": getattr(settings, "discord_status_channel_id", ""),
        "WORKSPACE_ROOT": getattr(settings, "workspace_root", ""),
        "STATE_DIR": getattr(settings, "state_dir", ""),
        "GITHUB_APP_ID": getattr(settings, "github_app_id", ""),
        "GITHUB_APP_PRIVATE_KEY_PATH": getattr(settings, "github_app_private_key_path", ""),
        "GITHUB_APP_INSTALLATION_ID": getattr(settings, "github_app_installation_id", ""),
    }
    for key, value in required.items():
        if not str(value).strip():
            missing.append(key)
    project_id = str(getattr(settings, "github_project_id", "")).strip()
    if project_id:
        project_required = {
            "GITHUB_PROJECT_STATE_FIELD_ID": getattr(settings, "github_project_state_field_id", ""),
            "GITHUB_PROJECT_STATE_OPTION_IDS": getattr(settings, "github_project_state_option_ids", ""),
            "GITHUB_PROJECT_PLAN_FIELD_ID": getattr(settings, "github_project_plan_field_id", ""),
            "GITHUB_PROJECT_PLAN_OPTION_IDS": getattr(settings, "github_project_plan_option_ids", ""),
        }
        for key, value in project_required.items():
            if not str(value).strip():
                missing.append(key)
    return missing


def load_settings() -> Settings:
    return Settings.from_env()
