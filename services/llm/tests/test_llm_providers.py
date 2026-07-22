import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.llm import get_provider
from app.llm.base import BaseLLMProvider
from app.llm.mock_provider import MockProvider
from k8s_llm_shared import EvidencePackage, IncidentReport


@pytest.fixture
def evidence_package():
    return EvidencePackage(
        namespace="demo",
        pod_name="demo-app-abc",
        current_logs="ERROR Missing DATABASE_URL",
        previous_logs="WARN previous log",
        pod_status_summary="Status: CrashLoopBackOff",
        k8s_events_filtered="Warning BackOff restarting",
        restart_count=3,
    )


class TestBaseLLMProvider:
    def test_abstract_class_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseLLMProvider()


class TestMockProvider:
    def test_mock_provider_is_concrete(self):
        provider = MockProvider()
        assert isinstance(provider, BaseLLMProvider)

    @pytest.mark.asyncio
    async def test_analyse_returns_incident_report(self, evidence_package):
        provider = MockProvider()
        report = await provider.analyse(evidence_package)
        assert isinstance(report, IncidentReport)

    @pytest.mark.asyncio
    async def test_analyse_detects_config_failure(self, evidence_package):
        provider = MockProvider()
        report = await provider.analyse(evidence_package)
        assert report.failure_category == "config"
        assert "DATABASE_URL" in report.likely_root_cause

    @pytest.mark.asyncio
    async def test_analyse_is_async(self, evidence_package):
        provider = MockProvider()
        report = await provider.analyse(evidence_package)
        assert isinstance(report, IncidentReport)

    @pytest.mark.asyncio
    async def test_detects_connection_refused(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="ERROR connection refused to database",
            previous_logs="", pod_status_summary="", k8s_events_filtered="",
            restart_count=1,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "dependency"

    @pytest.mark.asyncio
    async def test_detects_oom(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="memory allocation failed",
            previous_logs="", pod_status_summary="OOMKilled container demo",
            k8s_events_filtered="", restart_count=1,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "resource"

    @pytest.mark.asyncio
    async def test_detects_image_pull_failure(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="ImagePullBackOff error",
            previous_logs="", pod_status_summary="",
            k8s_events_filtered="", restart_count=0,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "image"

    @pytest.mark.asyncio
    async def test_defaults_to_unknown(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="INFO normal operation", previous_logs="",
            pod_status_summary="Status: Running", k8s_events_filtered="",
            restart_count=0,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "unknown"
        assert report.confidence == 0.5

    @pytest.mark.asyncio
    async def test_detects_crashloop_container_cannot_run(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="", previous_logs="",
            pod_status_summary="CrashLoopBackOff\nMessage: executable file not found\nContainerCannotRun",
            k8s_events_filtered="Warning Failed: container has failed to start",
            restart_count=8,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "crash"

    @pytest.mark.asyncio
    async def test_detects_readiness_probe_failure(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="", previous_logs="",
            pod_status_summary="Running\nReady: False",
            k8s_events_filtered="Warning Unhealthy: Readiness probe failed with statuscode: 404",
            restart_count=0,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "probe"

    @pytest.mark.asyncio
    async def test_detects_liveness_probe_failure(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="", previous_logs="",
            pod_status_summary="Running\nLiveness probe failed: HTTP probe statuscode: 504",
            k8s_events_filtered="Warning Unhealthy: Liveness probe failed",
            restart_count=4,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "probe"

    @pytest.mark.asyncio
    async def test_detects_app_startup_crash(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="", previous_logs="FATAL: STARTUP_FAULT=crash\nRuntimeError: Deliberate crash",
            pod_status_summary="CrashLoopBackOff\nReason: Error\nExit Code: 1",
            k8s_events_filtered="Warning BackOff: restarting failed container",
            restart_count=6,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "crash"

    @pytest.mark.asyncio
    async def test_unknown_for_healthy_pod(self):
        pkg = EvidencePackage(
            namespace="demo", pod_name="p",
            current_logs="", previous_logs="",
            pod_status_summary="Running\nReady: True\nPort: 8000/TCP",
            k8s_events_filtered="",
            restart_count=0,
        )
        provider = MockProvider()
        report = await provider.analyse(pkg)
        assert report.failure_category == "unknown"

    @pytest.mark.asyncio
    async def test_report_contains_required_fields(self, evidence_package):
        provider = MockProvider()
        report = await provider.analyse(evidence_package)
        assert len(report.incident_summary) >= 10
        assert len(report.likely_root_cause) >= 10
        assert len(report.supporting_evidence) >= 1
        assert len(report.recommended_commands) >= 1
        assert len(report.human_verification_steps) >= 1

    @pytest.mark.asyncio
    async def test_supporting_evidence_has_valid_source(self, evidence_package):
        provider = MockProvider()
        report = await provider.analyse(evidence_package)
        for ev in report.supporting_evidence:
            assert ev.source in (
                "pod_log", "previous_pod_log", "kubernetes_event", "pod_status"
            )

    @pytest.mark.asyncio
    async def test_confidence_within_range(self, evidence_package):
        provider = MockProvider()
        report = await provider.analyse(evidence_package)
        assert 0.0 <= report.confidence <= 1.0


class TestGetProvider:
    def test_get_provider_returns_mock_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = get_provider()
            assert isinstance(provider, MockProvider)

    def test_get_provider_returns_mock_when_set(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}, clear=True):
            provider = get_provider()
            assert isinstance(provider, MockProvider)

    def test_get_provider_returns_openai(self):
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test-fake-key-for-testing-only",
        }, clear=True):
            provider = get_provider()
            from app.llm.openai_provider import OpenAIProvider
            assert isinstance(provider, OpenAIProvider)

    def test_get_provider_returns_anthropic(self):
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-test-fake-key-for-testing-only",
        }, clear=True):
            provider = get_provider()
            from app.llm.anthropic_provider import AnthropicProvider
            assert isinstance(provider, AnthropicProvider)

    def test_get_provider_returns_deepseek(self):
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "test-fake-key-for-testing-only",
        }, clear=True):
            provider = get_provider()
            from app.llm.deepseek_provider import DeepSeekProvider
            assert isinstance(provider, DeepSeekProvider)

    def test_get_provider_case_insensitive(self):
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "OPENAI",
            "OPENAI_API_KEY": "sk-test-fake-key-for-testing-only",
        }, clear=True):
            provider = get_provider()
            from app.llm.openai_provider import OpenAIProvider
            assert isinstance(provider, OpenAIProvider)


class TestOpenAIProviderAnalyse:
    @pytest.fixture
    def evidence_package(self):
        return EvidencePackage(
            namespace="demo",
            pod_name="demo-app-abc",
            current_logs="ERROR Missing DATABASE_URL",
            previous_logs="",
            pod_status_summary="CrashLoopBackOff",
            k8s_events_filtered="Warning BackOff",
            restart_count=3,
        )

    @pytest.fixture
    def fake_report(self):
        from k8s_llm_shared import EvidenceItem

        return IncidentReport(
            incident_summary="Test incident",
            likely_root_cause="Missing DATABASE_URL",
            affected_component="demo-app-abc",
            failure_category="config",
            severity="critical",
            confidence=0.9,
            supporting_evidence=[
                EvidenceItem(
                    source="pod_log",
                    pod="demo-app-abc",
                    evidence="FATAL: DATABASE_URL missing",
                )
            ],
            suggested_fix="Set the env var",
            recommended_commands=["kubectl describe pod"],
            human_verification_steps=["Check env vars"],
        )

    @pytest.mark.asyncio
    async def test_analyse_success(self, evidence_package, fake_report):
        with patch("app.llm.openai_provider.AsyncOpenAI") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_message = MagicMock()
            mock_message.parsed = fake_report
            mock_message.refusal = None
            mock_completion = MagicMock()
            mock_completion.choices = [MagicMock(message=mock_message)]
            mock_client.chat.completions.parse = AsyncMock(
                return_value=mock_completion
            )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
                from app.llm.openai_provider import OpenAIProvider
                provider = OpenAIProvider()
                report = await provider.analyse(evidence_package)

            assert isinstance(report, IncidentReport)
            assert report.failure_category == "config"
            mock_client.chat.completions.parse.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyse_content_filter_error(self, evidence_package):
        with patch("app.llm.openai_provider.AsyncOpenAI") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            from openai import ContentFilterFinishReasonError
            mock_client.chat.completions.parse = AsyncMock(
                side_effect=ContentFilterFinishReasonError()
            )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
                from app.llm.openai_provider import OpenAIProvider
                provider = OpenAIProvider()
                with pytest.raises(RuntimeError, match="Content filtered"):
                    await provider.analyse(evidence_package)

    @pytest.mark.asyncio
    async def test_analyse_length_error(self, evidence_package):
        with patch("app.llm.openai_provider.AsyncOpenAI") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            from openai import LengthFinishReasonError
            error = LengthFinishReasonError(
                completion=MagicMock(id="test-completion"),
            )
            mock_client.chat.completions.parse = AsyncMock(
                side_effect=error
            )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
                from app.llm.openai_provider import OpenAIProvider
                provider = OpenAIProvider()
                with pytest.raises(RuntimeError, match="Output truncated"):
                    await provider.analyse(evidence_package)

    @pytest.mark.asyncio
    async def test_analyse_refusal_raises(self, evidence_package):
        with patch("app.llm.openai_provider.AsyncOpenAI") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_message = MagicMock()
            mock_message.parsed = None
            mock_message.refusal = "I cannot analyze this"
            mock_completion = MagicMock()
            mock_completion.choices = [MagicMock(message=mock_message)]
            mock_client.chat.completions.parse = AsyncMock(
                return_value=mock_completion
            )

            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
                from app.llm.openai_provider import OpenAIProvider
                provider = OpenAIProvider()
                with pytest.raises(ValueError, match="No structured output"):
                    await provider.analyse(evidence_package)


class TestAnthropicProviderAnalyse:
    @pytest.fixture
    def evidence_package(self):
        return EvidencePackage(
            namespace="demo",
            pod_name="demo-app-abc",
            current_logs="ERROR connection refused",
            previous_logs="",
            pod_status_summary="Running",
            k8s_events_filtered="Warning Unhealthy",
            restart_count=0,
        )

    @pytest.fixture
    def fake_report(self):
        from k8s_llm_shared import EvidenceItem

        return IncidentReport(
            incident_summary="Test incident",
            likely_root_cause="Connection refused",
            affected_component="demo-app-abc",
            failure_category="dependency",
            severity="high",
            confidence=0.8,
            supporting_evidence=[
                EvidenceItem(
                    source="pod_log",
                    pod="demo-app-abc",
                    evidence="ERROR: connection refused",
                )
            ],
            suggested_fix="Check connectivity",
            recommended_commands=["kubectl describe pod"],
            human_verification_steps=["Verify DB is reachable"],
        )

    @pytest.mark.asyncio
    async def test_analyse_success(self, evidence_package, fake_report):
        with patch("app.llm.anthropic_provider.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = mock_cls.return_value
            mock_content = MagicMock()
            mock_content.parsed_output = fake_report
            mock_content.text = ""
            mock_response = MagicMock()
            mock_response.content = [mock_content]
            mock_client.messages.parse = AsyncMock(return_value=mock_response)

            with patch.dict(
                os.environ,
                {"ANTHROPIC_API_KEY": "sk-ant-test"},
                clear=True,
            ):
                from app.llm.anthropic_provider import AnthropicProvider
                provider = AnthropicProvider()
                report = await provider.analyse(evidence_package)

            assert isinstance(report, IncidentReport)
            assert report.failure_category == "dependency"
            mock_client.messages.parse.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyse_null_parsed_raises(self, evidence_package):
        with patch("app.llm.anthropic_provider.anthropic.AsyncAnthropic") as mock_cls:
            mock_client = mock_cls.return_value
            mock_content = MagicMock()
            mock_content.parsed_output = None
            mock_content.text = "some raw text"
            mock_response = MagicMock()
            mock_response.content = [mock_content]
            mock_client.messages.parse = AsyncMock(return_value=mock_response)

            with patch.dict(
                os.environ,
                {"ANTHROPIC_API_KEY": "sk-ant-test"},
                clear=True,
            ):
                from app.llm.anthropic_provider import AnthropicProvider
                provider = AnthropicProvider()
                with pytest.raises(ValueError, match="no structured output"):
                    await provider.analyse(evidence_package)


class TestDeepSeekProviderAnalyse:
    @pytest.fixture
    def evidence_package(self):
        return EvidencePackage(
            namespace="demo",
            pod_name="demo-app-abc",
            current_logs="ImagePullBackOff error",
            previous_logs="",
            pod_status_summary="ImagePullBackOff",
            k8s_events_filtered="Warning Failed to pull image",
            restart_count=0,
        )

    @pytest.fixture
    def fake_report_dict(self):
        return {
            "incident_summary": "Image pull failure",
            "likely_root_cause": "Cannot pull container image",
            "affected_component": "demo-app-abc",
            "failure_category": "image",
            "severity": "high",
            "confidence": 0.9,
            "supporting_evidence": [
                {"source": "pod_status", "pod": "demo-app-abc", "evidence": "ImagePullBackOff"}
            ],
            "suggested_fix": "Check image name and registry",
            "recommended_commands": ["kubectl describe pod"],
            "human_verification_steps": ["Verify image exists"],
        }

    @pytest.mark.asyncio
    async def test_analyse_success(self, evidence_package, fake_report_dict):
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps(fake_report_dict)}}]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.post = AsyncMock(return_value=fake_response)

            with patch.dict(
                os.environ,
                {"DEEPSEEK_API_KEY": "test-key"},
                clear=True,
            ):
                from app.llm.deepseek_provider import DeepSeekProvider
                provider = DeepSeekProvider()
                report = await provider.analyse(evidence_package)

            assert isinstance(report, IncidentReport)
            assert report.failure_category == "image"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_analyse_invalid_json_raises(self, evidence_package):
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "not valid json {"}}]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.post = AsyncMock(return_value=fake_response)

            with patch.dict(
                os.environ,
                {"DEEPSEEK_API_KEY": "test-key"},
                clear=True,
            ):
                from app.llm.deepseek_provider import DeepSeekProvider
                provider = DeepSeekProvider()
                with pytest.raises(RuntimeError, match="non-JSON"):
                    await provider.analyse(evidence_package)

    @pytest.mark.asyncio
    async def test_analyse_http_error_raises(self, evidence_package):
        fake_response = MagicMock()
        fake_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.post = AsyncMock(return_value=fake_response)

            with patch.dict(
                os.environ,
                {"DEEPSEEK_API_KEY": "test-key"},
                clear=True,
            ):
                from app.llm.deepseek_provider import DeepSeekProvider
                provider = DeepSeekProvider()
                with pytest.raises(httpx.HTTPStatusError):
                    await provider.analyse(evidence_package)
