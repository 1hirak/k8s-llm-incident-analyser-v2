"""Realistic EvidencePackage fixtures for all 10 fault scenarios.

These fixtures simulate what LogPreprocessor.process() would output after
processing raw k8s evidence (kubectl logs, describe, events) from each
scenario deployed on a real cluster.

Each fixture is derived from:
- Ground truth expected_log_patterns and expected_event_reasons
- Demo app source code (what logs it actually produces)
- Kubernetes pod/event output format for each failure mode
"""
from k8s_llm_shared import EvidencePackage

SCENARIO_IDS = [
    "01-missing-env",
    "02-db-unavailable",
    "03-crashloop",
    "04-imagepull",
    "05-oom",
    "06-readiness",
    "07-liveness",
    "08-bad-configmap",
    "09-app-exception",
    "10-wrong-port",
]

# Ground truth categories for assertion in tests
TRUE_CATEGORIES = {
    "01-missing-env": "config",
    "02-db-unavailable": "dependency",
    "03-crashloop": "crash",
    "04-imagepull": "image",
    "05-oom": "resource",
    "06-readiness": "probe",
    "07-liveness": "probe",
    "08-bad-configmap": "config",
    "09-app-exception": "crash",
    "10-wrong-port": "network",
}


def scenario_01_missing_env() -> EvidencePackage:
    """DATABASE_URL env var set to empty → app raises RuntimeError on startup."""
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs=(
            "FATAL: DATABASE_URL environment variable is not set\n"
            "RuntimeError: Missing required configuration: DATABASE_URL"
        ),
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Waiting\n"
            "      Reason:       CrashLoopBackOff\n"
            "    Last State:      Terminated\n"
            "      Reason:       Error\n"
            "      Exit Code:    1\n"
            "    Ready:          False\n"
            "    Restart Count:  5\n"
            "Events:\n"
            "  Warning  BackOff   2m  Back-off restarting failed container"
        ),
        k8s_events_filtered=(
            "Warning BackOff: Back-off restarting failed container demo-app "
            "in pod demo-app-abc123"
        ),
        restart_count=5,
    )


def scenario_02_db_unavailable() -> EvidencePackage:
    """DATABASE_URL set to unreachable host → readiness probe fails with 500."""
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs=(
            "ERROR: Application error: RuntimeError: "
            "Database connection failed: connection refused"
        ),
        previous_logs="",
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Running\n"
            "    Ready:          False\n"
            "    Restart Count:  0\n"
            "Events:\n"
            "  Warning  Unhealthy  1m  Readiness probe failed: "
            "HTTP probe failed with statuscode: 500"
        ),
        k8s_events_filtered=(
            "Warning Unhealthy: Readiness probe failed: "
            "HTTP probe failed with statuscode: 500"
        ),
        restart_count=0,
    )


def scenario_03_crashloop() -> EvidencePackage:
    """Container command set to /bin/nonexistent → CrashLoopBackOff."""
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs="",
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Waiting\n"
            "      Reason:       CrashLoopBackOff\n"
            "    Last State:      Terminated\n"
            "      Reason:       ContainerCannotRun\n"
            "      Message:       executable file not found in $PATH: /bin/nonexistent\n"
            "      Exit Code:    127\n"
            "    Ready:          False\n"
            "    Restart Count:  8\n"
            "Events:\n"
            "  Warning  BackOff   1m  Back-off restarting failed container"
        ),
        k8s_events_filtered=(
            "Warning BackOff: Back-off restarting failed container demo-app "
            "in pod demo-app-abc123\n"
            "Warning Failed: Error: container has failed to start"
        ),
        restart_count=8,
    )


def scenario_04_imagepull() -> EvidencePackage:
    """Image set to nonexistent tag → ImagePullBackOff."""
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs="",
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Waiting\n"
            "      Reason:       ImagePullBackOff\n"
            "    Ready:          False\n"
            "    Restart Count:  0\n"
            "Events:\n"
            "  Warning  Failed   30s  Failed to pull image "
            "demo-app:nonexistent-tag: manifest not found\n"
            "  Warning  BackOff  30s  Back-off pulling image "
            "demo-app:nonexistent-tag"
        ),
        k8s_events_filtered=(
            "Warning Failed: Error: ImagePullBackOff\n"
            "Warning Failed: Failed to pull image demo-app:nonexistent-tag: "
            "rpc error: decoding manifest: manifest not found\n"
            "Warning BackOff: Back-off pulling image demo-app:nonexistent-tag"
        ),
        restart_count=0,
    )


def scenario_05_oom() -> EvidencePackage:
    """Memory limit 32Mi → OOMKilled when /fault/oom endpoint is hit."""
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs="",
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Running\n"
            "    Last State:      Terminated\n"
            "      Reason:       OOMKilled\n"
            "      Exit Code:    137\n"
            "    Ready:          True\n"
            "    Restart Count:  3\n"
            "Events:\n"
            "  Warning  Killing  2m  Container demo-app was killed due to OOMKilled"
        ),
        k8s_events_filtered=(
            "Warning Killing: Container demo-app was killed due to OOMKilled\n"
            "Warning BackOff: Back-off restarting failed container"
        ),
        restart_count=3,
    )


def scenario_06_readiness() -> EvidencePackage:
    """Readiness probe path set to /does-not-exist → 404 → Ready=False."""
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs="",
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Running\n"
            "    Ready:          False\n"
            "    Restart Count:  0\n"
            "Events:\n"
            "  Warning  Unhealthy  5m  Readiness probe failed: "
            "HTTP probe failed with statuscode: 404"
        ),
        k8s_events_filtered=(
            "Warning Unhealthy: Readiness probe failed: "
            "HTTP probe failed with statuscode: 404\n"
            "Warning Unhealthy: Readiness probe failed: "
            "HTTP probe failed with statuscode: 404"
        ),
        restart_count=0,
    )


def scenario_07_liveness() -> EvidencePackage:
    """Liveness probe path /fault/slow → timeout → Killing → restarts."""
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs="",
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Running\n"
            "    Last State:      Terminated\n"
            "      Reason:       Error\n"
            "      Exit Code:    137\n"
            "    Ready:          True\n"
            "    Restart Count:  4\n"
            "Events:\n"
            "  Warning  Unhealthy  2m  Liveness probe failed: "
            "HTTP probe failed with statuscode: 504\n"
            "  Warning  Killing   2m  "
            "Container demo-app failed liveness probe"
        ),
        k8s_events_filtered=(
            "Warning Unhealthy: Liveness probe failed: "
            "HTTP probe failed with statuscode: 504\n"
            "Warning Killing: Container demo-app failed liveness probe"
        ),
        restart_count=4,
    )


def scenario_08_bad_configmap() -> EvidencePackage:
    """ConfigMap LOG_LEVEL=INVALID → app runs fine (subtle, no crash).

    This is an intentionally subtle scenario. The demo app does not validate
    LOG_LEVEL, so the pod runs normally. Without configmap inspection in the
    collector, there are no error signals in pod evidence.
    """
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs="",
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Running\n"
            "    Ready:          True\n"
            "    Restart Count:  0\n"
            "Environment Variables from ConfigMap:\n"
            "  APP_ENV=development\n"
            "  LOG_LEVEL=INVALID"
        ),
        k8s_events_filtered="",
        restart_count=0,
    )


def scenario_09_app_exception() -> EvidencePackage:
    """STARTUP_FAULT=crash → app raises RuntimeError on startup → CrashLoopBackOff."""
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs=(
            "FATAL: STARTUP_FAULT=crash -- raising exception on startup\n"
            "RuntimeError: Deliberate startup crash for scenario testing\n"
            "Traceback (most recent call last):\n"
            "  File app/main.py, line 19, in lifespan\n"
            "    raise RuntimeError('Deliberate startup crash')"
        ),
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Waiting\n"
            "      Reason:       CrashLoopBackOff\n"
            "    Last State:      Terminated\n"
            "      Reason:       Error\n"
            "      Exit Code:    1\n"
            "    Ready:          False\n"
            "    Restart Count:  6\n"
            "Events:\n"
            "  Warning  BackOff   2m  Back-off restarting failed container"
        ),
        k8s_events_filtered=(
            "Warning BackOff: Back-off restarting failed container demo-app "
            "in pod demo-app-abc123"
        ),
        restart_count=6,
    )


def scenario_10_wrong_port() -> EvidencePackage:
    """Service targetPort=9999 but pod listens on 8000 → no pod errors.

    The pod runs fine. The Service cannot reach it. Without service/endpoint
    inspection in the collector, there are no error signals in pod evidence.
    """
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc123",
        current_logs="",
        previous_logs="",
        pod_status_summary=(
            "Name:         demo-app-abc123\n"
            "Namespace:    demo\n"
            "Containers:\n"
            "  demo-app:\n"
            "    State:          Running\n"
            "    Ready:          True\n"
            "    Restart Count:  0\n"
            "    Port:           8000/TCP"
        ),
        k8s_events_filtered="",
        restart_count=0,
    )


_FIXTURES = {
    "01-missing-env": scenario_01_missing_env,
    "02-db-unavailable": scenario_02_db_unavailable,
    "03-crashloop": scenario_03_crashloop,
    "04-imagepull": scenario_04_imagepull,
    "05-oom": scenario_05_oom,
    "06-readiness": scenario_06_readiness,
    "07-liveness": scenario_07_liveness,
    "08-bad-configmap": scenario_08_bad_configmap,
    "09-app-exception": scenario_09_app_exception,
    "10-wrong-port": scenario_10_wrong_port,
}


def get_evidence(scenario_id: str) -> EvidencePackage:
    """Return the EvidencePackage fixture for the given scenario."""
    if scenario_id not in _FIXTURES:
        raise KeyError(f"Unknown scenario: {scenario_id}")
    return _FIXTURES[scenario_id]()


def all_fixtures() -> dict[str, EvidencePackage]:
    """Return all 10 scenario fixtures as a dict."""
    return {sid: fn() for sid, fn in _FIXTURES.items()}
