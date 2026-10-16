#!/usr/bin/env python3
"""Native queue monitor. No browser automation, shell eval, PID signalling or queue deletion.

Use --downloads/--storage-root for synthetic tests. A persistent retry intent makes
requeueing crash-safe; duplicate task lines never define a new batch. A manifest
of checksummed, stable, done outputs is the only input to automatic archiving.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

POLL_SECONDS = 15
STUCK_MINUTES = {"detail": 5, "list": 8}
MAX_TASK_RETRIES = 1
MAX_RETRY = 3
POPUP_TIMEOUT = 30
SCRIPT_DIR = Path(__file__).resolve().parent
BLOCKED = re.compile(r"captcha|验证码|人机验证|安全验证|verification|challenge|edgeone|login\s+(?:required|expired)|not\s+logged\s+in|登录|登陆", re.I)


class SnapshotError(ValueError):
    """Transient/incomplete queue snapshot; never modify queue files to repair it."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum(value):
    return hashlib.sha256(value).hexdigest()


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temporary sibling; os.replace publishes either the old or new document.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class FileLock:
    """OS advisory lock: automatically released on process death, never os.kill(pid, 0).

    Keep the lock file (do not unlink a locked inode). Heartbeats are diagnostic;
    stale timestamps alone cannot evict a live worker during a long archive call.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def release(self):
        if self.stream is not None:
            try:
                self.stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream, fcntl.LOCK_UN)
            finally:
                self.stream.close()
                self.stream = None


def state_directory(platform, queue, downloads, storage):
    key = checksum(canonical([str(Path(downloads).resolve()), str(Path(storage).resolve())]).encode("utf-8"))[:16]
    return Path(tempfile.gettempdir()) / "jobsniper" / "monitors" / f"{platform}_{queue}_{key}"


def read_bytes(path):
    try:
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
    except FileNotFoundError:
        return b""
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Queue file changed during read; waiting for a stable snapshot")
    return data


def rows_from_bytes(data):
    if data and not data.endswith(b"\n"):
        raise ValueError("Incomplete JSONL tail; no repair or append is allowed")
    rows = []
    for line in data.decode("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("JSONL row must be an object")
            rows.append(row)
    return rows


def append_queue_tasks(path, rows, ensure_counts=None):
    """Cooperating MCP/monitor writers append one fsynced payload under an OS lock.

    ensure_counts is a durable retry intent: if a crash happened after append but
    before saving acknowledgement, an existing occurrence satisfies the intent.
    Malformed/incomplete queues are never truncated, repaired or overwritten.
    """
    path = Path(path)
    key = checksum(str(path.resolve()).encode("utf-8"))
    lock = FileLock(Path(tempfile.gettempdir()) / "jobsniper" / "queue_writes" / key / "lock")
    deadline = time.monotonic() + 5
    while not lock.acquire():
        if time.monotonic() >= deadline:
            raise TimeoutError("Queue writer lock is busy")
        time.sleep(0.05)
    try:
        existing = rows_from_bytes(read_bytes(path))
        counts = Counter(canonical(row) for row in existing)
        pending = []
        for row in rows:
            if not isinstance(row.get("url"), str) or not row["url"]:
                raise ValueError("Task requires a URL")
            key = canonical(row)
            if ensure_counts is None or counts[key] < ensure_counts[key]:
                pending.append(row)
                counts[key] += 1
        if pending:
            payload = "".join(canonical(row) + "\n" for row in pending).encode("utf-8")
            # Unbuffered append; all cooperating writers use this lock.
            with path.open("ab", buffering=0) as stream:
                if stream.write(payload) != len(payload):
                    raise OSError("Short queue append; manual inspection required")
                os.fsync(stream.fileno())
        return len(pending)
    finally:
        lock.release()


def identity(row, queue):
    if queue == "list" and (row.get("task_id") or row.get("taskId")):
        return f"task:{row.get('task_id') or row['taskId']}"
    job_id = row.get("job_id")
    url = str(row.get("normalized_url") or row.get("url") or "")
    parsed = urlsplit(url)
    match = re.search(r"/(?:jobdetail/([^/?#]+)\.htm|job_detail/([^/?#]+)\.html)", parsed.path, re.I)
    if not job_id and match:
        job_id = match.group(1) or match.group(2)
    if job_id:
        return f"job:{job_id}"
    if not url:
        return ""
    query = "" if queue == "detail" or match else urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return "url:" + urlunsplit(("https", parsed.netloc.lower(), parsed.path, query, ""))


def parse_assignments(text):
    result = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            tokens = shlex.split(value, posix=True)
            if len(tokens) != 1:
                raise ValueError("Invalid parser assignment")
            result[key] = tokens[0]
    for key in ("total", "done", "failed"):
        result[key] = int(result[key])
    return result


def parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def output_fresh(path, result, metadata=None, *, max_age_seconds=1800, clock_skew_seconds=120):
    recorded = parse_timestamp(result.get("recorded_at"))
    if recorded is None:
        return False
    if metadata is not None:
        collected = parse_timestamp(metadata.get("collected"))
        if collected is None:
            return False
        delta = (recorded - collected).total_seconds()
    else:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        delta = (recorded - modified).total_seconds()
    return -clock_skew_seconds <= delta <= max_age_seconds


def frontmatter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    metadata = {}
    if lines and lines[0].strip() == "---":
        for line in lines[1:40]:
            if line.strip() == "---":
                break
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip().strip("\"'")
    return metadata


def notify_popup(message):
    # -EncodedCommand carries Unicode safely and avoids interpolating untrusted text as code.
    escaped = message.replace("'", "''")
    command = ("$w=New-Object -ComObject WScript.Shell; "
               f"Write-Output ($w.Popup('{escaped}', {POPUP_TIMEOUT}, 'JobSniper', 0x41))")
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=POPUP_TIMEOUT + 5)
        if result.returncode:
            return "unavailable"
        return {"1": "confirmed", "2": "cancelled"}.get(result.stdout.strip(), "timeout")
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


class Monitor:
    def __init__(self, platform, queue, downloads, storage, state_dir=None, *, runner=None, notifier=None, clock=None):
        self.platform, self.queue = platform, queue
        self.downloads, self.storage = Path(downloads).resolve(), Path(storage).resolve()
        self.directory = Path(state_dir) if state_dir is not None else state_directory(platform, queue, downloads, storage)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.tasks_file = self.downloads / f"{platform}_{queue}_tasks.jsonl"
        self.results_file = self.downloads / f"{platform}_{queue}_results.jsonl"
        self.state_file = self.directory / "state.json"
        self.runner = runner or subprocess.run
        self.notifier = notifier or notify_popup
        self.clock = clock or time.time
        if self.state_file.exists():
            self.state = json.loads(self.state_file.read_text(encoding="utf-8"))
            if self.state.get("config") != self.config:
                raise ValueError("Monitor state configuration mismatch")
        else:
            self.state = {"config": self.config, "phase": "idle", "batch_id": "", "retries": {},
                          "handled": [], "archive_jobs": [], "last_progress": self.clock(), "progress": "",
                          "complete_snapshot": "", "notify_snapshot": ""}

    @property
    def config(self):
        return [self.platform, self.queue, str(self.downloads), str(self.storage)]

    def save(self):
        save_json(self.state_file, self.state)

    def log(self, event):
        # Do not dump task URLs, keywords or private Markdown contents into logs.
        with (self.directory / "events.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{self.clock():.3f} {event}\n")

    def run_child(self, arguments):
        env = {**os.environ, "JOBSNIPER_DOWNLOADS_PATH": str(self.downloads),
               "JOBSNIPER_STORAGE_ROOT": str(self.storage), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        result = self.runner([sys.executable, *map(str, arguments)], capture_output=True, text=True,
                             encoding="utf-8", errors="strict", env=env, timeout=120)
        if result.returncode:
            save_json(self.directory / "child_diagnostic.json", {
                "script": Path(arguments[0]).name, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr,
            })
            raise RuntimeError(f"{Path(arguments[0]).name} failed (exit {result.returncode}); see child_diagnostic.json")
        return result.stdout

    def snapshot(self):
        task_bytes, result_bytes = read_bytes(self.tasks_file), read_bytes(self.results_file)
        tasks, results = rows_from_bytes(task_bytes), rows_from_bytes(result_bytes)
        unique = {}
        for row in tasks:
            if not isinstance(row.get("url"), str) or not row["url"]:
                raise ValueError("Task row has no URL")
            ident = identity(row, self.queue)
            if not ident:
                raise ValueError("Task row has no identity")
            unique.setdefault(ident, row)
        latest = {}
        for row in results:
            ident = identity(row, self.queue)
            if ident in unique:
                latest[ident] = row
        # Parse immutable snapshots, not the browser's concurrently replaced results file.
        task_snapshot, result_snapshot = self.directory / "tasks.snapshot.jsonl", self.directory / "results.snapshot.jsonl"
        task_snapshot.write_bytes(task_bytes)
        result_snapshot.write_bytes(result_bytes)
        parser = SCRIPT_DIR / ("parse_detail_results.py" if self.queue == "detail" else "parse_queue_results.py")
        stats = parse_assignments(self.run_child([parser, result_snapshot, task_snapshot]))
        expected = (len(unique), sum(row.get("status") == "done" for row in latest.values()),
                    sum(row.get("status") == "failed" for row in latest.values()))
        if (stats["total"], stats["done"], stats["failed"]) != expected:
            raise ValueError("Parser and monitor identities disagree; no retry/archive allowed")
        return tasks, unique, latest, stats, task_bytes, result_bytes

    def current_snapshot_id(self):
        task_bytes, result_bytes = read_bytes(self.tasks_file), read_bytes(self.results_file)
        return checksum(task_bytes + b"\\0" + result_bytes)

    def _notify(self):
        now = self.clock()
        if now < self.state.get("next_notify", 0):
            return self.state["phase"]
        attempts = self.state.get("notify_attempt", 0)
        complete = attempts >= MAX_RETRY
        if not complete:
            self.state["notify_attempt"] = attempts + 1
            self.save()  # Notification budget also survives restart.
            stats = self.state["stats"]
            outcome = self.notifier(f"Pipeline complete: done={stats['done']} failed={stats['failed']} total={stats['total']}. Queue files retained.")
            self.log(f"notification attempt={attempts + 1} outcome={outcome}")
            complete = outcome == "confirmed" or attempts + 1 >= MAX_RETRY
            if not complete:
                delay = (120 if outcome == "cancelled" else 60) if self.queue == "list" else 300
                self.state["next_notify"] = now + delay
        if complete:
            expected = self.state.get("notify_snapshot", "")
            if self.current_snapshot_id() != expected:
                # A task/result arrived while the popup was open. Keep this worker alive
                # and process the new snapshot instead of declaring a stale completion.
                self.state.update(phase="crawling", notify_attempt=0, next_notify=0, notify_snapshot="")
            else:
                self.state.update(phase="complete", complete_snapshot=expected)
        else:
            self.state["phase"] = "notifying"
        self.save()
        return self.state["phase"]

    def _outputs(self, tasks, latest, done_ids):
        files, covered = {}, set()
        for ident in done_ids:
            row = latest[ident]
            task = tasks[ident]
            if self.queue == "list":

                name = row.get("file_name")
                if not isinstance(name, str) or not name or "/" in name or "\\" in name or Path(name).name != name:
                    raise ValueError("Done list result has no safe output filename")
                candidates = [self.downloads / name]
            else:
                candidates = sorted(self.downloads.glob(f"{self.platform.upper()}_DETAIL_*.md"))
            for path in candidates:
                if path.is_symlink() or not path.is_file() or path.resolve().parent != self.downloads:
                    continue
                if "_RAW_" in path.name or "_MANIFEST_" in path.name:
                    continue
                if self.queue == "list":
                    if path.name.startswith(tuple(f"{self.platform.upper()}_{kind}_" for kind in ("DETAIL", "COMPANY", "RAW", "KEYWORDS"))):
                        raise ValueError("List result cannot claim another queue's output")
                    if path.name.startswith(f"{self.platform.upper()}_TEST_"):
                        covered.add(ident)  # Test outputs remain in Downloads; never auto-archive.
                        continue
                    if not output_fresh(path, row):
                        continue
                if self.queue == "detail":
                    metadata = frontmatter(path)
                    expected_keyword = str(task.get("keyword") or row.get("keyword") or "")
                    if (identity(metadata, "detail") != ident or not expected_keyword
                            or metadata.get("keyword") != expected_keyword
                            or not output_fresh(path, row, metadata)):
                        continue
                if path.suffix.lower() != ".md" or not path.name.startswith(self.platform.upper() + "_"):
                    raise ValueError("Done output has invalid platform/type")
                keyword = str(task.get("keyword") or row.get("keyword") or "job_detail")
                files[str(path)] = {"source": str(path), "sha256": file_digest(path), "keyword": keyword}
                covered.add(ident)
        if covered != set(done_ids):
            return None
        return list(files.values())

    def _archive(self, task_bytes, result_bytes):
        for job in self.state["archive_jobs"]:
            if job.get("done"):
                continue
            # Any new queue/results write invalidates this poll's completion decision.
            if read_bytes(self.tasks_file) != task_bytes or read_bytes(self.results_file) != result_bytes:
                self.log("archive deferred: queue changed")
                return False
            pending = []
            for entry in job["entries"]:
                source, target = Path(entry["source"]), Path(entry["target"])
                if source.exists():
                    if file_digest(source) != entry["sha256"]:
                        raise ValueError("Archive intent source changed; manual inspection required")
                    if target.is_file() and file_digest(target) == entry["sha256"]:
                        continue  # Interrupted copy/identical-output case: never archive it twice.
                    pending.append({"source": str(source), "sha256": entry["sha256"], "target": str(target)})
                elif not target.is_file() or file_digest(target) != entry["sha256"]:
                    raise ValueError("Cannot reconcile interrupted archive; manual inspection required")
            if pending:
                manifest = self.directory / "archive_manifest.json"
                save_json(manifest, pending)
                result = json.loads(self.run_child([SCRIPT_DIR / "archive_outputs.py", job["keyword"],
                                                    "--platform", self.platform, "--files-manifest", manifest]))
                completed = result.get("moved", []) + result.get("copied", []) + result.get("already_archived", [])
                if not result.get("ok") or len(completed) != len(pending):
                    raise ValueError("Archive reported incomplete execution; automatic processing stopped")
                save_json(self.directory / "archive_receipt.json", result)
                for item in completed:
                    if file_digest(item["target"]) != item["sha256"]:
                        raise ValueError("Archive target checksum mismatch")
            job["done"] = True
            self.save()
        return True

    def step(self):
        try:
            tasks, unique, latest, stats, task_bytes, result_bytes = self.snapshot()
        except (ValueError, OSError) as exc:
            raise SnapshotError(str(exc)) from exc
        snapshot_id = checksum(task_bytes + b"\\0" + result_bytes)
        self.state["snapshot_id"] = snapshot_id
        self.state["stats"] = stats
        if not unique:
            self.state["phase"] = "idle"
            self.save()
            return "idle"
        # Security failures always take priority, even with existing archive intents.
        blocked = [row for row in latest.values() if row.get("status") == "failed" and BLOCKED.search(str(row.get("error") or ""))]
        if blocked:
            self.state["phase"] = "paused"
            signature = checksum(canonical(blocked).encode("utf-8"))
            if signature != self.state.get("pause_notice"):
                self.state["pause_notice"] = signature
                self.save()
                outcome = self.notifier("Captcha/login failure: monitor stopped without retry/archive. Complete browser verification and resume Joblens manually. Queue files retained.")
                self.log(f"security pause notification={outcome}")
            self.save()
            return "paused"

        batch_id = checksum(canonical(list(unique.items())).encode("utf-8"))
        now = self.clock()
        if batch_id != self.state["batch_id"]:
            self.state.update(batch_id=batch_id, phase="crawling", progress="", last_progress=now,
                              stable_outputs=None, notify_attempt=0, next_notify=0)
            # retries/handled/archive intents are NOT reset by a batch signature change.
            self.log(f"batch observed total={len(unique)}")
        elif self.state["phase"] == "complete":
            if self.state.get("complete_snapshot") == snapshot_id:
                return "complete"
            self.state.update(phase="crawling", notify_attempt=0, next_notify=0, notify_snapshot="")
            self.log("completion reopened: queue/results snapshot changed")
        elif self.state["phase"] == "notifying":
            if self.state.get("notify_snapshot") == snapshot_id:
                return self._notify()
            self.state.update(phase="crawling", notify_attempt=0, next_notify=0, notify_snapshot="")
            self.log("notification reopened: queue/results snapshot changed")

        # Finish durable append intents before making any further completion decision.
        for ident, retry in self.state["retries"].items():
            if ident in unique and not retry.get("queued"):
                append_queue_tasks(self.tasks_file, [retry["task"]], {canonical(retry["task"]): retry["target_count"]})
                retry["queued"] = True
                self.state["last_progress"] = now
                self.save()
                self.log("retry intent applied")
                return "crawling"

        progress = checksum(canonical(latest).encode("utf-8"))
        if progress != self.state["progress"]:
            self.state.update(progress=progress, last_progress=now)
        stale = now - self.state["last_progress"] >= STUCK_MINUTES[self.queue] * 60
        waiting = set()
        for ident, retry in self.state["retries"].items():
            row = latest.get(ident, {})
            if ident in unique and row.get("status") != "done" and canonical(row) == retry["baseline"]:
                waiting.add(ident)
        terminal = all(latest.get(ident, {}).get("status") in ("done", "failed") for ident in unique) and not waiting
        failed = [ident for ident in unique if latest.get(ident, {}).get("status") == "failed" and ident not in waiting]
        retryable = [ident for ident in failed if self.state["retries"].get(ident, {}).get("count", 0) < MAX_TASK_RETRIES]
        if retryable and (terminal or stale):
            counts = Counter(canonical(row) for row in tasks)
            for ident in retryable:
                task = unique[ident]
                self.state["retries"][ident] = {"count": 1, "queued": False, "task": task,
                                                "target_count": counts[canonical(task)] + 1,
                                                "baseline": canonical(latest[ident])}
            self.state.update(phase="crawling", last_progress=now)
            self.save()  # Intent is durable BEFORE append; restart cannot reset this budget.
            for ident in retryable:
                retry = self.state["retries"][ident]
                append_queue_tasks(self.tasks_file, [retry["task"]], {canonical(retry["task"]): retry["target_count"]})
                retry["queued"] = True
                self.save()
            self.log(f"retry scheduled count={len(retryable)}")
            return "crawling"
        if not terminal:
            self.state["phase"] = "stalled" if stale else "crawling"
            self.save()
            return self.state["phase"]  # Never archive incomplete or unresolved retry tasks.

        done_ids = [ident for ident in unique if latest.get(ident, {}).get("status") == "done" and ident not in self.state["handled"]]
        if not self.state["archive_jobs"] and done_ids:
            outputs = self._outputs(unique, latest, done_ids)
            if outputs is None:
                self.state["phase"] = "stalled" if stale else "waiting_outputs"
                self.save()
                return self.state["phase"]
            if not outputs:
                # Every done identity was explicitly classified as test-mode output;
                # retain those files, but persist the intentional no-archive decision.
                self.state["handled"] = sorted(set(self.state["handled"]) | set(done_ids))
                self.state.update(phase="notifying", notify_attempt=0, next_notify=0, notify_snapshot=snapshot_id)
                self.save()
                return self._notify()
            signature = canonical(sorted(outputs, key=lambda entry: entry["source"]))
            if signature != self.state.get("stable_outputs"):
                self.state.update(stable_outputs=signature, phase="waiting_outputs")
                self.save()
                return "waiting_outputs"  # Require unchanged output checksums across two polls.
            groups = {}
            for entry in outputs:
                groups.setdefault(entry["keyword"], []).append({"source": entry["source"], "sha256": entry["sha256"]})
            jobs = []
            for keyword, entries in groups.items():
                manifest = self.directory / "archive_manifest.json"
                save_json(manifest, entries)
                plan = json.loads(self.run_child([SCRIPT_DIR / "archive_outputs.py", keyword, "--platform", self.platform,
                                                 "--files-manifest", manifest, "--dry-run"]))
                if not plan.get("ok") or len(plan.get("planned", [])) != len(entries):
                    raise ValueError("Archive planning rejected an output; no automatic archive")
                jobs.append({"keyword": keyword, "entries": plan["planned"], "done": False})
            self.state.update(archive_jobs=jobs, archive_done_ids=done_ids, phase="archiving")
            self.save()  # Targets/checksums survive crash after moving but before acknowledgement.
        if self.state["archive_jobs"]:
            if not self._archive(task_bytes, result_bytes):
                return "crawling"
            self.state["handled"] = sorted(set(self.state["handled"]) | set(self.state["archive_done_ids"]))
            self.state["archive_jobs"] = []
            self.state.pop("archive_done_ids", None)
            # Re-snapshot new tasks/results on the next poll; never mark them handled
            # merely because an older durable archive intent was recovered.
            remaining_done = set(done_ids) - set(self.state["handled"])
            if remaining_done:
                self.state.update(phase="crawling", stable_outputs=None)
                self.save()
                return "crawling"
        self.state.update(phase="notifying", notify_attempt=0, next_notify=0, notify_snapshot=snapshot_id)
        self.save()
        return self._notify()


def startup_recovery_decision(platform, queue, downloads, storage):
    """Return (should_start, reason) for one queue during MCP startup.

    This is deliberately fail-closed. It never creates/downloads queue files, repairs
    JSONL, resets retry budgets, or guesses that a missing output was already archived.
    """
    downloads, storage = Path(downloads).resolve(), Path(storage).resolve()
    if not downloads.is_dir():
        return False, "downloads directory unavailable"
    tasks_file = downloads / f"{platform}_{queue}_tasks.jsonl"
    results_file = downloads / f"{platform}_{queue}_results.jsonl"
    if not tasks_file.is_file():
        return False, "queue file absent"
    try:
        task_bytes, result_bytes = read_bytes(tasks_file), read_bytes(results_file)
        tasks, results = rows_from_bytes(task_bytes), rows_from_bytes(result_bytes)
        if not tasks:
            return False, "queue empty"
        unique = {}
        for row in tasks:
            if not isinstance(row.get("url"), str) or not row["url"]:
                return False, "queue task has no URL"
            ident = identity(row, queue)
            if not ident:
                return False, "queue task identity unavailable"
            unique.setdefault(ident, row)
        latest = {}
        for row in results:
            ident = identity(row, queue)
            if ident in unique:
                latest[ident] = row
    except (OSError, ValueError, UnicodeError) as exc:
        return False, f"queue/results are not safely readable ({type(exc).__name__}); manual review required"

    directory = state_directory(platform, queue, downloads, storage)
    state_path = directory / "state.json"
    state = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                return False, "monitor state is not an object; manual review required"
            expected_config = [platform, queue, str(downloads), str(storage)]
            if state.get("config") != expected_config:
                return False, "monitor state configuration mismatch; manual review required"
            retries = state.get("retries", {})
            handled = state.get("handled", [])
            archive_jobs = state.get("archive_jobs", [])
            archive_done_ids = state.get("archive_done_ids", [])
            if (not isinstance(retries, dict) or not isinstance(handled, list)
                    or not all(isinstance(item, str) for item in handled)
                    or not isinstance(archive_jobs, list)
                    or not isinstance(archive_done_ids, list)
                    or not all(isinstance(item, str) for item in archive_done_ids)):
                return False, "monitor state schema is invalid; manual review required"
            for ident, retry in retries.items():
                if (not isinstance(ident, str) or not isinstance(retry, dict)
                        or type(retry.get("count")) is not int or retry["count"] < 0
                        or type(retry.get("queued")) is not bool
                        or type(retry.get("target_count")) is not int or retry["target_count"] < 1
                        or not isinstance(retry.get("task"), dict)
                        or not isinstance(retry["task"].get("url"), str)
                        or not isinstance(retry.get("baseline"), str)):
                    return False, "retry state schema is invalid; manual review required"
            known_phases = {"idle", "crawling", "waiting_outputs", "archiving", "notifying",
                            "complete", "paused", "stalled", "input_error", "error"}
            if state.get("phase") not in known_phases:
                return False, "monitor state phase is invalid; manual review required"
        except (OSError, ValueError, UnicodeError):
            return False, "monitor state is unreadable; manual review required"

    # Security pauses always require a human, including after a state-file loss.
    blocked = [row for row in latest.values()
               if row.get("status") == "failed" and BLOCKED.search(str(row.get("error") or ""))]
    if blocked:
        return False, "captcha/login result requires manual intervention"

    if state is not None and state.get("phase") == "paused":
        return False, "monitor is manually/security paused"

    pending_archive_jobs = []
    if state is not None:
        jobs = state.get("archive_jobs", [])
        for job in jobs:
            if (not isinstance(job, dict) or not isinstance(job.get("done"), bool)
                    or not isinstance(job.get("keyword"), str) or not isinstance(job.get("entries"), list)):
                return False, "archive intent is malformed; manual review required"
        pending_archive_jobs = [job for job in jobs if not job["done"]]
        if pending_archive_jobs:
            positions = storage / "positions"
            for job in pending_archive_jobs:
                if not isinstance(job.get("keyword"), str) or not job["keyword"].strip() or not isinstance(job.get("entries"), list):
                    return False, "archive intent is malformed; manual review required"
                for entry in job["entries"]:
                    if not isinstance(entry, dict):
                        return False, "archive intent is malformed; manual review required"
                    source, target = Path(str(entry.get("source", ""))), Path(str(entry.get("target", "")))
                    if (not source.is_absolute() or source.is_symlink() or source.resolve().parent != downloads
                            or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))
                            or not target.is_absolute() or not target.resolve().is_relative_to(positions.resolve())):
                        return False, "archive intent paths/checksums are invalid; manual review required"
            return True, "verified archive intent pending"

    snapshot_id = checksum(task_bytes + b"\\0" + result_bytes)
    batch_id = checksum(canonical(list(unique.items())).encode("utf-8"))
    statuses = {ident: latest.get(ident, {}).get("status") for ident in unique}

    if state is not None:
        phase = state.get("phase")
        if phase == "paused":
            return False, "monitor is manually/security paused"
        if phase in ("stalled", "input_error", "error") and state.get("batch_id") == batch_id:
            return False, f"monitor state is {phase}; manual review required"
        if phase == "complete":
            handled = set(state.get("handled", []))
            unhandled_done = {ident for ident, status in statuses.items()
                              if status == "done" and ident not in handled}
            if state.get("complete_snapshot") == snapshot_id and not unhandled_done:
                return False, "completed snapshot already handled"
            if not unhandled_done and all(status in ("done", "failed") for status in statuses.values()):
                return False, "new snapshot has no unhandled work"
            return True, "queue/results changed after completion"

    # Without durable state, failed-result history is ambiguous: do not reset the
    # one-retry budget and do not guess whether a failed attempt was already retried.
    if state is None and any(status == "failed" for status in statuses.values()):
        return False, "state missing with failed history; retry budget cannot be proven"

    if state is None and all(status == "done" for status in statuses.values()):
        try:
            probe = Monitor(platform, queue, downloads, storage, directory)
            done_ids = [ident for ident, status in statuses.items() if status == "done"]
            outputs = probe._outputs(unique, latest, done_ids)
        except (OSError, ValueError, KeyError, TypeError):
            return False, "state missing and completed outputs are not verifiable; manual review required"
        if outputs is None:
            return False, "state missing and completed output is absent or unverified; manual review required"
        return True, "state missing but completed outputs are present and verifiable"

    # Valid state with active/incomplete work, or no state with pending tasks.
    return True, "unfinished queue can resume safely"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("zhilian", "boss"), required=True)
    parser.add_argument("--queue", choices=("list", "detail"), required=True)
    parser.add_argument("--downloads", type=Path, default=Path(os.environ.get("JOBSNIPER_DOWNLOADS_PATH") or r"D:\Downloads"))
    parser.add_argument("--storage-root", type=Path, default=Path(os.environ.get("JOBSNIPER_STORAGE_ROOT") or SCRIPT_DIR.parents[1] / "storage_layer"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--startup-token", default="")
    parser.add_argument("--once", action="store_true", help="One poll only; useful with synthetic queues")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()
    if not args.downloads.is_dir():
        parser.error("Downloads directory must already exist")
    monitor = Monitor(args.platform, args.queue, args.downloads, args.storage_root, args.state_dir,
                      notifier=(lambda _: "confirmed") if args.no_notify else None)
    lock = FileLock(monitor.directory / "monitor.lock")
    if not lock.acquire():
        return 4
    try:
        while True:
            save_json(monitor.directory / "heartbeat.json", {"pid": os.getpid(), "time": time.time(), "token": args.startup_token})
            try:
                phase = monitor.step()
            except SnapshotError as exc:
                # JSONL may be midway through Chrome's whole-file overwrite. Never fix it in place.
                monitor.log(f"snapshot/validation error: {type(exc).__name__}; no retry/archive this poll")
                monitor.state["phase"] = "input_error"
                monitor.save()
                if args.once:
                    return 3
                time.sleep(POLL_SECONDS)
                continue
            except Exception as exc:
                monitor.state["phase"] = "error"
                monitor.state["error"] = str(exc)
                monitor.save()
                monitor.log(f"worker stopped: {type(exc).__name__}")
                return 3
            if phase == "stalled":
                outcome = monitor.notifier("Pipeline stalled: unresolved tasks/results or missing outputs. No incomplete outputs were archived. Queue files retained; inspect state.json.")
                monitor.log(f"stalled notification={outcome}")
            # Completed workers remain as idle queue watchers. This closes the race
            # where MCP sees the monitor lock, appends a new task, and the old worker exits.
            if phase in ("paused", "stalled") or args.once:
                return {"paused": 2, "stalled": 3}.get(phase, 0)
            time.sleep(POLL_SECONDS)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
