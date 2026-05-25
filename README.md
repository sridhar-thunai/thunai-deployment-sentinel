# thunai-deployment-sentinel
AI-powered DevOps sentinel that monitors ArgoCD rollouts, detects deployment regressions, enriches incidents with GitHub context, creates Jira tickets, and enables human-approved rollback workflows.

## What is implemented

This repository now includes a small, dependency-free Python implementation of a deployment sentinel that:

- evaluates ArgoCD rollout events for unhealthy rollout state, error-rate regressions, and latency regressions
- enriches detected incidents with GitHub deployment context such as the deployed revision and linked pull requests
- creates an incident record through a Jira client abstraction
- prepares a rollback workflow that remains `awaiting_human_approval` until explicitly approved

## Run the sentinel

```bash
python -m thunai_deployment_sentinel <<'EOF'
{
  "application": "payments",
  "environment": "prod",
  "revision": "def456",
  "status": "Degraded",
  "health_status": "Degraded",
  "error_rate": 0.12,
  "baseline_error_rate": 0.01,
  "latency_ms": 450,
  "baseline_latency_ms": 150,
  "affected_pull_requests": ["#52", "#53"],
  "rollback_revision": "abc123"
}
EOF
```

## Run tests

```bash
python -m unittest discover -s tests
```
