import argparse
import json
from dataclasses import asdict
from pathlib import Path
from sys import stdin

from .sentinel import DevOpsSentinel, InMemoryJiraClient, RolloutEvent, SimpleGitHubContextProvider


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate an ArgoCD rollout and emit an incident/rollback decision as JSON."
    )
    parser.add_argument("event_file", nargs="?", help="Path to a JSON file containing a rollout event")
    args = parser.parse_args()

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


if __name__ == "__main__":
    raise SystemExit(main())
