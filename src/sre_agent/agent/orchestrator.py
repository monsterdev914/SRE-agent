"""Orchestrator: observe → diagnose → remediate → verify → communicate."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from sre_agent.config import Settings, get_settings
from sre_agent.observation import ClusterCollector, ClusterSnapshot
from sre_agent.diagnosis import diagnose, Diagnosis
from sre_agent.remediation import apply_remediation, verify_healthy
from sre_agent.agent.prompts import (
    REPORT_HEADER,
    REPORT_SECTION_DETECTION,
    REPORT_SECTION_ACTIONS,
    REPORT_SECTION_VERIFICATION,
    REPORT_NO_ISSUE,
    REPORT_DRY_RUN,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result of a full agent run."""

    snapshot: ClusterSnapshot
    diagnosis: Diagnosis
    actions_taken: list[tuple[str, bool, str]] = field(default_factory=list)
    verified: bool = False
    verification_message: str = ""
    report: str = ""

    @property
    def issue_resolved(self) -> bool:
        return self.verified or (not self.diagnosis.has_issue)


def run_agent(
    namespace: str | None = None,
    dry_run: bool | None = None,
    kubeconfig: str | None = None,
    context: str | None = None,
    settings: Settings | None = None,
) -> AgentResult:
    """
    Run the full agent loop: collect snapshot → diagnose → remediate (unless dry_run) → verify → build report.
    """
    opts = settings or get_settings()
    ns = namespace or opts.namespace
    do_remediate = not (dry_run if dry_run is not None else opts.dry_run)
    kubeconfig_str = str(opts.kubeconfig) if opts.kubeconfig else kubeconfig
    ctx = context or opts.context

    # Observe
    collector = ClusterCollector(
        namespace=ns,
        kubeconfig=kubeconfig_str,
        context=ctx,
    )
    snapshot = collector.collect()

    # Diagnose
    diagnosis = diagnose(snapshot, opts)

    actions_taken: list[tuple[str, bool, str]] = []
    if diagnosis.has_issue and diagnosis.remediation_actions and do_remediate:
        max_attempts = opts.max_remediation_attempts
        for action in diagnosis.remediation_actions:
            if len(actions_taken) >= max_attempts:
                break
            success, msg = apply_remediation(action, ns, kubeconfig_str, ctx)
            actions_taken.append((action.description, success, msg))
            if success and action.kind.value != "custom_instruction":
                # Allow cluster to settle before re-checking
                time.sleep(3)

    # Verify (only if we applied at least one remediation)
    verified = False
    verification_message = "Skipped (no remediation applied)."
    if actions_taken or not diagnosis.has_issue:
        verified, verification_message = verify_healthy(ns, kubeconfig_str, ctx)

    # Build report
    report_parts = [REPORT_HEADER]
    if diagnosis.has_issue:
        evidence_text = "\n".join(f"- {e}" for e in diagnosis.evidence) or "—"
        report_parts.append(
            REPORT_SECTION_DETECTION.format(
                summary=diagnosis.summary,
                root_cause=diagnosis.root_cause,
                evidence=evidence_text,
            )
        )
        if actions_taken:
            actions_text = "\n".join(
                f"- **{desc}**: {'OK' if ok else 'Failed'} — {msg}"
                for desc, ok, msg in actions_taken
            )
            report_parts.append(REPORT_SECTION_ACTIONS.format(actions=actions_text))
        elif do_remediate:
            report_parts.append("\nNo remediation was applied (none suggested or parsing failed).")
        if not do_remediate:
            report_parts.append(REPORT_DRY_RUN)
        report_parts.append(
            REPORT_SECTION_VERIFICATION.format(verification=verification_message)
        )
    else:
        report_parts.append(REPORT_NO_ISSUE)

    result = AgentResult(
        snapshot=snapshot,
        diagnosis=diagnosis,
        actions_taken=actions_taken,
        verified=verified,
        verification_message=verification_message,
        report="\n".join(report_parts),
    )
    return result


def print_result(result: AgentResult, console: Console | None = None) -> None:
    """Print agent result to console using Rich."""
    c = console or Console()
    c.print(Panel(Markdown(result.report), title="SRE Agent Report", border_style="blue"))
    if result.diagnosis.has_issue:
        c.print(f"\n[bold]Confidence:[/bold] {result.diagnosis.confidence:.0%}")
