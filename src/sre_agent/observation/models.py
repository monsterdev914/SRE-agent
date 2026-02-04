"""Structured models for Kubernetes cluster state used by the agent."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PodCondition(BaseModel):
    """Pod condition summary."""

    type: str
    status: str
    reason: str | None = None
    message: str | None = None
    last_transition: datetime | None = None


class ContainerState(BaseModel):
    """Container state summary (waiting, running, terminated)."""

    state: str  # waiting | running | terminated
    reason: str | None = None
    message: str | None = None
    exit_code: int | None = None
    restart_count: int = 0


class PodSummary(BaseModel):
    """Summary of a pod for diagnosis."""

    name: str
    namespace: str
    phase: str
    ready: bool
    conditions: list[PodCondition] = Field(default_factory=list)
    container_states: list[ContainerState] = Field(default_factory=list)
    resource_requests: dict[str, str] = Field(default_factory=dict)
    resource_limits: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    creation_timestamp: datetime | None = None


class EventSummary(BaseModel):
    """Kubernetes event summary."""

    type: str  # Normal | Warning
    reason: str
    message: str
    involved_object: str  # kind/name
    count: int = 1
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    source_component: str | None = None


class DeploymentSummary(BaseModel):
    """Deployment state summary."""

    name: str
    namespace: str
    desired_replicas: int
    ready_replicas: int
    available_replicas: int
    unavailable_replicas: int
    conditions: list[dict[str, Any]] = Field(default_factory=list)


class ClusterSnapshot(BaseModel):
    """Full snapshot of relevant cluster state for a namespace."""

    namespace: str
    pods: list[PodSummary] = Field(default_factory=list)
    events: list[EventSummary] = Field(default_factory=list)
    deployments: list[DeploymentSummary] = Field(default_factory=list)
    pod_logs: dict[str, str] = Field(
        default_factory=dict,
        description="pod_name -> tail of recent logs (last N lines)",
    )
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    def to_diagnostic_text(self) -> str:
        """Render snapshot as structured text for LLM consumption."""
        lines = [
            f"# Cluster snapshot (namespace={self.namespace}, collected_at={self.collected_at.isoformat()})",
            "",
            "## Pods",
        ]
        for p in self.pods:
            lines.append(f"- {p.name}: phase={p.phase}, ready={p.ready}")
            for c in p.container_states:
                extra = f", reason={c.reason}, message={c.message}" if c.reason or c.message else ""
                lines.append(f"  container state={c.state}, restart_count={c.restart_count}{extra}")
            if p.resource_requests or p.resource_limits:
                lines.append(f"  requests={p.resource_requests}, limits={p.resource_limits}")
        lines.extend(["", "## Events (recent)"])
        for e in self.events:
            lines.append(f"- [{e.type}] {e.reason}: {e.message} (object={e.involved_object}, count={e.count})")
        lines.extend(["", "## Deployments"])
        for d in self.deployments:
            lines.append(
                f"- {d.name}: desired={d.desired_replicas}, ready={d.ready_replicas}, "
                f"available={d.available_replicas}, unavailable={d.unavailable_replicas}"
            )
        if self.pod_logs:
            lines.extend(["", "## Pod logs (tail)"])
            for pod_name, log in self.pod_logs.items():
                lines.append(f"### {pod_name}")
                lines.append(log if log.strip() else "(no logs)")
        return "\n".join(lines)
