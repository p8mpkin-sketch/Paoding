#!/usr/bin/env bash
# 端到端冒烟：后台起全栈 → 用假 CLI 配置开一道题 → 等终态 → 输出摘要 → 清理。
#
#   scripts/test-e2e.sh [--port 8100] [--timeout 180] [--keep]
#
# 需要：uv、Docker（守护进程在跑，镜像 python:3.12-slim 在本地）。不需要任何模型密钥。
# 退出码：0 = 终态 solved 且清理干净；1 = 没解出或超时；2 = 环境不满足；3 = 清理后仍有残留。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8100
TIMEOUT=180
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

say() { printf '[test-e2e] %s\n' "$*" >&2; }

command -v uv >/dev/null || { say "需要 uv"; exit 2; }
docker info >/dev/null 2>&1 || { say "Docker 不可用：先起 dockerd"; exit 2; }
docker image inspect python:3.12-slim >/dev/null 2>&1 || { say "缺镜像：docker pull python:3.12-slim"; exit 2; }

HOME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/paoding-e2e.XXXXXX")"
LOG="$HOME_DIR/stack.log"
READY="$HOME_DIR/ready"
STACK_PID=""

# 1. 测试配置：假 CLI 后端，三类任务的脚本取 scripts/e2e/ 下的那三份（绝对路径）
E2E="$ROOT/scripts/e2e"
cat > "$HOME_DIR/config.json" <<JSON
{
  "backend": {"kind": "fake", "scripts": {
    "bootstrap": "$E2E/bootstrap.json", "reason": "$E2E/reason.json", "explore": "$E2E/explore.json"}},
  "executor": {"kind": "docker", "bases": {"basic": "python:3.12-slim"}},
  "poll_s": 0.3,
  "dog_interval_s": 1.0
}
JSON

cleanup() {
  local rc=$?
  if [ -n "$STACK_PID" ] && kill -0 "$STACK_PID" 2>/dev/null; then
    kill -INT "$STACK_PID" 2>/dev/null
    for _ in $(seq 60); do kill -0 "$STACK_PID" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$STACK_PID" 2>/dev/null && { say "30 秒没退，强杀"; kill -KILL "$STACK_PID" 2>/dev/null; }
  fi
  # 本次起的容器：属主标签里带全栈进程的 pid
  if [ -n "$STACK_PID" ]; then
    left="$(docker ps -a --filter label=paoding.owner --format '{{.Names}} {{.Label "paoding.owner"}}' | grep ":$STACK_PID:" | awk '{print $1}')"
    if [ -n "$left" ]; then
      say "残留容器：$left（删掉）"
      echo "$left" | xargs -r docker rm -f -v >/dev/null
      rc=3
    fi
  fi
  if [ "$KEEP" = 1 ]; then say "保留数据目录 $HOME_DIR"; else rm -rf "$HOME_DIR"; fi
  exit $rc
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# 2. 后台起全栈
say "数据目录 $HOME_DIR，端口 $PORT"
( cd "$ROOT" && exec uv run --quiet python scripts/run.py --home "$HOME_DIR" --port "$PORT" --no-static \
    --ready-file "$READY" ) 2>"$LOG" &
LAUNCHER=$!
for _ in $(seq 120); do
  [ -s "$READY" ] && break
  kill -0 "$LAUNCHER" 2>/dev/null || { say "全栈没起来："; cat "$LOG" >&2; exit 2; }
  sleep 0.25
done
[ -s "$READY" ] || { say "全栈 30 秒内没就绪："; cat "$LOG" >&2; exit 2; }
URL="$(cat "$READY")"
STACK_PID="$(pgrep -f -- "scripts/run.py --home $HOME_DIR" | while read -r p; do
  [ "$(readlink "/proc/$p/exe" 2>/dev/null | grep -c python)" = 1 ] && echo "$p"; done | tail -1)"
STACK_PID="${STACK_PID:-$LAUNCHER}"
say "全栈就绪：$URL（进程 $STACK_PID）"

# 3. 开题并等终态（人只做开题这一件事）
T0=$(date +%s.%N)
SUMMARY="$(cd "$ROOT" && uv run --quiet python scripts/e2e/drive.py --url "$URL" --token-file "$HOME_DIR/human.token" \
    --timeout "$TIMEOUT")"
DRIVE_RC=$?
T1=$(date +%s.%N)

# 4. 摘要
if [ -z "$SUMMARY" ]; then
  say "驱动没有输出（rc=$DRIVE_RC）；全栈日志："; cat "$LOG" >&2; exit 1
fi
python3 - "$SUMMARY" "$T0" "$T1" <<'PY'
import json, sys
s = json.loads(sys.argv[1])
if "error" in s:
    print("开题被拒：", json.dumps(s, ensure_ascii=False)); sys.exit(0)
print(f"终态      {s['terminal']}（关题者 {s['closed_by']}）")
print(f"事件数    {s['events']}  " + "  ".join(f"{k}×{v}" for k, v in sorted(s['by_kind'].items())))
print(f"耗时      开题到关题 {s['elapsed_s']} 秒（含开题请求；脚本墙钟 {float(sys.argv[3]) - float(sys.argv[2]):.2f} 秒）")
print(f"预算      花费 {s['spent_usd_milli']} / 上限 {s['cap_usd_milli']} 毫美元，悬着的预留 {s['reserved_usd_milli']}")
for k, v in sorted(s["by_task_kind"].items()):
    print(f"          {k:<10} {v['usd_milli']:>5} 毫美元  {v['tokens']:>7} token")
PY
if [ "$DRIVE_RC" != 0 ]; then
  say "没有解出；全栈日志最后 40 行："; tail -40 "$LOG" >&2; exit 1
fi
exit 0
