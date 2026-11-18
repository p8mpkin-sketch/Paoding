#!/usr/bin/env bash
# 备份一个数据目录（P2-3 第 3 项）：事件日志用 SQLite 的在线备份，Blob 目录打成 tar。
#
#   scripts/backup.sh --home <数据目录> [--out <备份放哪，缺省 <数据目录>/backups>] [--with-vault]
#
# 全栈在跑的时候也可以做，不用停机：
#   1. 先备份 g.sqlite（sqlite3 的 .backup：在线、一致，WAL 里已提交的内容都在内）；
#   2. 再打包 blobs/。Blob 按内容寻址、只增不改，而且总是先写 Blob 再落事件，
#      所以后打包的 Blob 目录一定包含先备份的日志引用到的每一个 Blob（多出来的无害）。
#   次序不能反。
# 产出 <out>/paoding-backup-<UTC 时间>/：g.sqlite、blobs.tar.gz、MANIFEST（链头序号、各文件的 sha256）。
# 不备份的：human.token（重新生成即可）、sessions/（会话的工作目录，留档已在 Blob 里）、logs/。
# vault/（保密库：含密级判官资产）缺省不备份，因为备份的存放处未必配得上它的保密级别；
# 加 --with-vault 才打包成 vault.tar.gz，没有它的备份恢复后含密级判官不能重判。
# 恢复步骤见 docs/ops.md。
set -euo pipefail

HOME_DIR="" OUT="" WITH_VAULT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --home) HOME_DIR="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --with-vault) WITH_VAULT=1; shift ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "backup.sh: 不认识的参数 $1" >&2; exit 2 ;;
  esac
done
[ -n "$HOME_DIR" ] || { echo "backup.sh: 要给 --home <数据目录>" >&2; exit 2; }
DB="$HOME_DIR/g.sqlite"
[ -f "$DB" ] || { echo "backup.sh: $DB 不存在" >&2; exit 2; }
OUT="${OUT:-$HOME_DIR/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT/paoding-backup-$STAMP"
TMP="$DEST.partial"
mkdir -p "$OUT"
[ ! -e "$DEST" ] || { echo "backup.sh: $DEST 已存在" >&2; exit 2; }
rm -rf "$TMP"
mkdir "$TMP"
trap 'rm -rf "$TMP"' EXIT

PY="$(command -v python3 || command -v python || true)"

# 1. 事件日志：在线备份。有 sqlite3 命令行就用它，没有就用 Python 标准库的同一个备份接口。
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".timeout 10000" ".backup '$TMP/g.sqlite'"
  CHECK="$(sqlite3 "$TMP/g.sqlite" 'PRAGMA integrity_check;')"
  HEAD="$(sqlite3 "$TMP/g.sqlite" 'SELECT COALESCE(MAX(seq), 0) FROM events;')"
elif [ -n "$PY" ]; then
  read -r CHECK HEAD < <("$PY" - "$DB" "$TMP/g.sqlite" <<'PYEOF'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=10)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
check = dst.execute("PRAGMA integrity_check").fetchone()[0]
head = dst.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()[0]
dst.close(); src.close()
print(check, head)
PYEOF
  )
else
  echo "backup.sh: 既没有 sqlite3 也没有 python3，做不了在线备份" >&2; exit 2
fi
[ "$CHECK" = "ok" ] || { echo "backup.sh: 备份出来的日志没过 integrity_check：$CHECK" >&2; exit 1; }

# 2. Blob 目录（排除写入中的临时文件）。
if [ -d "$HOME_DIR/blobs" ]; then
  tar -C "$HOME_DIR" --exclude='blobs/tmp/*' -czf "$TMP/blobs.tar.gz" blobs
else
  tar -czf "$TMP/blobs.tar.gz" -T /dev/null
fi
BLOBS="$(tar -tzf "$TMP/blobs.tar.gz" | grep -c '/[0-9a-f]\{62\}$' || true)"

if [ "$WITH_VAULT" = 1 ] && [ -d "$HOME_DIR/vault" ]; then
  ( umask 077; tar -C "$HOME_DIR" -czf "$TMP/vault.tar.gz" vault )
fi

# 3. 清单。
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
{
  echo "created_utc $STAMP"
  echo "head_seq $HEAD"
  echo "blobs $BLOBS"
  for f in g.sqlite blobs.tar.gz vault.tar.gz; do
    [ -f "$TMP/$f" ] && echo "sha256 $f $(sha "$TMP/$f")"
  done
} > "$TMP/MANIFEST"

mv "$TMP" "$DEST"
trap - EXIT
echo "备份完成：$DEST（链头 seq=$HEAD，Blob $BLOBS 个$([ -f "$DEST/vault.tar.gz" ] && echo '，含保密库')）"
