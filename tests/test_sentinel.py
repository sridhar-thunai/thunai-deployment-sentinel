import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from thunai_deployment_sentinel import DevOpsSentinel, RolloutEvent
from thunai_deployment_sentinel.__main__ import main


class DevOpsSentinelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sentinel = DevOpsSentinel()

    def test_healthy_rollout_does_not_create_incident(self) -> None:
        decision = self.sentinel.evaluate_rollout(
            RolloutEvent(
                application="payments",
                environment="prod",
                revision="abc123",
                status="Succeeded",
                health_status="Healthy",
                error_rate=0.02,
                baseline_error_rate=0.01,
                latency_ms=180,
                baseline_latency_ms=150,
                affected_pull_requests=("#41",),
                rollback_revision="prev123",
            )
        )

        self.assertFalse(decision.regression_detected)
        self.assertEqual((), decision.reasons)
        self.assertIsNone(decision.github_context)
        self.assertIsNone(decision.jira_incident)
        self.assertIsNone(decision.rollback_workflow)

    def test_regression_creates_enriched_incident_and_pending_rollback(self) -> None:
        decision = self.sentinel.evaluate_rollout(
            RolloutEvent(
                application="payments",
                environment="prod",
                revision="def456",
                status="Degraded",
                health_status="Degraded",
                error_rate=0.12,
                baseline_error_rate=0.01,
                latency_ms=450,
                baseline_latency_ms=150,
                affected_pull_requests=("#52", "#53"),
                rollback_revision="abc123",
            )
        )

        self.assertTrue(decision.regression_detected)
        self.assertIn("ArgoCD rollout status is degraded", decision.reasons)
        self.assertIn("ArgoCD health status is degraded", decision.reasons)
        self.assertIn("Error rate increased from 1.00% to 12.00%", decision.reasons)
        self.assertIn("Latency increased from 150ms to 450ms", decision.reasons)
        self.assertEqual("def456", decision.github_context.commit)
        self.assertEqual(("#52", "#53"), decision.github_context.pull_requests)
        self.assertIn("regression triggers", decision.github_context.summary)
        self.assertEqual("OPS-1", decision.jira_incident.ticket_key)
        self.assertIn("GitHub Context:", decision.jira_incident.description)
        self.assertEqual("abc123", decision.rollback_workflow.target_revision)
        self.assertEqual("awaiting_human_approval", decision.rollback_workflow.status)

    def test_rollback_requires_human_approval(self) -> None:
        initial_decision = self.sentinel.evaluate_rollout(
            RolloutEvent(
                application="payments",
                environment="prod",
                revision="def456",
                status="Failed",
                health_status="Missing",
                error_rate=0.09,
                baseline_error_rate=0.01,
                rollback_revision="abc123",
            )
        )

        approved_decision = self.sentinel.approve_rollback(initial_decision, approver="ops-oncall")

        self.assertEqual("approved", approved_decision.rollback_workflow.status)
        self.assertEqual("ops-oncall", approved_decision.rollback_workflow.approved_by)

    def test_zero_latency_baseline_can_still_trigger_regression(self) -> None:
        decision = self.sentinel.evaluate_rollout(
            RolloutEvent(
                application="payments",
                environment="prod",
                revision="ghi789",
                status="Succeeded",
                health_status="Healthy",
                latency_ms=300,
                baseline_latency_ms=0,
            )
        )

        self.assertTrue(decision.regression_detected)
        self.assertIn("Latency increased from 0ms to 300ms", decision.reasons)

    def test_cli_reports_invalid_rollout_payload_clearly(self) -> None:
        stderr = StringIO()
        with patch("sys.argv", ["thunai_deployment_sentinel"]), patch(
            "thunai_deployment_sentinel.__main__.stdin.read",
            return_value="{\"application\": \"payments\"}",
        ), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exit_context:
                main()

        self.assertEqual(2, exit_context.exception.code)
        self.assertIn("Expected a JSON rollout event", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
