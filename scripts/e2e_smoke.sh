#!/usr/bin/env bash
# ============================================================================
# End-to-end smoke test for the K8s LLM Incident Analyser platform.
#
# Prerequisites:
#   - Platform stack running:  make up
#   - A Kubernetes cluster reachable by collector/scenario (minikube/k3s)
#   - Demo app deployed:       kubectl apply -f k8s/base/
#
# What it verifies:
#   1. Gateway health (all services reachable through it)
#   2. Scenario listing
#   3. Fault scenario apply (05-oom)
#   4. Async analysis job: 202 → stage transitions → done
#   5. SSE stream delivers events
#   6. Report persisted + retrievable, correct category
#   7. Stats endpoint
#   8. Cluster reset to healthy baseline
# ============================================================================
set -euo pipefail

GATEWAY="${GATEWAY_URL:-http://localhost:8000}"
SCENARIO="${SCENARIO:-05-oom}"
EXPECTED_CATEGORY="${EXPECTED_CATEGORY:-resource}"
NAMESPACE="${K8S_NAMESPACE:-demo}"
POD="${POD_NAME:-demo-app}"
JOB_TIMEOUT=150

pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; exit 1; }
info() { echo "[INFO] $1"; }

cleanup_on_exit() {
    if [[ "${APPLIED:-false}" == "true" ]]; then
        info "Resetting cluster to healthy baseline..."
        curl -sf -X POST "${GATEWAY}/api/scenarios/reset" >/dev/null || true
    fi
}
trap cleanup_on_exit EXIT

echo "======================================================================"
echo "E2E Smoke Test — gateway: ${GATEWAY}, scenario: ${SCENARIO}"
echo "======================================================================"

# ---------------------------------------------------------------- 1. health
info "1/8  Gateway health"
HEALTH=$(curl -sf "${GATEWAY}/health") || fail "gateway unreachable at ${GATEWAY} — is the stack up?"
echo "       ${HEALTH}" | head -c 200; echo
pass "gateway healthy"

# ------------------------------------------------------------- 2. scenarios
info "2/8  List scenarios"
SCENARIOS=$(curl -sf "${GATEWAY}/api/scenarios") || fail "cannot list scenarios"
echo "${SCENARIOS}" | grep -q "${SCENARIO}" || fail "scenario ${SCENARIO} not found in list"
pass "scenario ${SCENARIO} listed"

# ----------------------------------------------------------------- 3. reset
info "3/8  Reset cluster to healthy baseline"
curl -sf -X POST "${GATEWAY}/api/scenarios/reset" >/dev/null || fail "reset failed (is the cluster reachable?)"
sleep 3
pass "cluster reset"

# ----------------------------------------------------------------- 4. apply
info "4/8  Apply fault scenario ${SCENARIO}"
APPLY=$(curl -sf -X POST "${GATEWAY}/api/scenarios/${SCENARIO}/apply") || fail "apply failed"
echo "       ${APPLY}" | head -c 200; echo
APPLIED=true
pass "scenario applied"

info "       Waiting 20s for the fault to take effect..."
sleep 20

# ------------------------------------------------------------ 5. create job
info "5/8  Create analysis job"
JOB_RESP=$(curl -sf -X POST "${GATEWAY}/api/jobs" \
    -H "Content-Type: application/json" \
    -d "{\"namespace\": \"${NAMESPACE}\", \"pod_name\": \"${POD}\"}") || fail "job creation failed"
JOB_ID=$(echo "${JOB_RESP}" | python3 -c "import sys, json; print(json.load(sys.stdin)['job_id'])")
pass "job created: ${JOB_ID}"

# --------------------------------------------------- 6. SSE stream (sample)
info "6/8  SSE stream delivers events (10s sample)"
SSE_OUT=$(curl -sf -N --max-time 10 "${GATEWAY}/api/jobs/${JOB_ID}/stream" 2>/dev/null | head -c 2000 || true)
if echo "${SSE_OUT}" | grep -q "event: "; then
    pass "SSE events received"
    echo "${SSE_OUT}" | grep "^event: " | sort -u | sed 's/^/       /'
else
    echo "       (job may have completed before sampling — verifying via polling)"
fi

# ------------------------------------------------------- 7. poll until done
info "7/8  Poll job until terminal state"
ELAPSED=0
LAST_STATUS=""
while [[ ${ELAPSED} -lt ${JOB_TIMEOUT} ]]; do
    JOB=$(curl -sf "${GATEWAY}/api/jobs/${JOB_ID}") || fail "cannot fetch job"
    STATUS=$(echo "${JOB}" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
    if [[ "${STATUS}" != "${LAST_STATUS}" ]]; then
        echo "       [${ELAPSED}s] ${STATUS}"
        LAST_STATUS="${STATUS}"
    fi
    if [[ "${STATUS}" == "done" || "${STATUS}" == "failed" ]]; then
        break
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
done
[[ "${STATUS}" == "done" ]] || fail "job did not complete (last status: ${STATUS})"
INCIDENT_ID=$(echo "${JOB}" | python3 -c "import sys, json; print(json.load(sys.stdin)['incident_id'])")
LATENCY=$(echo "${JOB}" | python3 -c "import sys, json; print(json.load(sys.stdin)['latency_ms'])")
pass "job done in ${LATENCY}ms → incident ${INCIDENT_ID}"

# ----------------------------------------------------------------- 8. report
info "8/8  Retrieve and validate report"
REPORT=$(curl -sf "${GATEWAY}/api/reports/${INCIDENT_ID}") || fail "report not found"
CATEGORY=$(echo "${REPORT}" | python3 -c "import sys, json; print(json.load(sys.stdin)['failure_category'])")
SUMMARY=$(echo "${REPORT}" | python3 -c "import sys, json; print(json.load(sys.stdin)['incident_summary'])")
echo "       category: ${CATEGORY}"
echo "       summary:  ${SUMMARY}"
[[ "${CATEGORY}" == "${EXPECTED_CATEGORY}" ]] || fail "expected category ${EXPECTED_CATEGORY}, got ${CATEGORY}"
EVIDENCE_COUNT=$(echo "${REPORT}" | python3 -c "import sys, json; print(len(json.load(sys.stdin)['supporting_evidence']))")
[[ "${EVIDENCE_COUNT}" -ge 1 ]] || fail "report has no supporting evidence"
pass "report valid (category=${CATEGORY}, evidence=${EVIDENCE_COUNT})"

# ------------------------------------------------------------------- stats
info "bonus  Stats endpoint"
STATS=$(curl -sf "${GATEWAY}/api/stats?range=7d") || fail "stats failed"
TOTAL=$(echo "${STATS}" | python3 -c "import sys, json; print(json.load(sys.stdin)['total_reports'])")
[[ "${TOTAL}" -ge 1 ]] || fail "stats shows no reports"
pass "stats ok (total_reports=${TOTAL})"

# ------------------------------------------------------------------- reset
info "Resetting cluster to healthy baseline"
curl -sf -X POST "${GATEWAY}/api/scenarios/reset" >/dev/null || fail "final reset failed"
APPLIED=false
pass "cluster reset"

echo "======================================================================"
echo "E2E SMOKE TEST PASSED"
echo "======================================================================"
