from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

from .sentinel import RolloutEvent


class ArgoCDHttpClient:
    """Thin stdlib-only client for the ArgoCD REST API."""

    def __init__(
        self,
        server_url: str,
        token: str,
        insecure_skip_tls_verify: bool = False,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._ssl_ctx = ssl.create_default_context()
        if insecure_skip_tls_verify:
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        url = f"{self.server_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self._ssl_ctx) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"ArgoCD API {method} {url} returned {exc.code}: {exc.read().decode(errors='replace')}"
            ) from exc

    # ------------------------------------------------------------------
    # Application queries
    # ------------------------------------------------------------------

    def get_application(self, name: str) -> dict:
        return self._request("GET", f"/api/v1/applications/{name}")

    def get_rollout_event(self, name: str) -> RolloutEvent:
        """Map an ArgoCD Application object to a RolloutEvent."""
        app = self.get_application(name)
        spec = app.get("spec", {})
        status = app.get("status", {})
        sync = status.get("sync", {})
        health = status.get("health", {})
        operation_state = status.get("operationState", {})

        phase = operation_state.get("phase") or sync.get("status", "Unknown")
        namespace = spec.get("destination", {}).get("namespace", "unknown")

        return RolloutEvent(
            application=name,
            environment=namespace,
            revision=sync.get("revision", "unknown"),
            status=phase,
            health_status=health.get("status", "Unknown"),
        )

    # ------------------------------------------------------------------
    # Sync control
    # ------------------------------------------------------------------

    def pause_sync(self, name: str) -> None:
        """Disable automated sync on the application to contain blast radius."""
        app = self.get_application(name)
        spec = app.get("spec", {})
        sync_policy = spec.get("syncPolicy", {})
        if "automated" in sync_policy:
            sync_policy.pop("automated")
        patch = {"spec": {"syncPolicy": sync_policy}}
        self._request("PATCH", f"/api/v1/applications/{name}", patch)

    def rollback(self, name: str, history_id: int = 0) -> None:
        """Trigger a rollback to a previous synced revision (by history ID)."""
        self._request("POST", f"/api/v1/applications/{name}/rollback", {"id": history_id})

    def sync(self, name: str, revision: str | None = None) -> None:
        """Trigger a sync, optionally pinned to a specific revision."""
        body: dict = {}
        if revision:
            body["revision"] = revision
        self._request("POST", f"/api/v1/applications/{name}/sync", body)
