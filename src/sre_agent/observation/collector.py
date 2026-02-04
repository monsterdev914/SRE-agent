"""Collect Kubernetes cluster state (pods, events, logs) for diagnosis."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from sre_agent.observation.models import (
    ClusterSnapshot,
    ContainerState,
    DeploymentSummary,
    EventSummary,
    PodCondition,
    PodSummary,
)

logger = logging.getLogger(__name__)

# Default number of log lines to fetch per failing container
DEFAULT_LOG_TAIL_LINES = 50


def _load_kube_config(kubeconfig_path: str | None, context: str | None) -> client.Configuration:
    """Load in-cluster or kubeconfig-based configuration."""
    try:
        config.load_incluster_config()
        return client.Configuration.get_default_copy()
    except config.ConfigException:
        pass
    kwargs: dict[str, Any] = {}
    if kubeconfig_path:
        kwargs["config_file"] = str(kubeconfig_path)
    if context:
        kwargs["context"] = context
    config.load_kube_config(**kwargs)
    return client.Configuration.get_default_copy()


def _parse_container_state(container_status: Any) -> ContainerState:
    """Extract container state from V1ContainerStatus."""
    state = "unknown"
    reason = None
    message = None
    exit_code = None
    if container_status.state and container_status.state.waiting:
        state = "waiting"
        reason = getattr(container_status.state.waiting, "reason", None)
        message = getattr(container_status.state.waiting, "message", None)
    elif container_status.state and container_status.state.running:
        state = "running"
    elif container_status.state and container_status.state.terminated:
        state = "terminated"
        reason = getattr(container_status.state.terminated, "reason", None)
        message = getattr(container_status.state.terminated, "message", None)
        exit_code = getattr(container_status.state.terminated, "exit_code", None)
    return ContainerState(
        state=state,
        reason=reason,
        message=message,
        exit_code=exit_code,
        restart_count=container_status.restart_count or 0,
    )


def _pod_resource_dict(resources: Any) -> dict[str, str]:
    """Convert V1ResourceRequirements to dict of resource name -> quantity."""
    if not resources:
        return {}
    out: dict[str, str] = {}
    for attr in ("requests", "limits"):
        mapping = getattr(resources, attr, None)
        if not mapping:
            continue
        for k, v in (mapping or {}).items():
            out[f"{attr}_{k}"] = str(v) if v else ""
    return out


def _build_pod_summary(pod: Any) -> PodSummary:
    """Build PodSummary from V1Pod."""
    conditions = []
    for c in getattr(pod.status, "conditions", []) or []:
        conditions.append(
            PodCondition(
                type=c.type or "",
                status=c.status or "",
                reason=getattr(c, "reason", None),
                message=getattr(c, "message", None),
                last_transition=(
                    c.last_transition_time.replace(tzinfo=timezone.utc) if c.last_transition_time else None
                ),
            )
        )
    container_states = []
    for cs in getattr(pod.status, "container_statuses", []) or []:
        container_states.append(_parse_container_state(cs))
    # If container_statuses is empty but we have spec.containers, add a placeholder
    if not container_states and getattr(pod.spec, "containers", []):
        for _ in pod.spec.containers:
            container_states.append(ContainerState(state="unknown", restart_count=0))

    requests, limits = {}, {}
    for container in getattr(pod.spec, "containers", []) or []:
        res = _pod_resource_dict(getattr(container, "resources", None))
        for k, v in res.items():
            if k.startswith("requests_"):
                requests[k.replace("requests_", "")] = v
            elif k.startswith("limits_"):
                limits[k.replace("limits_", "")] = v

    return PodSummary(
        name=pod.metadata.name,
        namespace=pod.metadata.namespace or "default",
        phase=getattr(pod.status, "phase", "Unknown") or "Unknown",
        ready=any(
            (c.status == "True" and c.type == "Ready")
            for c in getattr(pod.status, "conditions", []) or []
        ),
        conditions=conditions,
        container_states=container_states,
        resource_requests=requests,
        resource_limits=limits,
        labels=dict(pod.metadata.labels or {}),
        creation_timestamp=(
            pod.metadata.creation_timestamp.replace(tzinfo=timezone.utc)
            if pod.metadata.creation_timestamp
            else None
        ),
    )


def _build_event_summary(ev: Any) -> EventSummary:
    """Build EventSummary from CoreV1Event."""
    obj = ev.involved_object
    involved = f"{getattr(obj, 'kind', '')}/{getattr(obj, 'name', '')}"
    return EventSummary(
        type=ev.type or "Normal",
        reason=ev.reason or "",
        message=ev.message or "",
        involved_object=involved,
        count=ev.count or 1,
        first_timestamp=ev.first_timestamp.replace(tzinfo=timezone.utc) if ev.first_timestamp else None,
        last_timestamp=ev.last_timestamp.replace(tzinfo=timezone.utc) if ev.last_timestamp else None,
        source_component=getattr(ev.source, "component", None) if ev.source else None,
    )


def _build_deployment_summary(d: Any) -> DeploymentSummary:
    """Build DeploymentSummary from V1Deployment or V1DeploymentStatus."""
    status = d.status
    return DeploymentSummary(
        name=d.metadata.name,
        namespace=d.metadata.namespace or "default",
        desired_replicas=status.replicas or 0,
        ready_replicas=status.ready_replicas or 0,
        available_replicas=status.available_replicas or 0,
        unavailable_replicas=status.unavailable_replicas or 0,
        conditions=[{"type": c.type, "status": c.status} for c in (status.conditions or [])],
    )


class ClusterCollector:
    """Collects cluster state (pods, events, deployments, logs) from a Kubernetes cluster."""

    def __init__(
        self,
        namespace: str = "default",
        kubeconfig: str | None = None,
        context: str | None = None,
        log_tail_lines: int = DEFAULT_LOG_TAIL_LINES,
    ) -> None:
        self.namespace = namespace
        self.log_tail_lines = log_tail_lines
        cfg = _load_kube_config(kubeconfig, context)
        self._core = client.CoreV1Api(client.ApiClient(cfg))
        self._apps = client.AppsV1Api(client.ApiClient(cfg))

    def collect(self) -> ClusterSnapshot:
        """Collect full snapshot for the configured namespace."""
        pods: list[PodSummary] = []
        events: list[EventSummary] = []
        deployments: list[DeploymentSummary] = []
        pod_logs: dict[str, str] = {}

        try:
            pod_list = self._core.list_namespaced_pod(
                namespace=self.namespace,
                limit=100,
            )
            for pod in pod_list.items:
                pods.append(_build_pod_summary(pod))
                # Collect logs for non-ready or non-running pods
                if not self._pod_healthy(pod):
                    for c in getattr(pod.spec, "containers", []) or []:
                        cname = c.name
                        try:
                            log = self._core.read_namespaced_pod_log(
                                name=pod.metadata.name,
                                namespace=self.namespace,
                                container=cname,
                                tail_lines=self.log_tail_lines,
                                timestamps=False,
                            )
                            key = f"{pod.metadata.name}/{cname}"
                            pod_logs[key] = log or ""
                        except ApiException as e:
                            pod_logs[f"{pod.metadata.name}/{cname}"] = f"(failed to get logs: {e.reason})"
        except ApiException as e:
            logger.warning("Failed to list pods: %s", e.reason)
            raise

        try:
            event_list = self._core.list_namespaced_event(
                namespace=self.namespace,
                limit=50,
            )
            # Sort by last_timestamp descending (most recent first)
            items = sorted(
                event_list.items,
                key=lambda x: (x.last_timestamp or x.first_timestamp or datetime.min.replace(tzinfo=timezone.utc)),
                reverse=True,
            )
            for ev in items[:30]:
                events.append(_build_event_summary(ev))
        except ApiException as e:
            logger.warning("Failed to list events: %s", e.reason)

        try:
            dep_list = self._apps.list_namespaced_deployment(namespace=self.namespace, limit=50)
            for d in dep_list.items:
                deployments.append(_build_deployment_summary(d))
        except ApiException as e:
            logger.warning("Failed to list deployments: %s", e.reason)

        return ClusterSnapshot(
            namespace=self.namespace,
            pods=pods,
            events=events,
            deployments=deployments,
            pod_logs=pod_logs,
            collected_at=datetime.now(timezone.utc),
        )

    def _pod_healthy(self, pod: Any) -> bool:
        """Return True if pod is running and ready."""
        if getattr(pod.status, "phase", None) != "Running":
            return False
        for c in getattr(pod.status, "conditions", []) or []:
            if c.type == "Ready" and c.status == "True":
                return True
        return False
