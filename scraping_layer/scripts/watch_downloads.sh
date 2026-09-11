#!/bin/bash
# 采集→归档流水线监控
# 读 results.jsonl 精确计算 done/failed, done==total 时自动归档, 弹窗通知
# 依赖: bash, python3, powershell.exe

WATCH_DIR="${JOBSNIPER_DOWNLOADS_PATH:-/mnt/d/Downloads}"
TASK_FILE="$WATCH_DIR/zhilian_detail_tasks.jsonl"
RESULTS_FILE="$WATCH_DIR/zhilian_detail_results.jsonl"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_SCRIPT="$SCRIPT_DIR/archive_outputs.py"
PARSE_SCRIPT="$SCRIPT_DIR/parse_detail_results.py"
STATE_DIR="/tmp/watch_downloads"
STATUS_FILE="$STATE_DIR/status"
LOG_FILE="$STATE_DIR/log"
LOCK_FILE="$STATE_DIR/lock"
ARCHIVE_JSON="$STATE_DIR/archive_result.json"
ARCHIVE_ERR="$STATE_DIR/archive_result.err"
POLL_SECONDS=15
STUCK_MINUTES=5
RETRY_INTERVAL=300
POPUP_TIMEOUT=30
MAX_RETRY=3
MAX_TASK_RETRIES=1

mkdir -p "$STATE_DIR"

# ---- 防重复 ----
if [ -f "$LOCK_FILE" ]; then
	old_pid=$(cat "$LOCK_FILE" 2>/dev/null)
	if kill -0 "$old_pid" 2>/dev/null; then
		echo "Monitor is already running (pid $old_pid)"
		exit 1
	fi
fi
echo $$ > "$LOCK_FILE"
cleanup() { rm -f "$LOCK_FILE"; }
trap cleanup EXIT

# ---- 工具 ----
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_FILE"; }

notify_popup() {
	local title="$1" msg="$2" attempt="$3"
	local full_msg="${msg}

(第 ${attempt}/${MAX_RETRY} 次，${POPUP_TIMEOUT}秒)
[确定] 确认  [取消] 稍后"
	local result
	result=$(powershell.exe -NoProfile -Command "
		\$ws = New-Object -ComObject Wscript.Shell
		\$rc = \$ws.Popup('$full_msg', $POPUP_TIMEOUT, '$title', 0x41)
		Write-Output \$rc
	" 2>/dev/null | tr -d '\r\n ')
	case "$result" in
		1) echo "confirmed" ;;
		2) echo "cancelled" ;;
		*) echo "timeout" ;;
	esac
}

get_status()  { grep "^$1=" "$STATUS_FILE" 2>/dev/null | cut -d= -f2; }
set_status()  { sed -i "/^$1=/d" "$STATUS_FILE" 2>/dev/null; echo "$1=$2" >> "$STATUS_FILE"; }
task_signature() {
	if [ -f "$TASK_FILE" ]; then
		cksum "$TASK_FILE" | awk '{print $1 ":" $2}'
	else
		echo ""
	fi
}

# 调用独立 Python 脚本解析 results.jsonl
parse_results() {
	python3 "$PARSE_SCRIPT" "$RESULTS_FILE" "$TASK_FILE"
}

# ---- 初始化 ----
: > "$STATUS_FILE"
set_status "phase" "idle"
set_status "total" "0"
set_status "done" "0"
set_status "failed" "0"
set_status "keyword" ""
set_status "last_progress" "0"
set_status "retry_count" "0"
set_status "notify_attempt" "0"
set_status "task_signature" "$(task_signature)"

log "========== PIPELINE MONITOR START =========="

init=$(parse_results)
eval "$init"
log "INIT: total=$total done=$done failed=$failed keyword=$keyword"

# ---- 主循环 ----
while true; do
	now=$(date +%s)
	eval $(parse_results)
	phase=$(get_status "phase")
	current_signature=$(task_signature)
	previous_signature=$(get_status "task_signature")

	if [ "$total" -gt 0 ] && [ "$current_signature" != "$previous_signature" ]; then
		log "NEW BATCH: task signature $previous_signature -> $current_signature, reset state"
		set_status "task_signature" "$current_signature"
		set_status "phase" "crawling"
		set_status "last_progress" "$now"
		set_status "done_prev" "0"
		set_status "completed_prev" "0"
		set_status "retry_count" "0"
		set_status "notify_attempt" "0"
		phase="crawling"
	elif [ "$total" -eq 0 ] && [ -n "$previous_signature" ]; then
		set_status "task_signature" ""
	fi

	set_status "total" "$total"
	set_status "done" "$done"
	set_status "failed" "$failed"
	[ -n "$keyword" ] && set_status "keyword" "$keyword"
	completed=$(( done + failed ))

	if [ "$total" -eq 0 ]; then
		sleep "$POLL_SECONDS"
		continue
	fi

	# ── 验证码拦截（硬停）──
	# 当出现安全验证页时：停止继续采集（不重试、不归档），弹窗通知人工处理。
	if [ "${has_captcha:-0}" -gt 0 ]; then
		log "CAPTCHA: detected (captcha_failed=${captcha_failed:-0}) → stop monitor without retry/archive"
		msg="Captcha detected: captcha_failed=${captcha_failed:-0}

采集已暂停。请在 Chrome 中完成人机验证后，再触发详情队列唤醒/恢复，然后重新启动监视脚本。"
		notify_popup "Jobsniper Captcha Detected" "$msg" "1" >/dev/null
		cleanup; exit 2
	fi

	# ── 采集监控 ──
	if [ "$phase" != "archiving" ] && [ "$phase" != "notifying" ]; then
		prev_completed=$(get_status "completed_prev" 2>/dev/null)
		if ! [[ "$prev_completed" =~ ^[0-9]+$ ]]; then
			prev_completed=0
		fi
		if [ "$completed" -gt "$prev_completed" ]; then
			set_status "last_progress" "$now"
			set_status "done_prev" "$done"
			set_status "completed_prev" "$completed"
			log "PROGRESS: done=$done/$total failed=$failed completed=$completed/$total"
			[ "$phase" = "idle" ] && set_status "phase" "crawling"
		fi

		last_prog=$(get_status "last_progress")
		stuck_sec=$(( now - last_prog ))

		# 卡住→重试失败任务
		if [ "$failed" -gt 0 ] && [ "$phase" = "crawling" ] && [ "$stuck_sec" -ge $(( STUCK_MINUTES * 60 )) ]; then
			retries=$(get_status "retry_count")
			if [ "$retries" -lt "$MAX_TASK_RETRIES" ]; then
				log "RETRY: $failed failed, attempt $(( retries + 1 ))/$MAX_TASK_RETRIES"
				python3 -c "
import json
with open('$RESULTS_FILE') as f:
    results = [json.loads(l) for l in f if l.strip()]
latest = {}
for r in results:
    latest[r['task_index']] = r['status']
failed_idxs = [idx for idx, s in latest.items() if s == 'failed']
with open('$TASK_FILE') as f:
    tasks = [json.loads(l) for l in f if l.strip()]
for idx in failed_idxs:
    if idx < len(tasks):
        with open('$TASK_FILE', 'a') as f:
            f.write(json.dumps(tasks[idx], ensure_ascii=False) + '\n')
print(f'{len(failed_idxs)} tasks re-queued')
" | while read line; do log "RETRY: $line"; done
				set_status "retry_count" $(( retries + 1 ))
				set_status "last_progress" "$now"
			else
				log "GIVEUP: max retries, proceeding"
				set_status "phase" "archiving"
			fi
		fi

		# completed>=total 是唯一完成判定点；按失败数和重试次数决定后续动作。
		if [ "$completed" -ge "$total" ] && [ "$total" -gt 0 ]; then
			retries=$(get_status "retry_count")
			if [ "$failed" -gt 0 ] && [ "$retries" -lt "$MAX_TASK_RETRIES" ]; then
				log "RETRY: $failed failed after completion, attempt $(( retries + 1 ))/$MAX_TASK_RETRIES"
				python3 -c "
import json
with open('$RESULTS_FILE') as f:
    results = [json.loads(l) for l in f if l.strip()]
latest = {}
for r in results:
    latest[r['task_index']] = r['status']
failed_idxs = [idx for idx, s in latest.items() if s == 'failed']
with open('$TASK_FILE') as f:
    tasks = [json.loads(l) for l in f if l.strip()]
for idx in failed_idxs:
    if idx < len(tasks):
        with open('$TASK_FILE', 'a') as f:
            f.write(json.dumps(tasks[idx], ensure_ascii=False) + '\n')
print(f'{len(failed_idxs)} tasks re-queued')
" | while read line; do log "RETRY: $line"; done
				set_status "retry_count" $(( retries + 1 ))
				set_status "last_progress" "$now"
			elif [ "$failed" -gt 0 ] && [ "$done" -gt 0 ]; then
				log "ALL RESULTS: done=$done failed=$failed total=$total, archive done outputs"
				set_status "phase" "archiving"
			elif [ "$failed" -gt 0 ]; then
				log "ALL FAILED: failed=$failed/$total, notify without archive"
				set_status "phase" "notifying"
				set_status "notify_attempt" "0"
				set_status "next_notify" "$now"
			else
				log "ALL DONE: $done/$total, archive"
				set_status "phase" "archiving"
			fi
		fi
	fi

	# ── 归档 ──
	if [ "$phase" = "archiving" ]; then
		kw=$(get_status "keyword")
		log "ARCHIVE: $kw"
		: > "$ARCHIVE_ERR"
		python3 "$ARCHIVE_SCRIPT" "$kw" --platform zhilian --since-minutes 120 > "$ARCHIVE_JSON" 2> "$ARCHIVE_ERR"
		archive_rc=$?
		if [ -s "$ARCHIVE_ERR" ]; then
			while IFS= read -r line; do log "ARCHIVE_ERR: $line"; done < "$ARCHIVE_ERR"
		fi
		if [ "$archive_rc" -ne 0 ]; then
			log "ARCHIVE: command failed rc=$archive_rc"
		fi
		moved=$(python3 -c "import json, sys; print(json.load(open('$ARCHIVE_JSON')).get('moved_count',0))" 2>/tmp/watch_downloads/archive_parse.err || echo 0)
		if [ -s /tmp/watch_downloads/archive_parse.err ]; then
			while IFS= read -r line; do log "ARCHIVE_PARSE_ERR: $line"; done < /tmp/watch_downloads/archive_parse.err
		fi
		log "ARCHIVE: moved=$moved → notifying"
		set_status "phase" "notifying"
		set_status "notify_attempt" "0"
		set_status "next_notify" "$now"
	fi

	# ── 通知 ──
	if [ "$phase" = "notifying" ]; then
		next_notify=$(get_status "next_notify")
		attempt=$(get_status "notify_attempt")
		if [ "$now" -ge "$next_notify" ] && [ "$attempt" -lt "$MAX_RETRY" ]; then
			attempt=$(( attempt + 1 ))
			set_status "notify_attempt" "$attempt"
			msg="Pipeline complete: done=$(get_status "done") failed=$(get_status "failed") total=$(get_status "total")"
			log "POPUP: $attempt/$MAX_RETRY"
			result=$(notify_popup "Jobsniper Pipeline Done" "$msg" "$attempt")
			case "$result" in
				confirmed)
					log "CONFIRMED, cleanup and exit"
					rm -f "$TASK_FILE" "$RESULTS_FILE"
					cleanup; exit 0 ;;
				*)
					set_status "next_notify" $(( now + RETRY_INTERVAL )) ;;
			esac
		elif [ "$attempt" -ge "$MAX_RETRY" ] && [ "$now" -ge "$(get_status "next_notify")" ]; then
			log "MAX RETRIES exhausted, exit"
			cleanup; exit 0
		fi
	fi

	sleep "$POLL_SECONDS"
done
