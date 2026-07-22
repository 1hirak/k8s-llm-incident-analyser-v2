import json

from k8s_llm_shared import IncidentReport
from pydantic import ValidationError


class ReportValidator:
    """Validate LLM output against the IncidentReport schema."""

    def validate_dict(self, data: dict) -> IncidentReport:
        return IncidentReport.model_validate(data)

    def validate_string(self, raw: str) -> IncidentReport:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON must be an object, not a scalar or array")
        return self.validate_dict(data)

    def validate(self, data: dict | str) -> IncidentReport:
        if isinstance(data, str):
            return self.validate_string(data)
        return self.validate_dict(data)

    def get_schema(self) -> dict:
        return IncidentReport.model_json_schema()

    def get_schema_json(self) -> str:
        return json.dumps(self.get_schema(), indent=2)

    def is_valid(self, data: dict | str) -> bool:
        try:
            self.validate(data)
            return True
        except (ValidationError, ValueError):
            return False
