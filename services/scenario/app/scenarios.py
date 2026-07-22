"""Fault scenario manager — list, apply, and reset k8s fault scenarios.

Implements the scenario-svc behaviour from contracts/api/scenario.yaml.
Scenario metadata is enriched from evaluation/ground_truth/{id}.json when
available. Faults are applied via kubectl strategic-merge patch, matching
scripts/run_scenario.sh semantics.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from k8s_llm_shared import ScenarioSummary

logger = logging.getLogger(__name__)


class ScenarioNotFoundError(Exception):
    pass


class ScenarioConflictError(Exception):
    pass


class KubectlError(Exception):
    pass


class ClusterUnreachableError(KubectlError):
    pass


class ScenarioManager:
    def __init__(
        self,
        scenarios_dir: str,
        base_dir: str,
        namespace: str = "demo",
        ground_truth_dir: str | None = None,
        kubectl_path: str = "kubectl",
        timeout: int = 60,
    ):
        self.scenarios_dir = Path(scenarios_dir)
        self.base_dir = Path(base_dir)
        self.namespace = namespace
        self.ground_truth_dir = Path(ground_truth_dir) if ground_truth_dir else None
        self.kubectl = kubectl_path
        self.timeout = timeout
        self._active: str | None = None

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_scenarios(self) -> list[ScenarioSummary]:
        scenarios = []
        if not self.scenarios_dir.is_dir():
            return scenarios
        for path in sorted(self.scenarios_dir.iterdir()):
            if path.is_dir() and (path / "fault.yaml").exists():
                scenarios.append(self._summarize(path.name))
        return scenarios

    def _summarize(self, scenario_id: str) -> ScenarioSummary:
        meta = self._ground_truth(scenario_id)
        name = _humanize_name(scenario_id)
        description = f"Fault scenario {scenario_id}"
        category = "unknown"
        severity = None
        if meta:
            description = meta.get("description", description)
            category = meta.get("true_failure_category", category)
            severity = meta.get("true_severity")
        return ScenarioSummary(
            scenario_id=scenario_id,
            name=name,
            category=category,  # type: ignore[arg-type]
            description=description,
            severity=severity,  # type: ignore[arg-type]
        )

    def _ground_truth(self, scenario_id: str) -> dict | None:
        if self.ground_truth_dir is None:
            return None
        path = self.ground_truth_dir / f"{scenario_id}.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Apply / reset
    # ------------------------------------------------------------------

    @property
    def active_scenario(self) -> str | None:
        return self._active

    def apply(self, scenario_id: str) -> str:
        """Apply the scenario's fault patch. Returns a fault description."""
        if self._active is not None:
            raise ScenarioConflictError(
                f"Scenario '{self._active}' is already applied — reset first"
            )
        fault_path = self.scenarios_dir / scenario_id / "fault.yaml"
        if not fault_path.is_file():
            raise ScenarioNotFoundError(
                f"No fault.yaml found for scenario '{scenario_id}'"
            )
        patch = fault_path.read_text()
        kind, resource_name = _parse_patch_target(patch)
        self._run(
            "patch", f"{kind}/{resource_name}", "-n", self.namespace,
            "--type", "strategic", "-p", patch,
        )
        self._active = scenario_id
        meta = self._ground_truth(scenario_id)
        return (meta or {}).get("description", f"Applied fault {scenario_id}")

    def reset(self) -> None:
        """Reset the cluster to the healthy baseline."""
        # Best-effort delete, then re-apply base and wait for rollout
        self._run(
            "delete", "deployment", "demo-app", "-n", self.namespace,
            "--ignore-not-found",
        )
        for manifest in ("namespace", "configmap", "deployment", "service"):
            path = self.base_dir / f"{manifest}.yaml"
            if path.is_file():
                self._run("apply", "-f", str(path))
        self._run(
            "rollout", "status", "deployment/demo-app",
            "-n", self.namespace, "--timeout=120s",
        )
        self._active = None

    # ------------------------------------------------------------------
    # kubectl
    # ------------------------------------------------------------------

    def check_connectivity(self) -> bool:
        try:
            result = subprocess.run(
                [self.kubectl, "version", "--client=false"],
                capture_output=True, text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _run(self, *args: str) -> str:
        cmd = [self.kubectl, *args]
        logger.info("Running: %s", " ".join(cmd)[:200])
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise KubectlError(f"kubectl timed out: {' '.join(cmd[:3])}") from e
        if result.returncode != 0:
            raise KubectlError(
                f"kubectl exited {result.returncode}: {result.stderr[:300]}"
            )
        return result.stdout.strip()


def _humanize_name(scenario_id: str) -> str:
    """'05-oom' -> 'Oom'; '01-missing-env' -> 'Missing Env'."""
    suffix = re.sub(r"^\d+-", "", scenario_id)
    return suffix.replace("-", " ").title()


def _parse_patch_target(patch: str) -> tuple[str, str]:
    """Extract (kind, metadata.name) from a strategic merge patch.

    Uses the same line-scan approach as scripts/run_scenario.sh, avoiding
    a YAML dependency for a two-field extraction.
    """
    kind = "deployment"
    name = "demo-app"
    in_metadata = False
    for line in patch.splitlines():
        stripped = line.strip()
        if stripped.startswith("kind:"):
            kind = stripped.split(":", 1)[1].strip().lower()
        elif re.match(r"^metadata:\s*$", stripped):
            in_metadata = True
        elif in_metadata and stripped.startswith("name:"):
            name = stripped.split(":", 1)[1].strip()
            in_metadata = False
    return kind, name
