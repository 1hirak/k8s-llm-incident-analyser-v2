#!/usr/bin/env bash
#
# run_all_tests.sh — Run every test suite in the project.
#
# Covers:
#   1. All 8 backend Python microservice test suites
#   2. Root integration + unit test suite
#   3. Frontend (Next.js) test suite (vitest)
#
# Usage:
#   ./scripts/run_all_tests.sh
#   make test          # delegates to this script

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAILED_SUITES=()

# ── helpers ────────────────────────────────────────────────────────────────

RED="\033[0;31m" GREEN="\033[0;32m" YELLOW="\033[1;33m" CYAN="\033[0;36m" BOLD="\033[1m" NC="\033[0m"

banner()   { echo -e "\n${BOLD}${CYAN}━━━ $1 ━━━${NC}"; }
fail_suite(){ FAILED_SUITES+=("$1"); }

extract_passed() {
  grep -o '[0-9]\+ passed' "$1" 2>/dev/null | tail -1 | grep -o '[0-9]\+' || echo "0"
}

# ── Python service suites ──────────────────────────────────────────────────

SERVICES=(shared collector processor llm reports orchestrator gateway scenario)

for svc in "${SERVICES[@]}"; do
  banner "services/$svc"
  tmpfile=$(mktemp)
  if (cd "$ROOT/services/$svc" && "$ROOT/.venv/bin/python" -m pytest -q) > "$tmpfile" 2>&1; then
    count=$(extract_passed "$tmpfile")
    echo -e "  ${GREEN}✓${NC} services/$svc — ${count} passed"
    PASS=$((PASS + count))
  else
    count=$(extract_passed "$tmpfile")
    echo -e "  ${RED}✗${NC} services/$svc — ${count} passed (some failed)"
    fail_suite "services/$svc"
    PASS=$((PASS + count))
  fi
  rm -f "$tmpfile"
done

# ── Root test suite ────────────────────────────────────────────────────────

banner "root tests (integration + unit)"
tmpfile=$(mktemp)
if (cd "$ROOT" && "$ROOT/.venv/bin/python" -m pytest tests -q) > "$tmpfile" 2>&1; then
  count=$(extract_passed "$tmpfile")
  echo -e "  ${GREEN}✓${NC} root tests — ${count} passed"
  PASS=$((PASS + count))
else
  count=$(extract_passed "$tmpfile")
  echo -e "  ${RED}✗${NC} root tests — ${count} passed (some failed)"
  fail_suite "root"
  PASS=$((PASS + count))
fi
rm -f "$tmpfile"

# ── Frontend tests ─────────────────────────────────────────────────────────

banner "frontend (vitest)"
if ! command -v npm &> /dev/null; then
  echo -e "  ${YELLOW}⚠${NC}  npm not found — skipping frontend tests"
else
  tmpfile=$(mktemp)
  if (cd "$ROOT/frontend" && npm test) > "$tmpfile" 2>&1; then
    fe_count=$(extract_passed "$tmpfile")
    echo -e "  ${GREEN}✓${NC} frontend — ${fe_count} passed"
    PASS=$((PASS + fe_count))
  else
    fe_count=$(extract_passed "$tmpfile")
    echo -e "  ${RED}✗${NC} frontend — ${fe_count} passed (some failed)"
    fail_suite "frontend"
    PASS=$((PASS + fe_count))
  fi
  rm -f "$tmpfile"
fi

# ── Summary ────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Total: ${GREEN}${PASS} passed${NC}  |  Failed suites: ${RED}${#FAILED_SUITES[@]}${NC}"
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${NC}"

if [ ${#FAILED_SUITES[@]} -gt 0 ]; then
  echo ""
  echo -e "${RED}Failed suites:${NC}"
  for s in "${FAILED_SUITES[@]}"; do
    echo -e "  ${RED}✗${NC} $s"
  done
fi
echo ""

exit ${#FAILED_SUITES[@]}
