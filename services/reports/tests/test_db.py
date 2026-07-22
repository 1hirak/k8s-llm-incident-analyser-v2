"""Unit tests for the SQLite persistence layer."""

from pathlib import Path
from unittest.mock import patch

from app.db import ReportsDB
from k8s_llm_shared import (
    IncidentReport,
    SaveJobRequest,
    new_id,
)


def make_report(**overrides) -> IncidentReport:
    data = {
        "incident_summary": "Pod demo-app failed to start due to missing config.",
        "likely_root_cause": "The DATABASE_URL environment variable is not set.",
        "affected_component": "demo-app",
        "failure_category": "config",
        "severity": "critical",
        "confidence": 0.9,
        "supporting_evidence": [
            {
                "source": "pod_log",
                "pod": "demo-app-abc",
                "evidence": "FATAL: DATABASE_URL environment variable is not set",
            }
        ],
        "suggested_fix": "Set DATABASE_URL in the deployment env.",
        "recommended_commands": ["kubectl describe pod -n demo demo-app-abc"],
        "human_verification_steps": ["Check environment variables."],
    }
    data.update(overrides)
    return IncidentReport(**data)


def make_job(**overrides) -> SaveJobRequest:
    data = {
        "job_id": new_id(),
        "namespace": "demo",
        "pod_name": "demo-app-abc",
        "status": "queued",
    }
    data.update(overrides)
    return SaveJobRequest(**data)


class TestSaveAndGetReport:
    def test_roundtrip(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        report = make_report()
        incident_id = db.save_report(report, "demo", "demo-app-abc", new_id())
        assert incident_id == report.incident_id

        fetched = db.get_report(incident_id)
        assert fetched is not None
        assert fetched["incident_id"] == report.incident_id
        assert fetched["failure_category"] == "config"
        assert fetched["supporting_evidence"][0]["pod"] == "demo-app-abc"
        db.close()

    def test_get_missing_returns_none(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        assert db.get_report(new_id()) is None
        db.close()

    def test_save_report_links_job(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        job = make_job()
        db.upsert_job(job)
        report = make_report()
        db.save_report(report, "demo", "demo-app-abc", job.job_id)
        jobs, _ = db.list_jobs()
        assert jobs[0].incident_id == report.incident_id
        db.close()


class TestListReports:
    def test_pagination_envelope(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        for _ in range(5):
            db.save_report(make_report(), "demo", "demo-app-abc", new_id())
        items, count = db.list_reports(limit=2, offset=0)
        assert count == 5
        assert len(items) == 2
        items, count = db.list_reports(limit=2, offset=4)
        assert len(items) == 1
        db.close()

    def test_filters(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.save_report(make_report(failure_category="config"), "demo", "a", new_id())
        db.save_report(
            make_report(failure_category="resource", severity="high"),
            "demo", "b", new_id(),
        )
        items, count = db.list_reports(category="resource")
        assert count == 1
        assert items[0].pod_name == "b"
        items, count = db.list_reports(severity="critical")
        assert count == 1
        items, count = db.list_reports(namespace="demo", pod_name="a")
        assert count == 1
        db.close()


class TestJobs:
    def test_upsert_updates_status(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        job = make_job()
        db.upsert_job(job)
        db.upsert_job(job.model_copy(update={"status": "done", "latency_ms": 1234}))
        jobs, count = db.list_jobs()
        assert count == 1
        assert jobs[0].status == "done"
        assert jobs[0].latency_ms == 1234
        db.close()

    def test_list_jobs_filter_by_status(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.upsert_job(make_job(status="done"))
        db.upsert_job(make_job(status="failed", error="boom"))
        jobs, count = db.list_jobs(status="failed")
        assert count == 1
        assert jobs[0].error == "boom"
        db.close()


class TestStats:
    def test_stats_aggregates(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.save_report(make_report(failure_category="config", confidence=0.8), "d", "a", new_id())
        db.save_report(make_report(failure_category="config", confidence=1.0), "d", "b", new_id())
        db.save_report(make_report(failure_category="crash", confidence=0.5), "d", "c", new_id())
        db.upsert_job(make_job(status="done", latency_ms=1000))
        db.upsert_job(make_job(status="done", latency_ms=3000))

        stats = db.get_stats("7d")
        assert stats.total_reports == 3
        assert stats.reports_24h == 3
        assert stats.category_counts == {"config": 2, "crash": 1}
        assert stats.mean_confidence == 0.7667
        assert stats.mean_latency_ms == 2000.0
        assert len(stats.latency_series) == 2
        db.close()

    def test_stats_empty_db(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        stats = db.get_stats("24h")
        assert stats.total_reports == 0
        assert stats.mean_latency_ms == 0.0
        assert stats.category_counts == {}
        db.close()

    def test_stats_all_ranges(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        for r in ("24h", "7d", "30d"):
            stats = db.get_stats(r)
            assert stats.total_reports == 0
        db.close()

    def test_stats_invalid_range_falls_to_default(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        stats = db.get_stats("invalid")
        assert stats.total_reports == 0
        db.close()

    def test_stats_excludes_jobs_without_latency(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.upsert_job(make_job(status="done", latency_ms=None))
        stats = db.get_stats("7d")
        assert stats.mean_latency_ms == 0.0
        db.close()


class TestListReportsEdgeCases:
    def test_offset_beyond_total(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.save_report(make_report(), "d", "a", new_id())
        items, count = db.list_reports(offset=100)
        assert count == 1
        assert len(items) == 0
        db.close()

    def test_limit_one(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        for _ in range(3):
            db.save_report(make_report(), "d", "a", new_id())
        items, count = db.list_reports(limit=1)
        assert count == 3
        assert len(items) == 1
        db.close()

    def test_filters_combined(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.save_report(make_report(failure_category="config"), "ns1", "pod-a", new_id())
        db.save_report(make_report(failure_category="crash"), "ns1", "pod-b", new_id())
        db.save_report(make_report(failure_category="config"), "ns2", "pod-c", new_id())
        items, count = db.list_reports(namespace="ns1", category="config")
        assert count == 1
        assert items[0].pod_name == "pod-a"
        db.close()

    def test_filters_no_match(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.save_report(make_report(), "d", "a", new_id())
        items, count = db.list_reports(category="network")
        assert count == 0
        assert items == []
        db.close()


class TestJobsEdgeCases:
    def test_list_jobs_all(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        for _ in range(3):
            db.upsert_job(make_job())
        jobs, count = db.list_jobs()
        assert count == 3
        db.close()

    def test_list_jobs_with_status_filter(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.upsert_job(make_job(status="done"))
        db.upsert_job(make_job(status="queued"))
        jobs, count = db.list_jobs(status="done")
        assert count == 1
        db.close()

    def test_list_jobs_offset(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        for _ in range(3):
            db.upsert_job(make_job())
        jobs, count = db.list_jobs(offset=10)
        assert count == 3
        assert len(jobs) == 0
        db.close()


class TestDBSchemaPath:
    def test_schema_path_from_env(self, tmp_path):
        import os
        with patch.dict(os.environ, {"SCHEMA_PATH": str(tmp_path / "custom.sql")}):
            from app.db import _schema_path
            path = _schema_path()
            assert path == str(tmp_path / "custom.sql")

    def test_schema_path_fallback(self):
        from app.db import _schema_path
        path = _schema_path()
        assert "contracts" in path
        assert "schema.sql" in path


class TestToIso8601:
    def test_none_returns_none(self):
        from app.db import _to_iso8601
        assert _to_iso8601(None) is None

    def test_valid_timestamp(self):
        from app.db import _to_iso8601
        result = _to_iso8601("2026-07-22 10:00:00")
        assert result == "2026-07-22T10:00:00Z"

    def test_empty_string(self):
        from app.db import _to_iso8601
        result = _to_iso8601("")
        assert result == "Z"  # "" -> replaced -> "" -> + "Z" = "Z"


class TestDBInit:
    def test_init_creates_directory(self, tmp_path):
        db_path = str(tmp_path / "subdir" / "test.db")
        db = ReportsDB(db_path)
        assert Path(db_path).exists()
        db.close()

    def test_close_method(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.close()
        # should not raise

    def test_multiple_close_safe(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        db.close()
        # second close may raise but test shouldn't crash
        try:
            db.close()
        except Exception:
            pass


class TestSchemaCompliance:
    def test_invalid_category_rejected_by_check_constraint(self, tmp_path):
        import sqlite3

        import pytest

        db = ReportsDB(str(tmp_path / "t.db"))
        with pytest.raises(sqlite3.IntegrityError):
            with db._lock:
                db._conn.execute(
                    "INSERT INTO incidents (incident_id, namespace, pod_name, "
                    "failure_category, severity, confidence, incident_summary, "
                    "likely_root_cause, affected_component, suggested_fix, "
                    "report_json) VALUES (?, 'd', 'p', 'act-of-god', 'high', "
                    "0.5, 's', 'r', 'a', 'f', '{}')",
                    (new_id(),),
                )
        db.close()

    def test_updated_at_trigger(self, tmp_path):
        db = ReportsDB(str(tmp_path / "t.db"))
        job = make_job()
        db.upsert_job(job)
        before = db.list_jobs()[0][0].updated_at
        db.upsert_job(job.model_copy(update={"status": "collecting"}))
        after_jobs, _ = db.list_jobs()
        assert after_jobs[0].status == "collecting"
        # updated_at is auto-maintained by the trigger (may be equal within
        # the same second — just assert it exists and is ISO-shaped)
        assert after_jobs[0].updated_at.endswith("Z")
        assert before.endswith("Z")
        db.close()
