"""Contract parity tests for the shared models package.

Validates the alignment rules from contracts/README.md §4:
- Enum parity with contracts/database/schema.sql CHECK constraints
- UUIDv7 ID format (§4.4)
- ISO 8601 timestamps (§4.5)
- RFC 7807 error shape (§4.6)
"""

import re
import uuid
from pathlib import Path

import pytest
from k8s_llm_shared import (
    AnalysisRequest,
    EvidenceItem,
    EvidencePackage,
    HealthResponse,
    IncidentReport,
    JobCreated,
    JobState,
    LatencyPoint,
    ProblemDetail,
    ProviderInfo,
    RawEvidence,
    ReportSummary,
    SaveJobRequest,
    SaveReportRequest,
    SaveReportResponse,
    ScenarioApplyResponse,
    ScenarioSummary,
    SseDoneEvent,
    SseFailedEvent,
    SseStageEvent,
    StatsResponse,
    new_id,
    utc_now_iso,
)
from k8s_llm_shared.web import health_payload
from pydantic import ValidationError

SCHEMA_SQL = (
    Path(__file__).resolve().parents[3] / "contracts" / "database" / "schema.sql"
)


def _make_report(**overrides) -> IncidentReport:
    data = {
        "incident_summary": "Pod is crash looping repeatedly",
        "likely_root_cause": "Container exceeded memory limit",
        "affected_component": "demo-app",
        "failure_category": "resource",
        "severity": "high",
        "confidence": 0.85,
        "supporting_evidence": [
            {"source": "pod_status", "pod": "demo-app", "evidence": "OOMKilled"}
        ],
        "suggested_fix": "Increase the memory limit",
        "recommended_commands": ["kubectl describe pod demo-app -n demo"],
        "human_verification_steps": ["Check memory usage"],
    }
    data.update(overrides)
    return IncidentReport(**data)


class TestIdFormat:
    def test_new_id_is_valid_uuid(self):
        parsed = uuid.UUID(new_id())
        assert parsed.version == 7

    def test_new_ids_are_unique(self):
        ids = {new_id() for _ in range(100)}
        assert len(ids) == 100

    def test_timestamp_iso8601_z_suffix(self):
        ts = utc_now_iso()
        assert ts.endswith("Z")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts)

    def test_new_id_36_chars(self):
        assert len(new_id()) == 36

    def test_utc_now_iso_has_correct_format(self):
        ts = utc_now_iso()
        assert ts.count("-") == 2
        assert ts.count(":") == 2
        assert "T" in ts


class TestIncidentReport:
    def test_defaults_populated(self):
        report = _make_report()
        uuid.UUID(report.incident_id)  # must parse as UUID
        assert report.created_at.endswith("Z")

    def test_summary_min_length(self):
        with pytest.raises(ValidationError):
            _make_report(incident_summary="short")

    def test_root_cause_min_length(self):
        with pytest.raises(ValidationError):
            _make_report(likely_root_cause="short")

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            _make_report(confidence=1.5)
        with pytest.raises(ValidationError):
            _make_report(confidence=-0.1)

    def test_requires_at_least_one_evidence(self):
        with pytest.raises(ValidationError):
            _make_report(supporting_evidence=[])

    def test_extra_fields_ignored(self):
        report = _make_report(some_random_field="x")
        assert not hasattr(report, "some_random_field")

    def test_all_categories_accepted(self):
        for cat in [
            "crash", "config", "dependency", "network",
            "image", "resource", "probe", "unknown",
        ]:
            assert _make_report(failure_category=cat).failure_category == cat

    def test_all_severities_accepted(self):
        for sev in ["low", "medium", "high", "critical"]:
            assert _make_report(severity=sev).severity == sev

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            _make_report(failure_category="act-of-god")

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            _make_report(severity="unknown")

    def test_suggested_fix_empty_accepted(self):
        report = _make_report(suggested_fix="")
        assert report.suggested_fix == ""

    def test_confidence_edge_values(self):
        report = _make_report(confidence=0.0)
        assert report.confidence == 0.0
        report = _make_report(confidence=1.0)
        assert report.confidence == 1.0

    def test_recommended_commands_empty_accepted(self):
        report = _make_report(recommended_commands=[], human_verification_steps=[])
        assert report.recommended_commands == []
        assert report.human_verification_steps == []

    def test_serialize_roundtrip(self):
        report = _make_report()
        data = report.model_dump()
        restored = IncidentReport(**data)
        assert restored.incident_id == report.incident_id
        assert restored.failure_category == report.failure_category

    def test_json_roundtrip(self):
        report = _make_report()
        raw = report.model_dump_json()
        restored = IncidentReport.model_validate_json(raw)
        assert restored.incident_id == report.incident_id


class TestEvidenceItem:
    def test_valid_sources(self):
        for source in [
            "pod_log", "previous_pod_log", "kubernetes_event", "pod_status"
        ]:
            item = EvidenceItem(source=source, pod="p", evidence="e")
            assert item.source == source

    def test_timestamp_optional(self):
        item = EvidenceItem(source="pod_log", pod="p", evidence="e")
        assert item.timestamp is None

    def test_timestamp_settable(self):
        item = EvidenceItem(
            source="pod_log", pod="p", evidence="e",
            timestamp="2026-07-22T10:00:00Z",
        )
        assert item.timestamp == "2026-07-22T10:00:00Z"

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceItem(source="invalid", pod="p", evidence="e")

    def test_evidence_required(self):
        with pytest.raises(ValidationError):
            EvidenceItem(source="pod_log", pod="p")

    def test_pod_required(self):
        with pytest.raises(ValidationError):
            EvidenceItem(source="pod_log", evidence="e")


class TestJobState:
    def _make(self, **kw):
        base = {
            "job_id": new_id(),
            "namespace": "demo",
            "pod_name": "demo-app",
            "status": "queued",
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        }
        base.update(kw)
        return JobState(**base)

    def test_all_statuses_accepted(self):
        for status in [
            "queued", "collecting", "processing",
            "llm_call", "persisting", "done", "failed",
        ]:
            assert self._make(status=status).status == status

    def test_terminal_fields_nullable(self):
        job = self._make(status="done")
        assert job.incident_id is None
        assert job.latency_ms is None
        assert job.error is None

    def test_terminal_fields_filled(self):
        job = self._make(
            status="done", incident_id="inc-001",
            latency_ms=1234, error="",
        )
        assert job.incident_id == "inc-001"
        assert job.latency_ms == 1234

    def test_stage_settable(self):
        job = self._make(status="collecting", stage="Collecting evidence")
        assert job.stage == "Collecting evidence"

    def test_created_at_updated_at_format(self):
        job = self._make()
        assert job.created_at.endswith("Z")
        assert job.updated_at.endswith("Z")

    def test_latency_ms_int_only(self):
        with pytest.raises(ValidationError):
            self._make(status="done", latency_ms=12.5)


class TestProblemDetail:
    def test_rfc7807_shape(self):
        problem = ProblemDetail.of(404, "Job not found", "No job 'abc'")
        data = problem.model_dump()
        assert data["type"] == "https://errors.k8s-llm.io/job-not-found"
        assert data["title"] == "Job not found"
        assert data["status"] == 404
        assert data["detail"] == "No job 'abc'"

    def test_explicit_type_slug(self):
        problem = ProblemDetail.of(
            500, "Internal", "boom", type_slug="internal"
        )
        assert problem.type == "https://errors.k8s-llm.io/internal"

    def test_with_instance(self):
        problem = ProblemDetail.of(
            400, "Bad request", "invalid", instance="/api/jobs"
        )
        assert problem.instance == "/api/jobs"

    def test_without_instance(self):
        problem = ProblemDetail.of(200, "OK", "all good")
        assert problem.instance is None

    def test_serialization_exclude_none(self):
        problem = ProblemDetail.of(200, "OK", "all good")
        data = problem.model_dump(exclude_none=True)
        assert "instance" not in data

    def test_type_url_format(self):
        problem = ProblemDetail.of(500, "Server Error", "oops")
        assert problem.type.startswith("https://errors.")
        assert "server-error" in problem.type


class TestAnalysisRequest:
    def test_namespace_defaults_to_demo(self):
        req = AnalysisRequest(pod_name="my-pod")
        assert req.namespace == "demo"
        assert req.pod_name == "my-pod"

    def test_namespace_overridable(self):
        req = AnalysisRequest(namespace="production", pod_name="my-pod")
        assert req.namespace == "production"

    def test_pod_name_required(self):
        with pytest.raises(ValidationError):
            AnalysisRequest()


class TestEvidencePackage:
    def test_all_fields_required(self):
        pkg = EvidencePackage(
            namespace="ns", pod_name="p",
            current_logs="log1", previous_logs="log2",
            pod_status_summary="running", k8s_events_filtered="events",
            restart_count=3,
        )
        assert pkg.namespace == "ns"
        assert pkg.restart_count == 3

    def test_restart_count_defaults(self):
        with pytest.raises(ValidationError):
            EvidencePackage(
                namespace="ns", pod_name="p",
                current_logs="", previous_logs="",
                pod_status_summary="", k8s_events_filtered="",
            )


class TestRawEvidence:
    def test_all_fields_default(self):
        ev = RawEvidence(namespace="ns", pod_name="p")
        assert ev.current_logs == ""
        assert ev.restart_count == 0
        assert ev.container_states == []

    def test_container_states_defaults_to_list(self):
        ev = RawEvidence(namespace="ns", pod_name="p")
        assert isinstance(ev.container_states, list)

    def test_with_container_states(self):
        ev = RawEvidence(
            namespace="ns", pod_name="p",
            container_states=[{"name": "app", "state": {"running": {}}}],
        )
        assert len(ev.container_states) == 1


class TestJobCreated:
    def test_all_fields(self):
        jc = JobCreated(job_id="job-123", status="queued")
        assert jc.job_id == "job-123"
        assert jc.status == "queued"

    def test_serialize(self):
        jc = JobCreated(job_id="job-123", status="done")
        data = jc.model_dump()
        assert data == {"job_id": "job-123", "status": "done"}


class TestSaveJobRequest:
    def test_minimal(self):
        sj = SaveJobRequest(
            job_id="j1", namespace="ns", pod_name="p", status="queued",
        )
        assert sj.incident_id is None
        assert sj.error is None

    def test_full(self):
        sj = SaveJobRequest(
            job_id="j1", namespace="ns", pod_name="p",
            status="done", incident_id="inc-1",
            latency_ms=500, error="",
        )
        assert sj.latency_ms == 500

    def test_stage_present(self):
        sj = SaveJobRequest(
            job_id="j1", namespace="ns", pod_name="p",
            status="collecting", stage="Collecting evidence",
        )
        assert sj.stage == "Collecting evidence"


class TestSaveReportRequest:
    def test_roundtrip(self):
        report = _make_report()
        req = SaveReportRequest(
            report=report, namespace="ns", pod_name="p", job_id="j1",
        )
        assert req.report.incident_id == report.incident_id
        assert req.namespace == "ns"

    def test_all_fields(self):
        report = _make_report()
        req = SaveReportRequest(
            report=report, namespace="demo", pod_name="pod", job_id="job-1",
        )
        data = req.model_dump()
        assert data["job_id"] == "job-1"
        assert data["report"]["failure_category"] == "resource"


class TestSaveReportResponse:
    def test_incident_id(self):
        resp = SaveReportResponse(incident_id="inc-001")
        assert resp.incident_id == "inc-001"


class TestProviderInfo:
    def test_all_fields(self):
        pi = ProviderInfo(id="mock", name="Mock", model="v1", available=True)
        assert pi.id == "mock"
        assert pi.available is True

    def test_not_available(self):
        pi = ProviderInfo(id="openai", name="OpenAI", model="gpt-4", available=False)
        assert pi.available is False

    def test_all_provider_ids_accepted(self):
        for pid in ["mock", "openai", "anthropic", "deepseek"]:
            pi = ProviderInfo(id=pid, name=pid, model="m", available=True)
            assert pi.id == pid


class TestHealthResponse:
    def test_minimal(self):
        hr = HealthResponse(service="test-svc", version="0.1.0")
        assert hr.status == "ok"
        assert hr.provider is None

    def test_all_fields(self):
        hr = HealthResponse(
            service="llm-svc", version="1.0", provider="mock",
            model="gpt-4", cluster="connected",
        )
        assert hr.provider == "mock"
        assert hr.cluster == "connected"

    def test_health_payload_helper(self):
        payload = health_payload("test-svc")
        assert payload["status"] == "ok"
        assert payload["service"] == "test-svc"
        assert "version" in payload

    def test_health_payload_with_extras(self):
        payload = health_payload("custom-svc", provider="openai", model="gpt-4")
        assert payload["provider"] == "openai"
        assert payload["model"] == "gpt-4"

    def test_health_payload_with_cluster(self):
        payload = health_payload("collector-svc", cluster="connected")
        assert payload["cluster"] == "connected"


class TestSseEvents:
    def test_stage_event(self):
        ev = SseStageEvent(
            job_id="j1", status="collecting",
            stage="Collecting evidence", updated_at=utc_now_iso(),
        )
        assert ev.event == "stage"
        assert ev.status == "collecting"

    def test_done_event(self):
        ev = SseDoneEvent(
            job_id="j1", incident_id="inc-1",
            failure_category="config", severity="high", latency_ms=500,
        )
        assert ev.event == "done"
        assert ev.status == "done"
        assert ev.latency_ms == 500

    def test_failed_event(self):
        ev = SseFailedEvent(
            job_id="j1", error="timeout", latency_ms=1000,
        )
        assert ev.event == "failed"
        assert ev.status == "failed"
        assert "timeout" in ev.error


class TestScenarioModels:
    def test_scenario_summary(self):
        ss = ScenarioSummary(
            scenario_id="01-missing-env", name="Missing Env",
            category="config", description="DATABASE_URL empty",
        )
        assert ss.severity is None

    def test_scenario_summary_with_severity(self):
        ss = ScenarioSummary(
            scenario_id="05-oom", name="OOM", category="resource",
            description="Memory limit reduced", severity="high",
        )
        assert ss.severity == "high"

    def test_apply_response(self):
        resp = ScenarioApplyResponse(
            applied=True, scenario_id="05-oom",
            fault_description="Memory limit 32Mi",
        )
        assert resp.applied is True
        assert resp.fault_description == "Memory limit 32Mi"

    def test_apply_response_no_description(self):
        resp = ScenarioApplyResponse(applied=False, scenario_id="x")
        assert resp.fault_description is None


class TestStatsModels:
    def test_latency_point(self):
        lp = LatencyPoint(timestamp=utc_now_iso(), latency_ms=500)
        assert lp.latency_ms == 500

    def test_stats_response(self):
        sr = StatsResponse(
            total_reports=10, reports_24h=5,
            mean_latency_ms=1200.5, mean_confidence=0.85,
            category_counts={"config": 1, "crash": 2},
        )
        assert sr.total_reports == 10
        assert sr.category_counts["config"] == 1
        assert sr.latency_series == []

    def test_stats_with_latency_series(self):
        sr = StatsResponse(
            total_reports=1, reports_24h=1,
            mean_latency_ms=100.0, mean_confidence=0.5,
            category_counts={},
            latency_series=[LatencyPoint(timestamp=utc_now_iso(), latency_ms=100)],
        )
        assert len(sr.latency_series) == 1

    def test_mean_confidence_bounds(self):
        with pytest.raises(ValidationError):
            StatsResponse(
                total_reports=0, reports_24h=0,
                mean_latency_ms=0.0, mean_confidence=1.5,
                category_counts={},
            )

    def test_mean_latency_zero_allowed(self):
        sr = StatsResponse(
            total_reports=0, reports_24h=0,
            mean_latency_ms=0.0, mean_confidence=0.0,
            category_counts={},
        )
        assert sr.mean_latency_ms == 0.0


class TestReportSummary:
    def test_all_fields(self):
        rs = ReportSummary(
            incident_id="inc-1", namespace="demo", pod_name="p",
            failure_category="crash", severity="high", confidence=0.9,
            incident_summary="Pod crashed", created_at=utc_now_iso(),
        )
        assert rs.confidence == 0.9
        assert rs.severity == "high"

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            ReportSummary(
                incident_id="i", namespace="n", pod_name="p",
                failure_category="crash", severity="low", confidence=1.1,
                incident_summary="x", created_at="now",
            )


class TestSchemaSqlParity:
    """Enum values must match the SQLite CHECK constraints exactly (§4.3)."""

    @pytest.fixture(scope="class")
    def schema_text(self) -> str:
        return SCHEMA_SQL.read_text()

    def test_failure_category_parity(self, schema_text):
        for cat in [
            "crash", "config", "dependency", "network",
            "image", "resource", "probe", "unknown",
        ]:
            assert f"'{cat}'" in schema_text

    def test_severity_parity(self, schema_text):
        for sev in ["low", "medium", "high", "critical"]:
            assert f"'{sev}'" in schema_text

    def test_job_status_parity(self, schema_text):
        for status in [
            "queued", "collecting", "processing",
            "llm_call", "persisting", "done", "failed",
        ]:
            assert f"'{status}'" in schema_text

    def test_schema_file_exists(self):
        assert SCHEMA_SQL.exists()


class TestWebHelpers:
    def test_add_error_handlers_does_not_crash(self):
        from fastapi import FastAPI
        from k8s_llm_shared.web import add_error_handlers

        test_app = FastAPI()
        add_error_handlers(test_app)
        assert test_app.exception_handlers

    def test_health_payload_default_version(self):
        payload = health_payload("test")
        assert payload["version"] == "0.1.0"

    def test_health_payload_status_always_ok(self):
        payload = health_payload("x")
        assert payload["status"] == "ok"
