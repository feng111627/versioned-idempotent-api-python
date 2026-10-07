#!/usr/bin/env bash
# 运行全部场景测试，并把带场景/用例/结果的完整日志保存到 test-results.log
set -euo pipefail
cd "$(dirname "$0")/.."

uv run pytest "$@" 2>&1 | tee test-results.log
echo
echo "完整场景日志已保存到 test-results.log"
