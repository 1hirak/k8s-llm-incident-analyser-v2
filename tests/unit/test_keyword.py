from k8s_llm_shared import EvidencePackage

from evaluation.baselines.keyword import (
    KEYWORD_WEIGHTS,
    KeywordClassifier,
    keyword_classify,
    keyword_classify_detailed,
)


def make_pkg(**kwargs):
    defaults = dict(
        namespace="demo",
        pod_name="demo-app-abc",
        current_logs="",
        previous_logs="",
        pod_status_summary="",
        k8s_events_filtered="",
        restart_count=0,
    )
    defaults.update(kwargs)
    return EvidencePackage(**defaults)


class TestKeywordWeights:
    def test_all_seven_categories_present(self):
        expected = {"crash", "config", "dependency", "image", "resource", "probe", "network"}
        assert set(KEYWORD_WEIGHTS.keys()) == expected

    def test_unknown_category_not_in_weights(self):
        assert "unknown" not in KEYWORD_WEIGHTS

    def test_each_category_has_tier1_keywords(self):
        for cat, kws in KEYWORD_WEIGHTS.items():
            assert any(w == 3 for w in kws.values()), f"{cat} has no tier-1 keywords"

    def test_weights_are_positive_integers(self):
        for cat, kws in KEYWORD_WEIGHTS.items():
            for kw, w in kws.items():
                assert isinstance(w, int) and w > 0, f"{cat}/{kw} weight={w}"


class TestKeywordClassifyFunction:
    def test_detects_config(self):
        pkg = make_pkg(current_logs="FATAL: Missing required configuration DATABASE_URL")
        assert keyword_classify(pkg) == "config"

    def test_detects_dependency(self):
        pkg = make_pkg(current_logs="ERROR connection refused to database host")
        assert keyword_classify(pkg) == "dependency"

    def test_detects_image(self):
        pkg = make_pkg(current_logs="ImagePullBackOff: pull access denied")
        assert keyword_classify(pkg) == "image"

    def test_detects_resource(self):
        pkg = make_pkg(current_logs="OOMKilled: out of memory limit exceeded")
        assert keyword_classify(pkg) == "resource"

    def test_detects_probe(self):
        pkg = make_pkg(
            k8s_events_filtered="Warning Unhealthy: readiness probe failed"
        )
        assert keyword_classify(pkg) == "probe"

    def test_detects_network(self):
        pkg = make_pkg(current_logs="Error: address already in use port 8080")
        assert keyword_classify(pkg) == "network"

    def test_detects_crash(self):
        pkg = make_pkg(current_logs="Traceback: RuntimeError exception in handler")
        assert keyword_classify(pkg) == "crash"

    def test_detects_crash_executable_not_found(self):
        pkg = make_pkg(
            pod_status_summary="Reason: ContainerCannotRun "
            "Message: executable file not found in $PATH: /bin/nonexistent"
        )
        assert keyword_classify(pkg) == "crash"

    def test_returns_unknown_when_no_match(self):
        pkg = make_pkg(current_logs="INFO: server started on port 8000")
        assert keyword_classify(pkg) == "unknown"

    def test_searches_all_text_fields(self):
        pkg = make_pkg(
            current_logs="nothing useful",
            pod_status_summary="OOMKilled memory limit exceeded",
        )
        assert keyword_classify(pkg) == "resource"

    def test_case_insensitive(self):
        pkg = make_pkg(current_logs="IMAGEPULLBACKOFF encountered")
        assert keyword_classify(pkg) == "image"

    def test_definitive_keyword_outranks_symptom(self):
        """CrashLoopBackOff (crash, weight 1) should not override
        'environment variable' (config, weight 3) when both are present."""
        pkg = make_pkg(
            previous_logs="FATAL: DATABASE_URL environment variable is not set",
            pod_status_summary="Reason: CrashLoopBackOff",
        )
        assert keyword_classify(pkg) == "config"

    def test_probe_symptom_deprioritised_when_dependency_present(self):
        """Readiness probe failure is a symptom of dependency failure.
        When 'connection refused' is also present, dependency should win."""
        pkg = make_pkg(
            current_logs="Database connection failed: connection refused",
            k8s_events_filtered="Warning Unhealthy: Readiness probe failed",
        )
        assert keyword_classify(pkg) == "dependency"

    def test_probe_wins_when_no_root_cause(self):
        """When only probe signals are present (no dependency/config/etc),
        probe should still be detected."""
        pkg = make_pkg(
            k8s_events_filtered="Warning Unhealthy: Readiness probe failed: "
            "HTTP probe failed with statuscode: 404"
        )
        assert keyword_classify(pkg) == "probe"


class TestKeywordClassifyDetailed:
    def test_returns_dict_with_category(self):
        pkg = make_pkg(current_logs="OOMKilled")
        result = keyword_classify_detailed(pkg)
        assert isinstance(result, dict)
        assert result["failure_category"] == "resource"

    def test_returns_confidence(self):
        pkg = make_pkg(current_logs="ImagePullBackOff")
        result = keyword_classify_detailed(pkg)
        assert "confidence" in result
        assert 0 < result["confidence"] <= 0.9

    def test_returns_matched_keywords(self):
        pkg = make_pkg(current_logs="OOMKilled out of memory")
        result = keyword_classify_detailed(pkg)
        assert "matched_keywords" in result
        assert len(result["matched_keywords"]) >= 2
        assert all("keyword" in m and "weight" in m for m in result["matched_keywords"])

    def test_unknown_returns_zero_confidence(self):
        pkg = make_pkg(current_logs="INFO: all good")
        result = keyword_classify_detailed(pkg)
        assert result["failure_category"] == "unknown"
        assert result["confidence"] == 0.0
        assert result["matched_keywords"] == []


class TestKeywordClassifierClass:
    def test_can_be_instantiated(self):
        c = KeywordClassifier()
        assert c is not None

    def test_classify_method_returns_string(self):
        c = KeywordClassifier()
        pkg = make_pkg(current_logs="OOMKilled")
        result = c.classify(pkg)
        assert isinstance(result, str)

    def test_classify_matches_function(self):
        c = KeywordClassifier()
        pkg = make_pkg(current_logs="connection refused")
        assert c.classify(pkg) == keyword_classify(pkg)

    def test_scores_returns_dict(self):
        c = KeywordClassifier()
        pkg = make_pkg(current_logs="OOMKilled connection refused")
        scores = c.scores(pkg)
        assert isinstance(scores, dict)
        assert scores["resource"] >= 3
        assert scores["dependency"] >= 2

    def test_raw_scores_returns_dict(self):
        c = KeywordClassifier()
        pkg = make_pkg(
            current_logs="OOMKilled connection refused",
            k8s_events_filtered="Readiness probe failed",
        )
        raw = c.raw_scores(pkg)
        assert isinstance(raw, dict)
        assert raw["resource"] >= 3
        assert raw["dependency"] >= 2
        assert raw["probe"] >= 2

    def test_highest_score_wins(self):
        c = KeywordClassifier()
        pkg = make_pkg(
            current_logs="OOMKilled memory limit exceeded "
            "connection refused timeout error exception traceback"
        )
        result = c.classify(pkg)
        scores = c.scores(pkg)
        assert result == max(scores, key=lambda k: scores[k])

    def test_classify_detailed_matches_function(self):
        c = KeywordClassifier()
        pkg = make_pkg(current_logs="ImagePullBackOff")
        detail = c.classify_detailed(pkg)
        assert detail["failure_category"] == c.classify(pkg)
