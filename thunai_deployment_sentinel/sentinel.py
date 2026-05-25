from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, Sequence


@dataclass(frozen=True)
class RolloutEvent:
    application: str
    environment: str
    revision: str
    status: str
    health_status: str
    error_rate: float = 0.0
    baseline_error_rate: float = 0.0
    latency_ms: float = 0.0
    baseline_latency_ms: float = 0.0
    affected_pull_requests: tuple[str, ...] = ()
    rollback_revision: str | None = None


@dataclass(frozen=True)
class GitHubContext:
    commit: str
    pull_requests: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class JiraIncident:
    ticket_key: str
    summary: str
    description: str


@dataclass(frozen=True)
class RollbackWorkflow:
    target_revision: str
    status: str = "awaiting_human_approval"
    approved_by: str | None = None
    steps: tuple[str, ...] = (
        "Review enriched incident context",
        "Approve rollback",
        "Promote rollback revision in ArgoCD",
        "Verify post-rollback health",
    )


@dataclass(frozen=True)
class SentinelDecision:
    rollout: RolloutEvent
    regression_detected: bool
    reasons: tuple[str, ...] = ()
    github_context: GitHubContext | None = None
    jira_incident: JiraIncident | None = None
    rollback_workflow: RollbackWorkflow | None = None


@dataclass(frozen=True)
class SentinelConfig:
    error_rate_delta_threshold: float = 0.03
    latency_increase_ratio_threshold: float = 1.5
    unhealthy_rollout_statuses: tuple[str, ...] = ("degraded", "failed", "error")


class GitHubContextProvider(Protocol):
    def enrich(self, rollout: RolloutEvent, reasons: Sequence[str]) -> GitHubContext: ...


class JiraClient(Protocol):
    def create_incident(
        self,
        rollout: RolloutEvent,
        reasons: Sequence[str],
        github_context: GitHubContext,
    ) -> JiraIncident: ...


class SimpleGitHubContextProvider:
    def enrich(self, rollout: RolloutEvent, reasons: Sequence[str]) -> GitHubContext:
        pull_requests = tuple(rollout.affected_pull_requests)
        pr_summary = ", ".join(pull_requests) if pull_requests else "no linked pull requests"
        summary = (
            f"Revision {rollout.revision} for {rollout.application} in {rollout.environment} "
            f"is linked to {pr_summary}; regression triggers: {', '.join(reasons)}."
        )
        return GitHubContext(commit=rollout.revision, pull_requests=pull_requests, summary=summary)


class InMemoryJiraClient:
    def __init__(self, project_key: str = "OPS") -> None:
        self.project_key = project_key
        self._incident_count = 0

    def create_incident(
        self,
        rollout: RolloutEvent,
        reasons: Sequence[str],
        github_context: GitHubContext,
    ) -> JiraIncident:
        self._incident_count += 1
        ticket_key = f"{self.project_key}-{self._incident_count}"
        summary = f"[Deployment Regression] {rollout.application} {rollout.environment}"
        description = "\n".join(
            (
                f"Application: {rollout.application}",
                f"Environment: {rollout.environment}",
                f"Revision: {rollout.revision}",
                f"Reasons: {', '.join(reasons)}",
                f"GitHub Context: {github_context.summary}",
            )
        )
        return JiraIncident(ticket_key=ticket_key, summary=summary, description=description)


class DevOpsSentinel:
    def __init__(
        self,
        github_context_provider: GitHubContextProvider | None = None,
        jira_client: JiraClient | None = None,
        config: SentinelConfig | None = None,
    ) -> None:
        self.github_context_provider = github_context_provider or SimpleGitHubContextProvider()
        self.jira_client = jira_client or InMemoryJiraClient()
        self.config = config or SentinelConfig()

    def evaluate_rollout(self, rollout: RolloutEvent) -> SentinelDecision:
        reasons = self._detect_regression_reasons(rollout)
        if not reasons:
            return SentinelDecision(rollout=rollout, regression_detected=False)

        github_context = self.github_context_provider.enrich(rollout, reasons)
        jira_incident = self.jira_client.create_incident(rollout, reasons, github_context)
        rollback_workflow = (
            RollbackWorkflow(target_revision=rollout.rollback_revision)
            if rollout.rollback_revision
            else None
        )
        return SentinelDecision(
            rollout=rollout,
            regression_detected=True,
            reasons=tuple(reasons),
            github_context=github_context,
            jira_incident=jira_incident,
            rollback_workflow=rollback_workflow,
        )

    def approve_rollback(self, decision: SentinelDecision, approver: str) -> SentinelDecision:
        if not decision.rollback_workflow:
            raise ValueError("Rollback approval requested for a decision without a rollback workflow.")

        return replace(
            decision,
            rollback_workflow=replace(
                decision.rollback_workflow,
                status="approved",
                approved_by=approver,
            ),
        )

    def _detect_regression_reasons(self, rollout: RolloutEvent) -> list[str]:
        reasons: list[str] = []
        rollout_status = rollout.status.lower()
        health_status = rollout.health_status.lower()

        if rollout_status in self.config.unhealthy_rollout_statuses:
            reasons.append(f"ArgoCD rollout status is {rollout.status}")

        if health_status != "healthy":
            reasons.append(f"ArgoCD health status is {rollout.health_status}")

        error_rate_delta = rollout.error_rate - rollout.baseline_error_rate
        if error_rate_delta >= self.config.error_rate_delta_threshold:
            reasons.append(
                "Error rate increased "
                f"from {rollout.baseline_error_rate:.2%} to {rollout.error_rate:.2%}"
            )

        if rollout.baseline_latency_ms > 0:
            latency_ratio = rollout.latency_ms / rollout.baseline_latency_ms
            if latency_ratio >= self.config.latency_increase_ratio_threshold:
                reasons.append(
                    "Latency increased "
                    f"from {rollout.baseline_latency_ms:.0f}ms to {rollout.latency_ms:.0f}ms"
                )

        return reasons
