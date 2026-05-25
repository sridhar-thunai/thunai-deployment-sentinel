import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from sys import stdin

from .argocd_client import ArgoCDHttpClient
from .sentinel import DevOpsSentinel, InMemoryJiraClient, RolloutEvent, SimpleGitHubContextProvider


# ---------------------------------------------------------------------------
# evaluate  (original single-shot mode)
# ---------------------------------------------------------------------------

def _cmd_evaluate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        raw_payload = Path(args.event_file).read_text() if args.event_file else stdin.read()
    except OSError as error:
        parser.exit(
            2,
            f"Unable to read rollout event input for the deployment sentinel: {error}\n",
        )

    try:
        rollout = RolloutEvent(**json.loads(raw_payload))
    except (json.JSONDecodeError, TypeError) as error:
        parser.exit(
            2,
            "Expected a JSON rollout event with fields such as application, environment, revision, "
            f"status, and health_status. Error: {error}\n",
        )

    sentinel = DevOpsSentinel(
        github_context_provider=SimpleGitHubContextProvider(),
        jira_client=InMemoryJiraClient(),
    )
    decision = sentinel.evaluate_rollout(rollout)
    print(json.dumps(asdict(decision), indent=2))
    return 0


# ---------------------------------------------------------------------------
# watch  (daemon mode — polls ArgoCD every --interval seconds)
# ---------------------------------------------------------------------------

def _cmd_watch(args: argparse.Namespace) -> int:
    server = args.argocd_server or os.environ.get("ARGOCD_SERVER", "")
    token = args.argocd_token or os.environ.get("ARGOCD_TOKEN", "")

    if not server:
        print(
            "error: --argocd-server (or ARGOCD_SERVER env var) is required for watch mode",
            file=sys.stderr,
        )
        return 2
    if not token:
        print(
            "error: --argocd-token (or ARGOCD_TOKEN env var) is required for watch mode",
            file=sys.stderr,
        )
        return 2

    argocd = ArgoCDHttpClient(
        server_url=server,
        token=token,
        insecure_skip_tls_verify=args.insecure,
    )
    sentinel = DevOpsSentinel(
        github_context_provider=SimpleGitHubContextProvider(),
        jira_client=InMemoryJiraClient(),
    )

    print(
        f"[sentinel] watching {args.applications} on {server} every {args.interval}s",
        flush=True,
    )

    while True:
        for app_name in args.applications:
            try:
                rollout = argocd.get_rollout_event(app_name)
                decision = sentinel.evaluate_rollout(rollout)
                if decision.regression_detected:
                    print(
                        f"[sentinel] regression detected on {app_name} — pausing sync",
                        flush=True,
                    )
                    argocd.pause_sync(app_name)
                    print(json.dumps(asdict(decision), indent=2), flush=True)
                else:
                    print(f"[sentinel] {app_name} is healthy", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[sentinel] error evaluating {app_name}: {exc}", file=sys.stderr, flush=True)

        time.sleep(args.interval)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Thunai Deployment Sentinel — monitors ArgoCD rollouts for regressions.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- evaluate (default / legacy behaviour) ---
    eval_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate a single rollout event from a JSON file or stdin.",
    )
    eval_parser.add_argument(
        "event_file",
        nargs="?",
        help="Path to a JSON file containing a rollout event (reads stdin if omitted)",
    )

    # --- watch (daemon) ---
    watch_parser = subparsers.add_parser(
        "watch",
        help="Continuously poll ArgoCD applications and act on regressions.",
    )
    watch_parser.add_argument(
        "applications",
        nargs="+",
        metavar="APP",
        help="ArgoCD application name(s) to watch",
    )
    watch_parser.add_argument(
        "--argocd-server",
        metavar="URL",
        default="",
        help="ArgoCD server URL (or set ARGOCD_SERVER env var)",
    )
    watch_parser.add_argument(
        "--argocd-token",
        metavar="TOKEN",
        default="",
        help="ArgoCD API bearer token (or set ARGOCD_TOKEN env var)",
    )
    watch_parser.add_argument(
        "--interval",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Polling interval in seconds (default: 30)",
    )
    watch_parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS certificate verification",
    )

    args = parser.parse_args()

    # Preserve backwards-compatible behaviour: no subcommand → evaluate from stdin/file
    if args.command is None or args.command == "evaluate":
        # Reconstruct a minimal namespace expected by _cmd_evaluate
        if args.command is None:
            # Legacy: treat first positional (if any) as event_file
            setattr(args, "event_file", getattr(args, "event_file", None))
        return _cmd_evaluate(args, parser)

    if args.command == "watch":
        return _cmd_watch(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
