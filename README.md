# thunai-deployment-sentinel 

#### Sampler Notes:
AI-powered DevOps sentinel that monitors ArgoCD rollouts, detects deployment regressions, enriches incidents with GitHub context, creates Jira tickets, and enables human-approved rollback workflows.

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

## Run tests

```bash
python3 -m unittest discover -s tests -v
```

