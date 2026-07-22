from app.redactor import LogRedactor
from k8s_llm_shared import EvidencePackage


class TestLogRedactor:
    def setup_method(self):
        self.redactor = LogRedactor()

    def _make_package(self, **kwargs) -> EvidencePackage:
        defaults = {
            "namespace": "demo",
            "pod_name": "demo-app",
            "current_logs": "",
            "previous_logs": "",
            "pod_status_summary": "",
            "k8s_events_filtered": "",
            "restart_count": 0,
        }
        defaults.update(kwargs)
        return EvidencePackage(**defaults)

    def test_redact_openai_key(self):
        pkg = self._make_package(
            current_logs="Using API key sk-proj-AxBcDeFgHiJkLmNoPqRsT1234567890abcdefgh"
        )
        result = self.redactor.redact(pkg)
        assert "[OPENAI_KEY=REDACTED]" in result.current_logs
        assert "sk-proj-" not in result.current_logs

    def test_redact_anthropic_key(self):
        pkg = self._make_package(
            current_logs="Using anthropic key sk-ant-AxBcDeFgHiJkLmNoPqRsT123456789"
        )
        result = self.redactor.redact(pkg)
        assert "[ANTHROPIC_KEY=REDACTED]" in result.current_logs

    def test_redact_password_keyword(self):
        pkg = self._make_package(current_logs="password=supersecret123")
        result = self.redactor.redact(pkg)
        assert "[PASSWORD=REDACTED]" in result.current_logs
        assert "supersecret123" not in result.current_logs

    def test_redact_api_key_pattern(self):
        pkg = self._make_package(
            current_logs="api_key=abcdef1234567890abcdef1234567890"
        )
        result = self.redactor.redact(pkg)
        assert "[API_KEY=REDACTED]" in result.current_logs

    def test_redact_db_url(self):
        pkg = self._make_package(
            current_logs="postgres://user:pass@localhost:5432/mydb"
        )
        result = self.redactor.redact(pkg)
        assert "[DB_URL=REDACTED]" in result.current_logs

    def test_redact_all_db_url_schemes(self):
        for scheme in ["postgres", "mysql", "mongodb", "redis"]:
            pkg = self._make_package(current_logs=f"{scheme}://user:pass@host:1234/db")
            result = self.redactor.redact(pkg)
            assert "[DB_URL=REDACTED]" in result.current_logs

    def test_redact_auth_header(self):
        pkg = self._make_package(
            current_logs="Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        )
        result = self.redactor.redact(pkg)
        assert "[AUTH_HEADER=REDACTED]" in result.current_logs

    def test_redact_email(self):
        pkg = self._make_package(current_logs="contact: user@example.com for support")
        result = self.redactor.redact(pkg)
        assert "[EMAIL=REDACTED]" in result.current_logs

    def test_redact_all_fields(self):
        pkg = self._make_package(
            current_logs="DB: postgres://u:p@h/db, key=sk-proj-ABCDEF1234567890",
            previous_logs="password=secret123, api_key=abcdef1234567890abcdef1234567890",
            pod_status_summary=(
                "email: admin@k8s.io, token: "
                "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
            ),
            k8s_events_filtered="auth: Bearer xyzabcdef12345678901234",
        )
        result = self.redactor.redact(pkg)
        assert "[DB_URL=REDACTED]" in result.current_logs
        assert "[OPENAI_KEY=REDACTED]" in result.current_logs
        assert "[PASSWORD=REDACTED]" in result.previous_logs
        assert "[API_KEY=REDACTED]" in result.previous_logs
        assert "[EMAIL=REDACTED]" in result.pod_status_summary
        assert "[AUTH_HEADER=REDACTED]" in result.k8s_events_filtered

    def test_no_false_positives(self):
        pkg = self._make_package(
            current_logs="INFO Server started on port 8000\nERROR Connection refused to service"
        )
        result = self.redactor.redact(pkg)
        assert result.current_logs == pkg.current_logs

    def test_redact_empty_strings(self):
        pkg = self._make_package(
            current_logs="", previous_logs="",
            pod_status_summary="", k8s_events_filtered="",
        )
        result = self.redactor.redact(pkg)
        assert result.current_logs == ""

    def test_redact_preserves_non_secret_content(self):
        pkg = self._make_package(
            current_logs="ERROR CrashLoopBackOff: container demo-app restarting"
        )
        result = self.redactor.redact(pkg)
        assert "CrashLoopBackOff" in result.current_logs
        assert "restarting" in result.current_logs

    def test_redact_multiple_secrets_same_line(self):
        pkg = self._make_package(
            current_logs="password=admin123 api_key=abcdef123456 email=test@test.com"
        )
        result = self.redactor.redact(pkg)
        assert "[PASSWORD=REDACTED]" in result.current_logs
        assert "[API_KEY=REDACTED]" in result.current_logs
        assert "[EMAIL=REDACTED]" in result.current_logs

    def test_redact_passwd_variant(self):
        pkg = self._make_package(current_logs="passwd=secret123")
        result = self.redactor.redact(pkg)
        assert "[PASSWORD=REDACTED]" in result.current_logs

    def test_redact_pwd_variant(self):
        pkg = self._make_package(current_logs="pwd=mysecret")
        result = self.redactor.redact(pkg)
        assert "[PASSWORD=REDACTED]" in result.current_logs

    def test_redact_token_variant(self):
        pkg = self._make_package(
            current_logs="token=ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        )
        result = self.redactor.redact(pkg)
        assert "[API_KEY=REDACTED]" in result.current_logs

    def test_redact_secret_variant(self):
        pkg = self._make_package(
            current_logs='secret = "d4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9"'
        )
        result = self.redactor.redact(pkg)
        assert "[API_KEY=REDACTED]" in result.current_logs

    def test_redact_db_url_with_single_quotes(self):
        pkg = self._make_package(
            current_logs="redis://default:password@redis-service:6379/0"
        )
        result = self.redactor.redact(pkg)
        assert "[DB_URL=REDACTED]" in result.current_logs

    def test_redact_db_url_in_pod_status(self):
        pkg = self._make_package(
            pod_status_summary="DATABASE_URL=postgres://user:pass@host:5432/db"
        )
        result = self.redactor.redact(pkg)
        assert "[DB_URL=REDACTED]" in result.pod_status_summary

    def test_redact_multiple_openai_keys(self):
        pkg = self._make_package(
            current_logs="old: sk-proj-AAAAABBBBBCCCCCDDDDDEEEEEFFFFFGGGGGHHHH "
                         "new: sk-proj-IIIIIJJJJJKKKKKLLLLLMMMMMNNNNNOOOOOPPPPP"
        )
        result = self.redactor.redact(pkg)
        assert result.current_logs.count("[OPENAI_KEY=REDACTED]") == 2

    def test_redact_email_with_subdomain(self):
        pkg = self._make_package(
            current_logs="devops@k8s-production.example.co.uk"
        )
        result = self.redactor.redact(pkg)
        assert "[EMAIL=REDACTED]" in result.current_logs

    def test_short_api_key_not_redacted(self):
        pkg = self._make_package(current_logs="api_key=short")
        result = self.redactor.redact(pkg)
        assert "api_key=short" in result.current_logs

    def test_bearer_in_url_not_redacted_false_positive(self):
        pkg = self._make_package(
            current_logs="GET /api/data HTTP/1.1 200 OK"
        )
        result = self.redactor.redact(pkg)
        assert result.current_logs == pkg.current_logs

    def test_redact_preserves_newlines(self):
        pkg = self._make_package(
            current_logs="line1\npassword=s3cret\nline3"
        )
        result = self.redactor.redact(pkg)
        assert result.current_logs == "line1\n[PASSWORD=REDACTED]\nline3"

    def test_model_copy_preserves_other_fields(self):
        pkg = self._make_package(
            namespace="demo",
            pod_name="my-pod",
            current_logs="password=test",
            restart_count=5,
        )
        result = self.redactor.redact(pkg)
        assert result.namespace == "demo"
        assert result.pod_name == "my-pod"
        assert result.restart_count == 5
