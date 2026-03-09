from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import discord
from discord import app_commands

from app.config import Settings
from app.github_client import GitHubIssueClient
from app.issue_draft import build_issue_body, build_issue_title
from app.pipeline import DevelopmentPipeline
from app.planning_agent import PlanningAgent
from app.repo_profiler import build_repo_profile
from app.requirements_agent import RequirementsAgent
from app.state_store import FileStateStore


DERIVED_ARTIFACTS = (
    "issue.json",
    "pr.json",
    "workspace.json",
    "plan.json",
    "test_plan.json",
    "repo_profile.json",
    "planning_workspace.json",
    "current_activity.json",
    "activity_history.json",
    "agent_failure.json",
    "last_failure.json",
    "agent_result.json",
    "verification_result.json",
    "verification_history.json",
    "final_result.json",
)


class DevBotClient(discord.Client):
    def __init__(self, settings: Settings, state_store: FileStateStore) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.state_store = state_store
        self.requirements_agent = RequirementsAgent(settings=settings)
        self.planning_agent = PlanningAgent(settings=settings)
        self.github_client = GitHubIssueClient(settings.github_token)
        self.pipeline = DevelopmentPipeline(settings=settings, state_store=state_store, github_client=self.github_client)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        plan = app_commands.Command(
            name="plan",
            description="repo を読んで plan.json と test_plan.json を作成します",
            callback=self.plan_command,
        )
        plan.autocomplete("repo")(self.repo_autocomplete)
        self.tree.add_command(plan)

        run = app_commands.Command(
            name="run",
            description="確認済み plan に基づいて Issue 作成と実装を開始します",
            callback=self.run_command,
        )
        run.autocomplete("repo")(self.repo_autocomplete)
        self.tree.add_command(run)

        confirm = app_commands.Command(
            name="confirm",
            description="互換コマンドです。/plan と同じく計画を作成します",
            callback=self.confirm_command,
        )
        confirm.autocomplete("repo")(self.repo_autocomplete)
        self.tree.add_command(confirm)

        self.tree.add_command(
            app_commands.Command(
                name="status",
                description="現在の状態を表示します",
                callback=self.status_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="issue",
                description="作成済みIssueを表示します",
                callback=self.issue_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="pr",
                description="作成済みPRを表示します",
                callback=self.pr_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="abort",
                description="このスレッドの実行中プロセスを停止します",
                callback=self.abort_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="retry",
                description="直前の plan / issue で再実行します",
                callback=self.retry_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="revise",
                description="要件整理を再開し、plan/run の派生成果物をクリアします",
                callback=self.revise_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="diff",
                description="現在の作業差分を表示します",
                callback=self.diff_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="why-failed",
                description="直近の失敗理由を要約します",
                callback=self.why_failed_command,
            )
        )
        self.tree.add_command(
            app_commands.Command(
                name="budget",
                description="直近 run の usage / cost を表示します",
                callback=self.budget_command,
            )
        )
        if self.settings.discord_guild_id:
            guild = discord.Object(id=int(self.settings.discord_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            return
        await self.tree.sync()

    async def on_ready(self) -> None:
        if self.user is None:
            return
        print(f"Logged in as {self.user} ({self.user.id})")

    async def on_message(self, message: discord.Message) -> None:
        print(
            "Received message:",
            {
                "channel_id": message.channel.id,
                "author": str(message.author),
                "author_is_bot": message.author.bot,
                "mentions_bot": self.user in message.mentions if self.user else False,
                "content": message.content,
            },
        )
        if message.author.bot:
            return
        if isinstance(message.channel, discord.Thread):
            await self._handle_thread_message(message)
            return

        await self._handle_requirements_channel_message(message)

    def _build_thread_name(self, content: str) -> str:
        summary = content.replace("\n", " ").strip()
        if len(summary) > 40:
            summary = summary[:40].rstrip() + "..."
        return f"dev-bot | {summary or 'new request'}"

    async def _handle_requirements_channel_message(self, message: discord.Message) -> None:
        if str(message.channel.id) != self.settings.requirements_channel_id:
            print(
                "Ignoring message due to channel mismatch:",
                {
                    "expected": self.settings.requirements_channel_id,
                    "actual": str(message.channel.id),
                },
            )
            return
        if self.user is None or self.user not in message.mentions:
            print("Ignoring message because bot was not mentioned.")
            return

        print("Creating thread for request message.")
        thread = await message.create_thread(
            name=self._build_thread_name(message.content),
            auto_archive_duration=1440,
        )
        self.state_store.create_run(
            thread_id=thread.id,
            parent_message_id=message.id,
            channel_id=message.channel.id,
        )
        self.state_store.append_message(thread.id, "user", message.content)
        reply = await asyncio.to_thread(self.requirements_agent.build_reply, thread.id)
        await thread.send(reply.body)
        self.state_store.append_message(thread.id, "assistant", reply.body)
        self.state_store.update_status(thread.id, reply.status)
        if reply.artifacts:
            self._persist_artifacts(thread.id, reply.artifacts)

    async def _handle_thread_message(self, message: discord.Message) -> None:
        thread_id = message.channel.id
        if not self.state_store.has_run(thread_id):
            print("Ignoring thread message because it is not managed by this bot.")
            return
        if self.pipeline.is_running(thread_id):
            return

        meta = self.state_store.load_meta(thread_id)
        if meta.get("status") in {"plan_ready", "issue_created", "local_running", "completed", "failed", "aborted"}:
            self._clear_execution_artifacts(thread_id)

        self.state_store.append_message(thread_id, "user", message.content)
        reply = await asyncio.to_thread(self.requirements_agent.build_reply, thread_id)
        await message.channel.send(reply.body)
        self.state_store.append_message(thread_id, "assistant", reply.body)
        self.state_store.update_status(thread_id, reply.status)
        if reply.artifacts:
            self._persist_artifacts(thread_id, reply.artifacts)

    def _persist_artifacts(self, thread_id: int, artifacts: dict[str, Any]) -> None:
        summary = artifacts.get("summary")
        if isinstance(summary, dict):
            self.state_store.write_artifact(thread_id, "requirement_summary.json", summary)
        plan = artifacts.get("plan")
        if isinstance(plan, dict):
            self.state_store.write_artifact(thread_id, "plan.json", plan)
        test_plan = artifacts.get("test_plan")
        if isinstance(test_plan, dict):
            self.state_store.write_artifact(thread_id, "test_plan.json", test_plan)
        repo_profile = artifacts.get("repo_profile")
        if isinstance(repo_profile, dict):
            self.state_store.write_artifact(thread_id, "repo_profile.json", repo_profile)
        planning_workspace = artifacts.get("planning_workspace")
        if isinstance(planning_workspace, dict):
            self.state_store.write_artifact(thread_id, "planning_workspace.json", planning_workspace)
        agent_error = artifacts.get("agent_error")
        if isinstance(agent_error, dict):
            self.state_store.write_artifact(thread_id, "agent_error.json", agent_error)

    def _ensure_managed_thread(self, channel: discord.abc.GuildChannel | discord.Thread | None) -> int | None:
        if not isinstance(channel, discord.Thread):
            return None
        if not self.state_store.has_run(channel.id):
            return None
        return channel.id

    async def plan_command(self, interaction: discord.Interaction, repo: str) -> None:
        await self._generate_plan(interaction, repo, alias_used=False)

    async def confirm_command(self, interaction: discord.Interaction, repo: str) -> None:
        await self._generate_plan(interaction, repo, alias_used=True)

    async def run_command(self, interaction: discord.Interaction, repo: str | None = None) -> None:
        await self._start_run(interaction, repo)

    async def status_command(self, interaction: discord.Interaction) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return

        meta = self.state_store.load_meta(thread_id)
        issue = self.state_store.load_artifact(thread_id, "issue.json")
        pr = self.state_store.load_artifact(thread_id, "pr.json")
        summary = self.state_store.load_artifact(thread_id, "requirement_summary.json")
        plan = self.state_store.load_artifact(thread_id, "plan.json")
        test_plan = self.state_store.load_artifact(thread_id, "test_plan.json")
        current_activity = self.state_store.load_artifact(thread_id, "current_activity.json")
        agent_failure = self.state_store.load_artifact(thread_id, "agent_failure.json")
        last_failure = self.state_store.load_artifact(thread_id, "last_failure.json")
        lines = [
            f"status: `{meta.get('status', 'unknown')}`",
            f"thread_id: `{thread_id}`",
            f"running: `{self.pipeline.is_running(thread_id)}`",
        ]
        if meta.get("github_repo"):
            lines.append(f"repo: `{meta.get('github_repo')}`")
        if summary:
            lines.append(f"goal: {summary.get('goal', '(no goal)')}")
        if plan:
            lines.append(f"plan: `{len(plan.get('tasks', []))}` tasks")
        if test_plan:
            lines.append(f"test_plan: `{len(test_plan.get('test_cases', []))}` cases")
        if issue:
            lines.append(f"issue: [#{issue.get('number')}]({issue.get('url')})")
        if pr:
            lines.append(f"pr: [#{pr.get('number')}]({pr.get('url')})")
        if current_activity:
            lines.append(
                "current_activity: "
                f"`{current_activity.get('tool_name', 'unknown')}` {current_activity.get('status', '')} "
                f"- {current_activity.get('summary', '')}"
            )
        if last_failure:
            lines.append(
                "last_failure: "
                f"`{last_failure.get('tool_name', last_failure.get('message', 'unknown'))}` "
                f"- {last_failure.get('summary', last_failure.get('message', ''))}"
            )
        if agent_failure:
            lines.append(f"last_error: {agent_failure.get('message', '')}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    async def issue_command(self, interaction: discord.Interaction) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return

        issue = self.state_store.load_artifact(thread_id, "issue.json")
        if not issue:
            await interaction.response.send_message("まだ Issue は作成されていません。`/run` を実行してください。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Repo: `{issue.get('repo_full_name')}`\nIssue: #{issue.get('number')}\nURL: {issue.get('url')}",
            ephemeral=True,
        )

    async def pr_command(self, interaction: discord.Interaction) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        pr = self.state_store.load_artifact(thread_id, "pr.json")
        if not pr:
            await interaction.response.send_message("まだ PR は作成されていません。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Repo: `{pr.get('repo_full_name')}`\nPR: #{pr.get('number')}\nURL: {pr.get('url')}",
            ephemeral=True,
        )

    async def abort_command(self, interaction: discord.Interaction) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        stopped = await self.pipeline.abort(thread_id)
        self.state_store.update_status(thread_id, "aborted")
        if stopped:
            await interaction.response.send_message("実行中プロセスの停止を要求しました。", ephemeral=True)
            return
        await interaction.response.send_message("アクティブな実行は見つかりませんでしたが、状態は `aborted` に更新しました。", ephemeral=True)

    async def retry_command(self, interaction: discord.Interaction) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        issue = self.state_store.load_artifact(thread_id, "issue.json")
        meta = self.state_store.load_meta(thread_id)
        repo = issue.get("repo_full_name") if isinstance(issue, dict) else meta.get("github_repo")
        await self._start_run(interaction, repo)

    async def revise_command(self, interaction: discord.Interaction) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        if self.pipeline.is_running(thread_id):
            await interaction.response.send_message("実行中です。先に `/abort` してください。", ephemeral=True)
            return
        self._clear_execution_artifacts(thread_id)
        self.state_store.update_meta(
            thread_id,
            status="requirements_dialogue",
            issue_number="",
            pr_number="",
            pr_url="",
            workspace="",
            branch_name="",
            base_branch="",
        )
        await interaction.response.send_message("要件整理を再開しました。修正したい内容をそのまま投稿してください。", ephemeral=True)

    async def diff_command(self, interaction: discord.Interaction, pathspec: str | None = None) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        meta = self.state_store.load_meta(thread_id)
        workspace = str(meta.get("workspace", "")).strip()
        if not workspace or not Path(workspace).exists():
            await interaction.response.send_message("workspace が見つかりません。先に `/run` を実行してください。", ephemeral=True)
            return
        try:
            diff_text = await asyncio.to_thread(self._build_diff_summary, workspace, pathspec or "")
        except subprocess.CalledProcessError as exc:
            await interaction.response.send_message(f"diff の取得に失敗しました: `{exc}`", ephemeral=True)
            return
        await interaction.response.send_message(diff_text, ephemeral=True)

    async def why_failed_command(self, interaction: discord.Interaction) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        verification = self.state_store.load_artifact(thread_id, "verification_result.json")
        last_failure = self.state_store.load_artifact(thread_id, "last_failure.json")
        agent_failure = self.state_store.load_artifact(thread_id, "agent_failure.json")
        lines = ["直近の失敗要約"]
        if isinstance(verification, dict) and verification and not verification.get("success", False):
            lines.append(f"- phase: `{verification.get('phase', 'test')}`")
            lines.append(f"- command: `{verification.get('command', '')}`")
            excerpt = str(verification.get("output", "")).strip()
            if excerpt:
                lines.append(f"- output: ```text\n{excerpt[-1200:]}\n```")
        if isinstance(last_failure, dict) and last_failure:
            lines.append(
                f"- last_failure: `{last_failure.get('tool_name', last_failure.get('message', 'unknown'))}` "
                f"{last_failure.get('summary', last_failure.get('message', ''))}"
            )
        if isinstance(agent_failure, dict) and agent_failure:
            lines.append(f"- agent_error: {agent_failure.get('message', '')}")
        if len(lines) == 1:
            lines.append("- 直近の失敗情報は見つかりませんでした。")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    async def budget_command(self, interaction: discord.Interaction) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        agent_result = self.state_store.load_artifact(thread_id, "agent_result.json")
        final_result = self.state_store.load_artifact(thread_id, "final_result.json")
        result = agent_result if isinstance(agent_result, dict) and agent_result else final_result.get("agent_result", {})
        if not isinstance(result, dict) or not result:
            await interaction.response.send_message("usage / cost 情報はまだありません。", ephemeral=True)
            return
        usage = result.get("usage") or {}
        lines = [
            f"total_cost_usd: `{result.get('total_cost_usd', 'unknown')}`",
            f"session_id: `{result.get('session_id', 'unknown')}`",
        ]
        if isinstance(usage, dict):
            for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                if key in usage:
                    lines.append(f"{key}: `{usage.get(key)}`")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    async def repo_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        try:
            repos = self.github_client.suggest_repositories(current, limit=25)
        except Exception as exc:
            print(f"repo_autocomplete failed: {exc}")
            return []
        return [app_commands.Choice(name=repo, value=repo) for repo in repos]

    async def _generate_plan(self, interaction: discord.Interaction, repo: str, *, alias_used: bool) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        if self.pipeline.is_running(thread_id):
            await interaction.response.send_message("実行中です。先に `/abort` するか完了を待ってください。", ephemeral=True)
            return

        summary = self.state_store.load_artifact(thread_id, "requirement_summary.json")
        if not isinstance(summary, dict) or not summary:
            await interaction.response.send_message("要件サマリーがまだ作成されていません。もう少し会話を続けてください。", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        try:
            artifacts = await asyncio.to_thread(self._build_plan_artifacts, repo, thread_id, summary)
        except Exception as exc:
            await interaction.followup.send(f"plan の生成に失敗しました: `{exc}`", ephemeral=True)
            return

        self._clear_execution_artifacts(thread_id)
        self._persist_artifacts(
            thread_id,
            {
                "plan": artifacts["plan"],
                "test_plan": artifacts["test_plan"],
                "repo_profile": artifacts["repo_profile"],
                "planning_workspace": artifacts["planning_workspace"],
            },
        )
        self.state_store.update_meta(
            thread_id,
            status="plan_ready",
            github_repo=repo,
            base_branch=str(artifacts["planning_workspace"].get("base_branch", "")),
            issue_number="",
            pr_number="",
            pr_url="",
            workspace="",
            branch_name="",
        )
        prefix = "互換コマンド `/confirm` を `/plan` として扱いました。\n\n" if alias_used else ""
        await interaction.followup.send(prefix + self._format_plan_message(repo, artifacts["plan"], artifacts["test_plan"]))

    async def _start_run(self, interaction: discord.Interaction, repo: str | None) -> None:
        thread_id = self._ensure_managed_thread(interaction.channel)
        if thread_id is None:
            await interaction.response.send_message("このコマンドは dev-bot が管理しているスレッド内で実行してください。", ephemeral=True)
            return
        if self.pipeline.is_running(thread_id):
            await interaction.response.send_message("すでに実行中です。`/status` を確認してください。", ephemeral=True)
            return

        summary = self.state_store.load_artifact(thread_id, "requirement_summary.json")
        plan = self.state_store.load_artifact(thread_id, "plan.json")
        test_plan = self.state_store.load_artifact(thread_id, "test_plan.json")
        if not isinstance(summary, dict) or not summary:
            await interaction.response.send_message("要件サマリーが見つかりません。", ephemeral=True)
            return
        if not isinstance(plan, dict) or not plan or not isinstance(test_plan, dict) or not test_plan:
            await interaction.response.send_message("先に `/plan repo:owner/repo` を実行してください。", ephemeral=True)
            return

        meta = self.state_store.load_meta(thread_id)
        issue = self.state_store.load_artifact(thread_id, "issue.json")
        repo_full_name = repo or (issue.get("repo_full_name") if isinstance(issue, dict) else "") or str(meta.get("github_repo", ""))
        if not repo_full_name:
            await interaction.response.send_message("repo を決められませんでした。`/run repo:owner/repo` を指定してください。", ephemeral=True)
            return
        if isinstance(issue, dict) and issue and issue.get("repo_full_name") != repo_full_name:
            self.state_store.delete_artifact(thread_id, "issue.json")
            self.state_store.delete_artifact(thread_id, "pr.json")
            issue = {}

        await interaction.response.defer(thinking=True)
        if not isinstance(issue, dict) or not issue:
            thread_url = interaction.channel.jump_url if isinstance(interaction.channel, discord.Thread) else ""
            title = build_issue_title(summary)
            body = build_issue_body(summary, thread_url)
            try:
                created = await asyncio.to_thread(self.github_client.create_issue, repo_full_name=repo_full_name, title=title, body=body)
            except Exception as exc:
                await interaction.followup.send(f"Issue 作成に失敗しました: `{exc}`", ephemeral=True)
                return
            issue = {
                "repo_full_name": created.repo_full_name,
                "number": created.number,
                "title": created.title,
                "body": created.body,
                "url": created.url,
            }
            self.state_store.write_artifact(thread_id, "issue.json", issue)

        self.state_store.update_meta(
            thread_id,
            status="issue_created",
            github_repo=repo_full_name,
            issue_number=str(issue["number"]),
        )
        started = self.pipeline.start(
            client=self,
            thread=interaction.channel,
            repo_full_name=repo_full_name,
            issue=issue,
        ) if isinstance(interaction.channel, discord.Thread) else False
        if not started:
            await interaction.followup.send("パイプラインの起動に失敗しました。すでに実行中の可能性があります。", ephemeral=True)
            return
        await interaction.followup.send(
            "run を開始しました。\n"
            f"- Repo: `{repo_full_name}`\n"
            f"- Issue: #{issue['number']}\n"
            f"- URL: {issue['url']}"
        )

    def _build_plan_artifacts(self, repo: str, thread_id: int, summary: dict[str, Any]) -> dict[str, Any]:
        planning_workspace = self.pipeline.workspace_manager.prepare_plan_workspace(repo, thread_id)
        repo_profile = build_repo_profile(planning_workspace["workspace"])
        built = self.planning_agent.build_artifacts(
            workspace=planning_workspace["workspace"],
            summary=summary,
            repo_profile=repo_profile,
        )
        return {
            "repo_profile": built.repo_profile,
            "plan": built.plan,
            "test_plan": built.test_plan,
            "planning_workspace": planning_workspace,
        }

    def _format_plan_message(self, repo: str, plan: dict[str, Any], test_plan: dict[str, Any]) -> str:
        tasks = "\n".join(f"- {item}" for item in plan.get("tasks", [])[:6]) or "- なし"
        acceptance = "\n".join(f"- {item}" for item in plan.get("acceptance_criteria", [])[:6]) or "- なし"
        risks = "\n".join(f"- {item}" for item in plan.get("risks", [])[:4]) or "- なし"
        test_cases = "\n".join(
            f"- {case.get('id', 'TC')} {case.get('purpose', '')}"
            for case in test_plan.get("test_cases", [])[:6]
            if isinstance(case, dict)
        ) or "- なし"
        return (
            "plan.json / test_plan.json を生成しました。\n"
            f"- Repo: `{repo}`\n"
            f"- Goal: {plan.get('goal', '(no goal)')}\n\n"
            "Acceptance criteria\n"
            f"{acceptance}\n\n"
            "Tasks\n"
            f"{tasks}\n\n"
            "Test cases\n"
            f"{test_cases}\n\n"
            "Risks\n"
            f"{risks}\n\n"
            "問題なければ `/run` を実行してください。"
        )

    def _clear_execution_artifacts(self, thread_id: int) -> None:
        for filename in DERIVED_ARTIFACTS:
            self.state_store.delete_artifact(thread_id, filename)
        self.state_store.update_meta(
            thread_id,
            issue_number="",
            pr_number="",
            pr_url="",
            workspace="",
            branch_name="",
            base_branch="",
        )

    def _build_diff_summary(self, workspace: str, pathspec: str) -> str:
        status = subprocess.run(
            ["git", "-C", workspace, "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
        if not status.stdout.strip():
            return "作業差分はありません。"
        diff_stat_cmd = ["git", "-C", workspace, "diff", "--stat"]
        diff_name_cmd = ["git", "-C", workspace, "diff", "--name-only"]
        if pathspec:
            diff_stat_cmd.extend(["--", pathspec])
            diff_name_cmd.extend(["--", pathspec])
        diff_stat = subprocess.run(diff_stat_cmd, check=True, capture_output=True, text=True)
        diff_names = subprocess.run(diff_name_cmd, check=True, capture_output=True, text=True)
        names = diff_names.stdout.strip().splitlines()
        return (
            "現在の差分\n"
            f"- files: {len(names)}\n"
            f"- names:\n{chr(10).join(f'  - {line}' for line in names[:20]) or '  - none'}\n\n"
            f"```text\n{diff_stat.stdout.strip()[:1500]}\n```"
        )


def build_client(settings: Settings) -> DevBotClient:
    return DevBotClient(settings=settings, state_store=FileStateStore(runs_root=settings.runs_root))
