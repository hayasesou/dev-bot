"""Integration tests for Orchestrator with InMemoryAdapter and real state store."""

from __future__ import annotations

import asyncio
import tempfile
import unittest

from app.orchestrator import Orchestrator, WorkItem
from app.state_store import FileStateStore
from app.testing.in_memory_adapter import InMemoryAdapter


class OrchestratorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.state_store = FileStateStore(self.tmp)
        self.adapter = InMemoryAdapter()
        self.completed_items: list[WorkItem] = []

    def _init_thread(self, thread_id: int) -> None:
        self.state_store.create_run(thread_id=thread_id, parent_message_id=0, channel_id=0)

    async def _executor(self, item: WorkItem) -> None:
        self.completed_items.append(item)
        channel = self.adapter.register_channel(item.thread_id)
        await channel.send(f"Completed {item.workspace_key}")

    async def test_enqueue_and_execute_with_real_state(self) -> None:
        """Enqueue an item, let it execute, verify state and messages."""
        orchestrator = Orchestrator(self.state_store, self._executor, max_concurrency=2)
        self._init_thread(1)

        item = WorkItem(
            thread_id=1,
            repo_full_name="test/repo",
            issue={"number": 1, "title": "test"},
            workspace_key="test/repo#1",
        )
        accepted = await orchestrator.enqueue(item)
        self.assertTrue(accepted)

        await asyncio.sleep(0.1)

        self.assertEqual(len(self.completed_items), 1)
        self.assertEqual(self.completed_items[0].workspace_key, "test/repo#1")

        # Verify message was sent via adapter
        messages = self.adapter.messages_for(1)
        self.assertTrue(any("Completed" in m for m in messages))

        await orchestrator.drain()

    async def test_concurrent_execution_with_limit(self) -> None:
        """Verify concurrency limit is respected with real execution."""
        max_concurrent = 0
        barrier = asyncio.Event()
        executing: set[int] = set()

        async def tracked_executor(item: WorkItem) -> None:
            nonlocal max_concurrent
            executing.add(item.thread_id)
            max_concurrent = max(max_concurrent, len(executing))
            await barrier.wait()
            executing.discard(item.thread_id)

        orchestrator = Orchestrator(self.state_store, tracked_executor, max_concurrency=2)

        for i in range(5):
            self._init_thread(i)
            await orchestrator.enqueue(
                WorkItem(thread_id=i, repo_full_name="o/r", issue={"number": i}, workspace_key=f"o/r#{i}")
            )

        await asyncio.sleep(0.1)
        self.assertLessEqual(max_concurrent, 2)

        barrier.set()
        await asyncio.sleep(0.3)

        await orchestrator.drain()

    async def test_drain_with_real_state(self) -> None:
        """Verify drain works with real state store."""
        blocker = asyncio.Event()

        async def blocked_executor(item: WorkItem) -> None:
            await blocker.wait()

        orchestrator = Orchestrator(self.state_store, blocked_executor, max_concurrency=1)

        self._init_thread(1)
        self._init_thread(2)

        await orchestrator.enqueue(
            WorkItem(thread_id=1, repo_full_name="o/r", issue={"number": 1}, workspace_key="o/r#1")
        )
        await orchestrator.enqueue(
            WorkItem(thread_id=2, repo_full_name="o/r", issue={"number": 2}, workspace_key="o/r#2")
        )

        await asyncio.sleep(0.05)
        await orchestrator.drain()

        self.assertEqual(orchestrator.pending_count(), 0)
        self.assertEqual(orchestrator.active_count(), 0)
