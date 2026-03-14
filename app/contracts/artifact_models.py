from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PlanTask:
    id: str
    summary: str
    files: list[str] = field(default_factory=list)
    done_when: str = ""


@dataclass(frozen=True, slots=True)
class DesignBranch:
    id: str
    summary: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    recommended: bool = False


@dataclass(frozen=True, slots=True)
class RiskItem:
    risk: str
    mitigation: str


@dataclass(frozen=True, slots=True)
class TestMappingItem:
    criterion: str
    tests: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PlanV2:
    goal: str
    acceptance_criteria: list[str]
    out_of_scope: list[str]
    version: int = 2
    constraints: list[str] = field(default_factory=list)
    candidate_files: list[str] = field(default_factory=list)
    must_not_touch: list[str] = field(default_factory=list)
    verification_focus: list[str] = field(default_factory=list)
    exploration_required: bool = False
    tasks: list[PlanTask] = field(default_factory=list)
    design_branches: list[DesignBranch] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    test_mapping: list[TestMappingItem] = field(default_factory=list)
    verification_profile: str = ""
    planner_confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class RepoExplorerV1:
    candidate_files: list[str] = field(default_factory=list)
    similar_files: list[str] = field(default_factory=list)
    architectural_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RiskTestPlanV1:
    risks: list[RiskItem] = field(default_factory=list)
    test_mapping: list[TestMappingItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ConstraintReportV1:
    out_of_scope: list[str] = field(default_factory=list)
    protected_paths: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    id: str
    severity: str
    origin: str
    confidence: float
    file: str
    line_start: int
    line_end: int
    claim: str
    evidence: list[str] = field(default_factory=list)
    verifier_status: str = "unverified"
    suggested_fix: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewFindingsV1:
    findings: list[ReviewFinding] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ScopeContract:
    issue_key: str
    attempt_id: str
    version: int = 1
    allowed_paths: list[str] = field(default_factory=list)
    candidate_files: list[str] = field(default_factory=list)
    must_not_touch: list[str] = field(default_factory=list)
    verification_focus: list[str] = field(default_factory=list)
    unexpected_file_policy: str = "report_and_penalize"
    protected_config_default: str = "deny"
    protected_config_allow_label_present: bool = False
    protected_config_allowlist: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AttemptManifest:
    issue_key: str
    attempt_id: str
    trigger: str
    version: int = 1
    rework_of_attempt_id: str | None = None
    plan_version: int = 2
    workflow_hash: str = ""
    plan_hash: str = ""
    scope_contract_hash: str = ""
    candidate_ids: list[str] = field(default_factory=list)
    winner_candidate_id: str | None = None
    status: str = "running"


@dataclass(frozen=True, slots=True)
class CandidateManifest:
    attempt_id: str
    candidate_id: str
    branch_name: str
    workspace: str
    version: int = 1
    strategy_origin: str = "implementation_self_divergence"
    strategy_summary: str = "candidate execution lane"
    reused_from_candidate_id: str | None = None
    reuse_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateStrategy:
    candidate_id: str
    version: int = 1
    candidate_files: list[str] = field(default_factory=list)
    must_not_touch: list[str] = field(default_factory=list)
    verification_focus: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    tests: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    candidate_id: str
    version: int = 1
    status: str = ""
    failure_type: str = ""
    hard_checks_pass: bool = False
    retry_recommended: bool = False
    human_check_recommended: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ReviewResult:
    candidate_id: str
    decision: str
    version: int = 1
    reject_reasons: list[str] = field(default_factory=list)
    severity_counts: dict[str, int] = field(default_factory=dict)
    verified_finding_count: int = 0
    unverified_finding_count: int = 0
    plan_alignment_ok: bool = True
    scope_drift: bool = False
    protected_contract_ok: bool = True
    findings_ref: str = "review_findings.json"


@dataclass(frozen=True, slots=True)
class RepairInstructions:
    candidate_id: str
    version: int = 1
    summary: str = ""
    required_fixes: list[str] = field(default_factory=list)
    optional_fixes: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ScopeAnalysis:
    version: int = 1
    changed_files: list[str] = field(default_factory=list)
    unexpected_files: list[str] = field(default_factory=list)
    unexpected_file_count: int = 0
    must_not_touch: list[str] = field(default_factory=list)
    must_not_touch_violations: list[str] = field(default_factory=list)
    protected_config_default: str = "deny"
    protected_config_patterns: list[str] = field(default_factory=list)
    protected_config_allow_label: str = ""
    protected_config_label_present: bool = False
    protected_config_allowlist: list[str] = field(default_factory=list)
    protected_config_violations: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ProofResult:
    candidate_id: str
    version: int = 1
    complete: bool = False
    missing_artifacts: list[str] = field(default_factory=list)
    required_artifacts_present: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WinnerSelection:
    successful_candidates: list[str]
    version: int = 1
    winner_candidate_id: str = ""
    selection_basis: str = "deterministic_rank"
    winner_reason: str = ""
    exact_tie_detected: bool = False
    tied_candidate_ids: list[str] = field(default_factory=list)
    winner_tiebreak_artifact: str = ""
    candidates: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WinnerTieBreakJudge:
    attempt_id: str
    tied_candidate_ids: list[str]
    winner_candidate_id: str
    version: int = 1
    provider: str = "claude-agent-sdk"
    provider_status: str = "success"
    fallback_winner_candidate_id: str = ""
    selection_basis: str = "exact_tie_claude_judge"
    judge_summary: str = ""
    explanation: list[str] = field(default_factory=list)
    error: str = ""


@dataclass(frozen=True, slots=True)
class SessionCheckpoint:
    issue_key: str
    attempt_id: str
    candidate_id: str
    version: int = 1
    session_id: str | None = None
    turn_count: int = 0
    steer_count: int = 0
    repair_cycles: int = 0


@dataclass(frozen=True, slots=True)
class SessionHandoffBundle:
    attempt_id: str
    candidate_id: str
    rollover_id: str
    reason: str
    version: int = 1
    objective: str = "finish remaining fixes without expanding scope"
    current_status: dict[str, object] = field(default_factory=dict)
    immutable_constraints: dict[str, object] = field(default_factory=dict)
    plan_context: dict[str, object] = field(default_factory=dict)
    completed_work: list[str] = field(default_factory=list)
    remaining_work: list[str] = field(default_factory=list)
    latest_failures: list[dict[str, object]] = field(default_factory=list)
    latest_repair_feedback_refs: list[str] = field(default_factory=list)
    latest_review_delta_refs: list[str] = field(default_factory=list)
    input_artifacts: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ReplanReason:
    issue_key: str
    previous_attempt_id: str
    new_attempt_id: str
    triggered_by_review: bool
    version: int = 1
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    replan_count_after_increment: int = 0


@dataclass(frozen=True, slots=True)
class ProtectedConfigAllowlist:
    issue_key: str
    label_confirmed: bool
    version: int = 1
    paths: list[str] = field(default_factory=list)
    allowed_operations: list[str] = field(default_factory=list)
    forbidden_operations: list[str] = field(default_factory=list)
    forbid_rule_weakening: bool = True
    notes: str = ""
