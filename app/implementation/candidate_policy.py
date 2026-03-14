from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.contracts.artifact_models import PlanV2


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    enabled: bool
    candidate_ids: list[str]


@dataclass(frozen=True, slots=True)
class WinnerInput:
    candidate_id: str
    verification: Any
    review: Any
    scope: Any
    proof: Any
    diff_size: int = 0
    duration_ms: int = 0


def should_enable_candidate_mode(
    plan: PlanV2,
    rework_count: int,
    *,
    rework_count_gte: int = 1,
    planner_confidence_lt: float = 0.75,
    require_clear_design_branches: bool = False,
) -> bool:
    if require_clear_design_branches and len(plan.design_branches) < 2:
        return False
    return rework_count >= rework_count_gte or plan.planner_confidence < planner_confidence_lt


def decide_candidates(
    plan: PlanV2,
    rework_count: int,
    *,
    rework_count_gte: int = 1,
    planner_confidence_lt: float = 0.75,
    require_clear_design_branches: bool = False,
) -> CandidateDecision:
    if should_enable_candidate_mode(
        plan,
        rework_count,
        rework_count_gte=rework_count_gte,
        planner_confidence_lt=planner_confidence_lt,
        require_clear_design_branches=require_clear_design_branches,
    ):
        return CandidateDecision(enabled=True, candidate_ids=["primary", "alt1"])
    return CandidateDecision(enabled=False, candidate_ids=["primary"])


def severity_vector(review: Any) -> tuple[int, int, int, int]:
    if hasattr(review, "severity_counts"):
        counts = review.severity_counts
        if isinstance(counts, dict):
            return (
                int(counts.get("critical", 0)),
                int(counts.get("high", 0)),
                int(counts.get("medium", 0)),
                int(counts.get("low", 0)),
            )
    return (
        int(getattr(review, "critical_count", 0)),
        int(getattr(review, "high_count", 0)),
        int(getattr(review, "medium_count", 0)),
        int(getattr(review, "low_count", 0)),
    )


def eligible(candidate: WinnerInput) -> bool:
    return (
        bool(getattr(candidate.verification, "hard_checks_pass", False))
        and bool(getattr(candidate.proof, "complete", False))
        and not bool(getattr(candidate.scope, "protected_path_violations", False))
    )


def candidate_rank_tuple(candidate: WinnerInput) -> tuple[Any, ...]:
    failure_type = getattr(candidate.verification, "failure_type", None)
    missing_artifacts = getattr(candidate.proof, "missing_artifacts", [])
    plan_alignment_ok = bool(getattr(candidate.review, "plan_alignment_ok", True))
    return (
        severity_vector(candidate.review),
        0 if plan_alignment_ok else 1,
        int(getattr(candidate.scope, "unexpected_file_count", 0)),
        len(missing_artifacts) if isinstance(missing_artifacts, list) else 0,
        0 if failure_type in (None, "") else 1,
        int(candidate.diff_size),
        int(candidate.duration_ms),
    )


def exact_tie(a: WinnerInput, b: WinnerInput) -> bool:
    return candidate_rank_tuple(a) == candidate_rank_tuple(b)


def select_winner(candidates: list[WinnerInput]) -> str:
    ranked = [candidate for candidate in candidates if eligible(candidate)]
    if not ranked:
        raise ValueError("No eligible candidates")
    ranked.sort(key=candidate_rank_tuple)
    return ranked[0].candidate_id
