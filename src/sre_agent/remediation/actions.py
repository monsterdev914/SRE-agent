"""Execute remediation actions against the Kubernetes cluster."""

from __future__ import annotations

import logging
from typing import Any

from kubernetes import client, config
from kubernetes.client import V1EnvVar, V1ResourceRequirements
from kubernetes.client.rest import ApiException

from sre_agent.diagnosis.models import RemediationAction, RemediationKind

logger = logging.getLogger(__name__)


def _get_api_client(kubeconfig: str | None = None, context: str | None = None) -> tuple[client.CoreV1Api, client.AppsV1Api]:
    """Load kubeconfig and return Core and Apps API clients."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        kwargs: dict[str, Any] = {}
        if kubeconfig:
            kwargs["config_file"] = str(kubeconfig)
        if context:
            kwargs["context"] = context
        config.load_kube_config(**kwargs)
    cfg = client.Configuration.get_default_copy()
    return client.CoreV1Api(client.ApiClient(cfg)), client.AppsV1Api(client.ApiClient(cfg))


def _parse_target(target: str | None, namespace: str) -> tuple[str | None, str | None]:
    """Parse 'deployment/name' or 'pod/name' into kind and name."""
    if not target or "/" not in target:
        return None, None
    kind, name = target.strip().lower().split("/", 1)
    return kind, name


def apply_remediation(
    action: RemediationAction,
    namespace: str,
    kubeconfig: str | None = None,
    context: str | None = None,
) -> tuple[bool, str]:
    """
    Apply a single remediation action. Returns (success, message).
    """
    core, apps = _get_api_client(kubeconfig, context)
    kind, name = _parse_target(action.target, namespace)
    if not name:
        if action.kind == RemediationKind.CUSTOM_INSTRUCTION:
            return True, f"Manual: {action.description}"
        return False, f"Invalid or missing target: {action.target}"

    try:
        if action.kind == RemediationKind.DELETE_POD and kind == "pod":
            core.delete_namespaced_pod(name=name, namespace=namespace)
            return True, f"Deleted pod {name}"

        if action.kind == RemediationKind.PATCH_DEPLOYMENT_ENV and kind == "deployment":
            dep = apps.read_namespaced_deployment(name=name, namespace=namespace)
            env_vars = action.params
            if not env_vars:
                return False, "patch_deployment_env requires params with env var key/values"
            # Build env list for all containers (apply same env to each for simplicity)
            for container in dep.spec.template.spec.containers:
                existing = {e.name: e for e in (container.env or [])}
                for k, v in env_vars.items():
                    existing[k] = V1EnvVar(name=k, value=str(v))
                container.env = list(existing.values())
            apps.patch_namespaced_deployment(
                name=name,
                namespace=namespace,
                body=dep,
            )
            return True, f"Patched deployment {name} with env vars: {list(env_vars.keys())}"

        if action.kind == RemediationKind.PATCH_DEPLOYMENT_RESOURCES and kind == "deployment":
            dep = apps.read_namespaced_deployment(name=name, namespace=namespace)
            res = dep.spec.template.spec.containers[0].resources or V1ResourceRequirements()
            limits = dict(res.limits or {})
            requests = dict(res.requests or {})
            if "memory_limit" in action.params:
                limits["memory"] = action.params["memory_limit"]
            if "memory_request" in action.params:
                requests["memory"] = action.params["memory_request"]
            if "cpu_limit" in action.params:
                limits["cpu"] = action.params["cpu_limit"]
            if "cpu_request" in action.params:
                requests["cpu"] = action.params["cpu_request"]
            res.limits = limits
            res.requests = requests
            dep.spec.template.spec.containers[0].resources = res
            apps.patch_namespaced_deployment(name=name, namespace=namespace, body=dep)
            return True, f"Patched deployment {name} resources"

        if action.kind == RemediationKind.PATCH_DEPLOYMENT_IMAGE_OR_CMD and kind == "deployment":
            dep = apps.read_namespaced_deployment(name=name, namespace=namespace)
            c = dep.spec.template.spec.containers[0]
            if "image" in action.params:
                c.image = action.params["image"]
            if "command" in action.params:
                cmd = action.params["command"]
                c.command = [cmd] if isinstance(cmd, str) else cmd
            if "args" in action.params:
                args = action.params["args"]
                c.args = [args] if isinstance(args, str) else args
            apps.patch_namespaced_deployment(name=name, namespace=namespace, body=dep)
            return True, f"Patched deployment {name} image/command/args"

        if action.kind == RemediationKind.SCALE_DEPLOYMENT and kind == "deployment":
            replicas = action.params.get("replicas")
            if replicas is None:
                return False, "scale_deployment requires params.replicas"
            from kubernetes.client import V1Scale
            scale = V1Scale(
                metadata=client.V1ObjectMeta(name=name, namespace=namespace),
                spec=client.V1ScaleSpec(replicas=int(replicas)),
            )
            apps.patch_namespaced_deployment_scale(name=name, namespace=namespace, body=scale)
            return True, f"Scaled deployment {name} to {replicas} replicas"

        if action.kind == RemediationKind.CUSTOM_INSTRUCTION:
            return True, f"Manual: {action.description}"

        return False, f"Unsupported action kind or target: {action.kind} for {action.target}"
    except ApiException as e:
        logger.exception("Remediation failed: %s", e.body)
        return False, f"API error: {e.reason} - {e.body}"


def verify_healthy(
    namespace: str,
    kubeconfig: str | None = None,
    context: str | None = None,
    timeout_seconds: int = 120,
    check_interval_seconds: int = 5,
) -> tuple[bool, str]:
    """
    Check whether the namespace looks healthy: all pods running and ready, deployments desired=ready.
    Does a single check (caller can poll with timeout). Returns (healthy, message).
    """
    core, apps = _get_api_client(kubeconfig, context)
    try:
        pods = core.list_namespaced_pod(namespace=namespace, limit=100)
        for pod in pods.items:
            if pod.status.phase != "Running":
                return False, f"Pod {pod.metadata.name} is not Running (phase={pod.status.phase})"
            ready = any(
                c.type == "Ready" and c.status == "True"
                for c in (pod.status.conditions or [])
            )
            if not ready:
                return False, f"Pod {pod.metadata.name} is not Ready"
        deps = apps.list_namespaced_deployment(namespace=namespace, limit=100)
        for d in deps.items:
            if (d.status.ready_replicas or 0) != (d.status.replicas or 0):
                return False, f"Deployment {d.metadata.name}: ready_replicas != desired"
    except ApiException as e:
        return False, f"API error: {e.reason}"
    return True, "All pods running and ready; deployments satisfied."
