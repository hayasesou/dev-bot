from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.agent_sdk_client import ClaudeAgentClient
from app.config import Settings


READ_ONLY_TOOLS = ["Read", "Grep", "Glob"]

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "goal": {"type": "string"},
        "background": {"type": "string"},
        "in_scope": {"type": "array", "items": {"type": "string"}},
        "out_of_scope": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "design": {"type": "array", "items": {"type": "string"}},
        "tasks": {"type": "array", "items": {"type": "string"}},
        "migration_plan": {"type": "array", "items": {"type": "string"}},
        "test_strategy": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "schema_version",
        "goal",
        "in_scope",
        "acceptance_criteria",
        "tasks",
        "test_strategy",
        "risks",
    ],
}

TEST_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "test_cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "purpose": {"type": "string"},
                    "type": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "files_to_add_or_change": {"type": "array", "items": {"type": "string"}},
                    "links_to_acceptance": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "purpose", "type", "steps"],
            },
        },
        "db_strategy": {
            "type": "object",
            "properties": {
                "needs_db": {"type": "boolean"},
                "engine": {"type": "string"},
                "migration_apply_cmd": {"type": "string"},
                "migration_rollback_cmd": {"type": "string"},
                "notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["needs_db", "notes"],
        },
        "commands": {
            "type": "object",
            "properties": {
                "setup": {"type": "array", "items": {"type": "string"}},
                "test": {"type": "array", "items": {"type": "string"}},
                "lint": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["setup", "test", "lint"],
        },
    },
    "required": ["schema_version", "test_cases", "db_strategy", "commands"],
}

PLAN_SYSTEM_PROMPT = """あなたはソフトウェア開発の planning エージェントです。
与えられた要件と既存リポジトリを調査し、実装前レビュー用の plan.json を作成してください。

必須ルール:
- 使ってよいのは Read / Grep / Glob のみ
- ファイル編集、コマンド実行、外部アクセスは禁止
- 実装案は既存コードに沿って最小変更で設計する
- 未確定事項は assumptions または risks に残す
- migration が必要な可能性があれば migration_plan に明記する
- JSON 以外は返さない
"""

TEST_PLAN_SYSTEM_PROMPT = """あなたはソフトウェア開発の test planning エージェントです。
与えられた plan.json と既存リポジトリ情報をもとに、実装前レビュー用の test_plan.json を作成してください。

必須ルール:
- 使ってよいのは Read / Grep / Glob のみ
- ファイル編集、コマンド実行、外部アクセスは禁止
- acceptance criteria と 1 対 1 以上で結びつくテスト観点を作る
- DB や migration が関わる場合は db_strategy に明記する
- setup/test/lint コマンドは repo_profile に合わせて現実的に書く
- JSON 以外は返さない
"""


@dataclass(frozen=True)
class PlanningArtifacts:
    repo_profile: dict[str, Any]
    plan: dict[str, Any]
    test_plan: dict[str, Any]


class PlanningAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_artifacts(self, *, workspace: str, summary: dict[str, Any], repo_profile: dict[str, Any]) -> PlanningArtifacts:
        client = ClaudeAgentClient(
            api_key=self.settings.anthropic_api_key,
            timeout_seconds=float(300),
        )
        hooks = _build_read_only_hooks()
        common_prompt = (
            "以下の要件サマリーとリポジトリ情報を見て判断してください。\n\n"
            f"requirement_summary:\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n\n"
            f"repo_profile:\n{json.dumps(repo_profile, ensure_ascii=False, indent=2)}\n"
        )
        plan = client.json_response(
            PLAN_SYSTEM_PROMPT,
            (
                f"{common_prompt}\n"
                "plan.json を作成してください。"
                " 特に goal / acceptance_criteria / tasks / risks / test_strategy を具体化してください。"
            ),
            cwd=workspace,
            max_turns=4,
            allowed_tools=READ_ONLY_TOOLS,
            permission_mode="default",
            setting_sources=["project"],
            hooks=hooks,
            output_schema=PLAN_SCHEMA,
        )
        test_plan = client.json_response(
            TEST_PLAN_SYSTEM_PROMPT,
            (
                f"{common_prompt}\n"
                f"plan.json:\n{json.dumps(plan, ensure_ascii=False, indent=2)}\n\n"
                "test_plan.json を作成してください。"
            ),
            cwd=workspace,
            max_turns=4,
            allowed_tools=READ_ONLY_TOOLS,
            permission_mode="default",
            setting_sources=["project"],
            hooks=hooks,
            output_schema=TEST_PLAN_SCHEMA,
        )
        return PlanningArtifacts(repo_profile=repo_profile, plan=plan, test_plan=test_plan)


def _build_read_only_hooks() -> dict[str, list[HookMatcher]]:
    from claude_agent_sdk import HookMatcher

    async def deny_non_read_only(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        del tool_use_id, context
        tool_name = str(input_data.get("tool_name", ""))
        if tool_name in READ_ONLY_TOOLS:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"`{tool_name}` is disabled during planning",
            }
        }

    return {
        "PreToolUse": [HookMatcher(hooks=[deny_non_read_only])],
    }
