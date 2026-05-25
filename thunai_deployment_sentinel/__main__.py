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

    raw_payload = Path(args.event_file).read_text() if args.event_file else stdin.read()
    rollout = RolloutEvent(**json.loads(raw_payload))

    sentinel = DevOpsSentinel(
        github_context_provider=SimpleGitHubContextProvider(),
        jira_client=InMemoryJiraClient(),
    )
    decision = sentinel.evaluate_rollout(rollout)
    print(json.dumps(asdict(decision), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
