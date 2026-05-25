# thunai-deployment-sentinel
AI-powered DevOps sentinel that monitors ArgoCD rollouts, detects deployment regressions, enriches incidents with GitHub context, creates Jira tickets, and enables human-approved rollback workflows.

## What is implemented

This repository includes:

- **Sentinel core** — evaluates ArgoCD rollout events for unhealthy rollout state, error-rate regressions, and latency regressions; enriches detected incidents with GitHub deployment context; creates incident records; prepares a human-approved rollback workflow
- **ArgoCD HTTP client** (`argocd_client.py`) — stdlib-only client for the ArgoCD REST API: fetch application health, pause automated sync (blast-radius containment), trigger rollback
- **Watch / daemon mode** — `python -m thunai_deployment_sentinel watch` polls one or more ArgoCD applications on a configurable interval and acts automatically on regression detection
- **Helm charts** — `charts/checkout-service` (the monitored service) and `charts/thunai-sentinel` (the sentinel itself), both ready for GitOps deployment
- **ArgoCD Application manifests** — `argocd/checkout-service-app.yaml` and `argocd/sentinel-app.yaml` tell ArgoCD to watch the charts directory; every `git push` to `main` triggers an automated sync

## Repository layout

```
charts/
  checkout-service/       ← Helm chart for the demo target service
  thunai-sentinel/        ← Helm chart for the sentinel daemon
argocd/
  checkout-service-app.yaml   ← ArgoCD Application (automated sync)
  sentinel-app.yaml           ← ArgoCD Application for the sentinel
thunai_deployment_sentinel/
  sentinel.py             ← Core detection & rollback logic
  argocd_client.py        ← ArgoCD REST API client (no extra deps)
  __main__.py             ← CLI: evaluate (single-shot) + watch (daemon)
Dockerfile
```

## ArgoCD setup

1. Apply both Application manifests to your cluster:

   ```bash
   kubectl apply -f argocd/checkout-service-app.yaml
   kubectl apply -f argocd/sentinel-app.yaml
   ```

2. ArgoCD will immediately sync `charts/checkout-service` and `charts/thunai-sentinel` from the `main` branch. Any future `git push` is detected automatically (automated sync is enabled).

3. Create the credentials secret before deploying the sentinel:

   ```bash
   kubectl create secret generic thunai-sentinel-credentials \
     --from-literal=ARGOCD_TOKEN=<your-argocd-api-token> \
     -n thunai-sentinel
   ```

## Run the sentinel daemon (watch mode)

```bash
python -m thunai_deployment_sentinel watch \
  --argocd-server https://argocd.example.com \
  --argocd-token  $ARGOCD_TOKEN \
  --interval      30 \
  checkout-service
```

Or set env vars and use the Helm chart / Docker image:

```bash
export ARGOCD_SERVER=https://argocd.example.com
export ARGOCD_TOKEN=<token>
python -m thunai_deployment_sentinel watch checkout-service
```

## Run the sentinel (single-shot evaluate mode)

```bash
python -m thunai_deployment_sentinel evaluate <<'EOF'
{
  "application": "checkout-service",
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

The legacy form (no subcommand) still works for backwards compatibility:

```bash
python -m thunai_deployment_sentinel event.json
```

## Demo: bad deployment

To reproduce the CrashLoopBackOff scenario described in the demo narrative, override the liveness probe path in `charts/checkout-service/values.yaml`:

```yaml
livenessProbe:
  httpGet:
    path: /nonexistent-health-endpoint   # ← causes readiness/liveness failures
    port: http
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 1
```

Commit and push → ArgoCD detects the change, syncs, pods start failing → sentinel detects the regression, pauses the sync, and emits an enriched incident payload.

## Run tests

```bash
python3 -m unittest discover -s tests -v
```

