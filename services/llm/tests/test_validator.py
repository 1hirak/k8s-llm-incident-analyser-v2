import json

import pytest
from app.validator import ReportValidator
from k8s_llm_shared import IncidentReport
from pydantic import ValidationError


@pytest.fixture
def valid_report_dict():
    return {
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
        "suggested_fix": "Set DATABASE_URL in the deployment env or ConfigMap.",
        "recommended_commands": [
            "kubectl describe pod -n demo demo-app-abc",
            "kubectl get configmap -n demo",
        ],
        "human_verification_steps": [
            "Check environment variables in the deployment spec.",
            "Verify the ConfigMap contains DATABASE_URL.",
        ],
    }


class TestReportValidator:
    def test_validator_class_can_be_instantiated(self):
        v = ReportValidator()
        assert v is not None

    def test_validate_dict_returns_incident_report(self, valid_report_dict):
        v = ReportValidator()
        report = v.validate_dict(valid_report_dict)
        assert isinstance(report, IncidentReport)
        assert report.failure_category == "config"

    def test_validate_string_accepts_valid_json(self, valid_report_dict):
        v = ReportValidator()
        report = v.validate_string(json.dumps(valid_report_dict))
        assert isinstance(report, IncidentReport)

    def test_validate_string_rejects_invalid_json(self):
        v = ReportValidator()
        with pytest.raises(ValueError):
            v.validate_string("not json at all")

    def test_validate_rejects_missing_required_field(self, valid_report_dict):
        v = ReportValidator()
        del valid_report_dict["likely_root_cause"]
        with pytest.raises(ValidationError):
            v.validate_dict(valid_report_dict)

    def test_validate_rejects_short_summary(self, valid_report_dict):
        v = ReportValidator()
        valid_report_dict["incident_summary"] = "short"
        with pytest.raises(ValidationError):
            v.validate_dict(valid_report_dict)

    def test_validate_rejects_confidence_out_of_range(self, valid_report_dict):
        v = ReportValidator()
        valid_report_dict["confidence"] = 1.5
        with pytest.raises(ValidationError):
            v.validate_dict(valid_report_dict)

    def test_validate_rejects_invalid_failure_category(self, valid_report_dict):
        v = ReportValidator()
        valid_report_dict["failure_category"] = "not-a-category"
        with pytest.raises(ValidationError):
            v.validate_dict(valid_report_dict)

    def test_validate_rejects_invalid_severity(self, valid_report_dict):
        v = ReportValidator()
        valid_report_dict["severity"] = "extreme"
        with pytest.raises(ValidationError):
            v.validate_dict(valid_report_dict)

    def test_validate_ignores_extra_fields(self, valid_report_dict):
        v = ReportValidator()
        valid_report_dict["unexpected_field"] = "ignored"
        report = v.validate_dict(valid_report_dict)
        assert not hasattr(report, "unexpected_field")

    def test_validate_rejects_empty_supporting_evidence(self, valid_report_dict):
        v = ReportValidator()
        valid_report_dict["supporting_evidence"] = []
        with pytest.raises(ValidationError):
            v.validate_dict(valid_report_dict)

    def test_get_schema_returns_dict(self):
        v = ReportValidator()
        schema = v.get_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "incident_summary" in schema["properties"]

    def test_get_schema_json_returns_string(self):
        v = ReportValidator()
        schema_str = v.get_schema_json()
        assert isinstance(schema_str, str)
        parsed = json.loads(schema_str)
        assert "properties" in parsed

    def test_validate_dispatch_string(self, valid_report_dict):
        v = ReportValidator()
        report = v.validate(json.dumps(valid_report_dict))
        assert isinstance(report, IncidentReport)

    def test_validate_dispatch_dict(self, valid_report_dict):
        v = ReportValidator()
        report = v.validate(valid_report_dict)
        assert isinstance(report, IncidentReport)

    def test_validate_string_rejects_non_dict_json(self):
        v = ReportValidator()
        with pytest.raises(ValueError, match="object"):
            v.validate_string(json.dumps(["a", "list"]))

    def test_validate_string_rejects_scalar_json(self):
        v = ReportValidator()
        with pytest.raises(ValueError, match="object"):
            v.validate_string(json.dumps("just a string"))

    def test_is_valid_returns_true_for_valid(self, valid_report_dict):
        v = ReportValidator()
        assert v.is_valid(valid_report_dict) is True

    def test_is_valid_returns_false_for_invalid(self, valid_report_dict):
        v = ReportValidator()
        del valid_report_dict["likely_root_cause"]
        assert v.is_valid(valid_report_dict) is False

    def test_is_valid_returns_false_for_invalid_json_string(self):
        v = ReportValidator()
        assert v.is_valid("not json") is False

    def test_validate_string_rejects_empty_string(self):
        v = ReportValidator()
        with pytest.raises(ValueError, match="Invalid JSON"):
            v.validate_string("")

    def test_validate_string_rejects_number_json(self):
        v = ReportValidator()
        with pytest.raises(ValueError, match="object"):
            v.validate_string("42")

    def test_validate_string_rejects_boolean_json(self):
        v = ReportValidator()
        with pytest.raises(ValueError, match="object"):
            v.validate_string("true")
