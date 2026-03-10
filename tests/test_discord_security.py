from __future__ import annotations

import time
import unittest

from app.discord_security import CommandRateLimiter, validate_repo_name


class RepoNameValidationTests(unittest.TestCase):
    def test_valid_repo_names(self) -> None:
        self.assertTrue(validate_repo_name("owner/repo"))
        self.assertTrue(validate_repo_name("my-org/my-repo"))
        self.assertTrue(validate_repo_name("user123/project_v2"))
        self.assertTrue(validate_repo_name("a/b"))
        self.assertTrue(validate_repo_name("org.name/repo.name"))

    def test_invalid_repo_names(self) -> None:
        self.assertFalse(validate_repo_name(""))
        self.assertFalse(validate_repo_name("no-slash"))
        self.assertFalse(validate_repo_name("too/many/slashes"))
        self.assertFalse(validate_repo_name("/leading-slash"))
        self.assertFalse(validate_repo_name("trailing-slash/"))
        self.assertFalse(validate_repo_name("owner/ repo"))
        self.assertFalse(validate_repo_name("owner/repo; rm -rf /"))
        self.assertFalse(validate_repo_name("owner/repo$(whoami)"))
        self.assertFalse(validate_repo_name("owner/repo`id`"))

    def test_rejects_path_traversal(self) -> None:
        self.assertFalse(validate_repo_name("../etc/passwd"))
        self.assertFalse(validate_repo_name("owner/.."))


class CommandRateLimiterTests(unittest.TestCase):
    def test_allows_first_call(self) -> None:
        limiter = CommandRateLimiter(max_calls=2, window_seconds=60)
        self.assertTrue(limiter.allow("user1", "run"))

    def test_allows_up_to_max_calls(self) -> None:
        limiter = CommandRateLimiter(max_calls=3, window_seconds=60)
        self.assertTrue(limiter.allow("user1", "run"))
        self.assertTrue(limiter.allow("user1", "run"))
        self.assertTrue(limiter.allow("user1", "run"))
        self.assertFalse(limiter.allow("user1", "run"))

    def test_different_users_have_separate_limits(self) -> None:
        limiter = CommandRateLimiter(max_calls=1, window_seconds=60)
        self.assertTrue(limiter.allow("user1", "run"))
        self.assertTrue(limiter.allow("user2", "run"))
        self.assertFalse(limiter.allow("user1", "run"))

    def test_different_commands_have_separate_limits(self) -> None:
        limiter = CommandRateLimiter(max_calls=1, window_seconds=60)
        self.assertTrue(limiter.allow("user1", "run"))
        self.assertTrue(limiter.allow("user1", "plan"))
        self.assertFalse(limiter.allow("user1", "run"))

    def test_expired_entries_are_cleaned(self) -> None:
        limiter = CommandRateLimiter(max_calls=1, window_seconds=0.05)
        self.assertTrue(limiter.allow("user1", "run"))
        self.assertFalse(limiter.allow("user1", "run"))
        time.sleep(0.06)
        self.assertTrue(limiter.allow("user1", "run"))

    def test_remaining_returns_correct_count(self) -> None:
        limiter = CommandRateLimiter(max_calls=3, window_seconds=60)
        self.assertEqual(limiter.remaining("user1", "run"), 3)
        limiter.allow("user1", "run")
        self.assertEqual(limiter.remaining("user1", "run"), 2)
        limiter.allow("user1", "run")
        self.assertEqual(limiter.remaining("user1", "run"), 1)
