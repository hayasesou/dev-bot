from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.contracts.artifact_models import DesignBranch, PlanTask, PlanV2
from app.contracts.artifact_models import TestMappingItem as CriterionTestMappingItem
from app.implementation.candidate_policy import (
    WinnerInput,
    decide_candidates,
    select_winner,
    should_enable_candidate_mode,
)


class CandidatePolicyTests(unittest.TestCase):
    def test_candidate_mode_turns_on_for_low_confidence_multi_branch_plan(self) -> None:
        plan = PlanV2(
            goal="goal",
            acceptance_criteria=["ac1"],
            out_of_scope=[],
            candidate_files=["app/x.py"],
            tasks=[PlanTask(id="T1", summary="Do it", files=["app/x.py"], done_when="done")],
            design_branches=[
                DesignBranch(id="primary", summary="main"),
                DesignBranch(id="alt1", summary="alt"),
            ],
            test_mapping=[CriterionTestMappingItem(criterion="ac1", tests=["tests/test_x.py"])],
            verification_profile="python-basic",
            planner_confidence=0.70,
        )

        self.assertTrue(should_enable_candidate_mode(plan, rework_count=0))
        self.assertEqual(["primary", "alt1"], decide_candidates(plan, rework_count=0).candidate_ids)

    def test_candidate_mode_stays_single_for_high_confidence_plan(self) -> None:
        plan = PlanV2(
            goal="goal",
            acceptance_criteria=["ac1"],
            out_of_scope=[],
            candidate_files=["app/x.py"],
            tasks=[PlanTask(id="T1", summary="Do it", files=["app/x.py"], done_when="done")],
            design_branches=[DesignBranch(id="primary", summary="main")],
            test_mapping=[CriterionTestMappingItem(criterion="ac1", tests=["tests/test_x.py"])],
            verification_profile="python-basic",
            planner_confidence=0.95,
        )

        self.assertFalse(should_enable_candidate_mode(plan, rework_count=0))
        self.assertEqual(["primary"], decide_candidates(plan, rework_count=0).candidate_ids)

    def test_candidate_mode_turns_on_for_low_confidence_without_design_branches(self) -> None:
        plan = PlanV2(
            goal="goal",
            acceptance_criteria=["ac1"],
            out_of_scope=[],
            candidate_files=["app/x.py"],
            tasks=[PlanTask(id="T1", summary="Do it", files=["app/x.py"], done_when="done")],
            design_branches=[],
            test_mapping=[CriterionTestMappingItem(criterion="ac1", tests=["tests/test_x.py"])],
            verification_profile="python-basic",
            planner_confidence=0.70,
        )

        self.assertTrue(should_enable_candidate_mode(plan, rework_count=0))
        self.assertEqual(["primary", "alt1"], decide_candidates(plan, rework_count=0).candidate_ids)

    def test_candidate_mode_respects_custom_thresholds(self) -> None:
        plan = PlanV2(
            goal="goal",
            acceptance_criteria=["ac1"],
            out_of_scope=[],
            candidate_files=["app/x.py"],
            tasks=[PlanTask(id="T1", summary="Do it", files=["app/x.py"], done_when="done")],
            design_branches=[DesignBranch(id="primary", summary="main")],
            test_mapping=[CriterionTestMappingItem(criterion="ac1", tests=["tests/test_x.py"])],
            verification_profile="python-basic",
            planner_confidence=0.70,
        )

        self.assertFalse(
            should_enable_candidate_mode(
                plan,
                rework_count=0,
                rework_count_gte=2,
                planner_confidence_lt=0.50,
            )
        )
        self.assertEqual(
            ["primary"],
            decide_candidates(
                plan,
                rework_count=0,
                rework_count_gte=2,
                planner_confidence_lt=0.50,
            ).candidate_ids,
        )

    def test_candidate_mode_can_require_clear_design_branches(self) -> None:
        plan = PlanV2(
            goal="goal",
            acceptance_criteria=["ac1"],
            out_of_scope=[],
            candidate_files=["app/x.py"],
            tasks=[PlanTask(id="T1", summary="Do it", files=["app/x.py"], done_when="done")],
            design_branches=[DesignBranch(id="primary", summary="main")],
            test_mapping=[CriterionTestMappingItem(criterion="ac1", tests=["tests/test_x.py"])],
            verification_profile="python-basic",
            planner_confidence=0.70,
        )

        self.assertFalse(
            should_enable_candidate_mode(
                plan,
                rework_count=0,
                require_clear_design_branches=True,
            )
        )
        self.assertEqual(
            ["primary"],
            decide_candidates(
                plan,
                rework_count=0,
                require_clear_design_branches=True,
            ).candidate_ids,
        )

    def test_ineligible_candidate_is_excluded_when_hard_checks_fail(self) -> None:
        winner = select_winner(
            [
                WinnerInput(
                    candidate_id="primary",
                    verification=SimpleNamespace(hard_checks_pass=False, failure_type="hard_check_failed"),
                    review=SimpleNamespace(high_count=0, medium_count=0),
                    scope=SimpleNamespace(unexpected_file_count=0, protected_path_violations=False),
                    proof=SimpleNamespace(complete=True, missing_artifacts=[]),
                ),
                WinnerInput(
                    candidate_id="alt1",
                    verification=SimpleNamespace(hard_checks_pass=True, failure_type=None),
                    review=SimpleNamespace(high_count=0, medium_count=0),
                    scope=SimpleNamespace(unexpected_file_count=0, protected_path_violations=False),
                    proof=SimpleNamespace(complete=True, missing_artifacts=[]),
                ),
            ]
        )

        self.assertEqual("alt1", winner)

    def test_ineligible_candidate_is_excluded_when_proof_incomplete(self) -> None:
        winner = select_winner(
            [
                WinnerInput(
                    candidate_id="primary",
                    verification=SimpleNamespace(hard_checks_pass=True, failure_type=None),
                    review=SimpleNamespace(high_count=0, medium_count=0),
                    scope=SimpleNamespace(unexpected_file_count=0, protected_path_violations=False),
                    proof=SimpleNamespace(complete=False, missing_artifacts=["review_findings.json"]),
                ),
                WinnerInput(
                    candidate_id="alt1",
                    verification=SimpleNamespace(hard_checks_pass=True, failure_type=None),
                    review=SimpleNamespace(high_count=0, medium_count=0),
                    scope=SimpleNamespace(unexpected_file_count=0, protected_path_violations=False),
                    proof=SimpleNamespace(complete=True, missing_artifacts=[]),
                ),
            ]
        )

        self.assertEqual("alt1", winner)

    def test_winner_prefers_lower_review_severity_vector(self) -> None:
        winner = select_winner(
            [
                WinnerInput(
                    candidate_id="primary",
                    verification=SimpleNamespace(hard_checks_pass=True, failure_type=None),
                    review=SimpleNamespace(high_count=1, medium_count=0),
                    scope=SimpleNamespace(unexpected_file_count=0, protected_path_violations=False),
                    proof=SimpleNamespace(complete=True, missing_artifacts=[]),
                ),
                WinnerInput(
                    candidate_id="alt1",
                    verification=SimpleNamespace(hard_checks_pass=True, failure_type=None),
                    review=SimpleNamespace(high_count=0, medium_count=1),
                    scope=SimpleNamespace(unexpected_file_count=0, protected_path_violations=False),
                    proof=SimpleNamespace(complete=True, missing_artifacts=[]),
                ),
            ]
        )

        self.assertEqual("alt1", winner)

    def test_winner_uses_unexpected_file_count_as_second_key(self) -> None:
        winner = select_winner(
            [
                WinnerInput(
                    candidate_id="primary",
                    verification=SimpleNamespace(hard_checks_pass=True, failure_type=None),
                    review=SimpleNamespace(high_count=0, medium_count=0),
                    scope=SimpleNamespace(unexpected_file_count=2, protected_path_violations=False),
                    proof=SimpleNamespace(complete=True, missing_artifacts=[]),
                ),
                WinnerInput(
                    candidate_id="alt1",
                    verification=SimpleNamespace(hard_checks_pass=True, failure_type=None),
                    review=SimpleNamespace(high_count=0, medium_count=0),
                    scope=SimpleNamespace(unexpected_file_count=0, protected_path_violations=False),
                    proof=SimpleNamespace(complete=True, missing_artifacts=[]),
                ),
            ]
        )

        self.assertEqual("alt1", winner)
