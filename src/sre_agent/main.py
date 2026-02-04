"""CLI entrypoint for the SRE agent."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from sre_agent import __version__
from sre_agent.config import get_settings
from sre_agent.agent import run_agent, print_result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SRE Agent: detect, diagnose, and resolve Kubernetes operational issues.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--namespace",
        "-n",
        default=None,
        help="Kubernetes namespace to operate in (default: from env or 'default')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only diagnose; do not apply any remediation",
    )
    parser.add_argument(
        "--kubeconfig",
        type=Path,
        default=None,
        help="Path to kubeconfig (default: KUBECONFIG env or ~/.kube/config)",
    )
    parser.add_argument(
        "--context",
        default=None,
        help="Kubernetes context to use",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args()


def main() -> int:
    """Entrypoint for sre-agent CLI."""
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    logger = logging.getLogger("sre_agent")
    if not args.verbose:
        logger.setLevel(logging.WARNING)

    try:
        settings = get_settings()
        if args.kubeconfig:
            settings.kubeconfig = args.kubeconfig
        if args.dry_run:
            settings.dry_run = True

        result = run_agent(
            namespace=args.namespace,
            dry_run=args.dry_run,
            kubeconfig=str(settings.kubeconfig) if settings.kubeconfig else None,
            context=args.context or settings.context,
            settings=settings,
        )
        print_result(result, Console())
        return 0 if result.issue_resolved else 1
    except Exception as e:
        logging.exception("Agent failed")
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
