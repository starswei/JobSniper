#!/usr/bin/env python3
"""Synthetic P3 regression checks; stdlib unittest only, no browser/network/popups.

Run with the project's interpreter. Every queue, vault, manifest and state file is
under a TemporaryDirectory; subprocesses only execute local Python scripts.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scraping_layer.scripts import jobsniper_monitor as worker

KW = "合成岗位"


class Fixture:
    def __init__(self, root, platform="zhilian", queue="detail"):
        self.root, self.platform, self.queue = Path(root), platform, queue
        self.downloads, self.storage, self.state = self.root / "downloads", self.root / "storage", self.root / "state"
        self.downloads.mkdir(parents=True)
        positions = self.storage / "positions"
        positions.mkdir(parents=True)
        for p in ("zhilian", "boss"):
            (positions / f"{p}_master_tasks.json").write_text(json.dumps([
                {"keyword": KW, "industry": f"{p}行业", "domain": f"{p}领域", "url": ""}
            ]), encoding="utf-8")
        self.tasks_path = self.downloads / f"{platform}_{queue}_tasks.jsonl"
        self.results_path = self.downloads / f"{platform}_{queue}_results.jsonl"
        self.calls, self.notices = [], []
        self.now = 1000

    def task(self, index):
        detail = f"/jobdetail/id{index}.htm" if self.platform == "zhilian" else f"/job_detail/id{index}.html"
        row = {"url": f"https://synthetic.invalid{detail if self.queue == 'detail' else '/list?k=' + str(index)}", "keyword": KW}
        if self.queue == "list":
            row["task_id"] = f"task{index}"
        return row

    def result(self, index, status="done", error=None, attempt=0):
        row = {**self.task(index), "task_index": index - 1 + attempt, "status": status,
               "recorded_at": datetime.now(timezone.utc).isoformat()}
        if self.queue == "list":
            row["file_name"] = self.output_name(index)
        if error:
            row["error"] = error
        return row

    def output_name(self, index):
        prefix = self.platform.upper()
        return (f"{prefix}_DETAIL_合成公司{index}_{KW}_20260101_12000{index}.md" if self.queue == "detail"
                else f"{prefix}_{KW}_20260101_12000{index}.md")

    def output(self, index):
        path = self.downloads / self.output_name(index)
        collected = datetime.now(timezone.utc).isoformat()
        path.write_text(f"---\nkeyword: {KW}\nurl: {self.task(index)['url']}\ncollected: {collected}\n---\nbody {index}\n", encoding="utf-8")
        return path

    def write(self, path, rows):
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def runner(self, command, **kwargs):
        self.calls.append(list(map(str, command)))
        return subprocess.run(command, **kwargs)

    def monitor(self):
        return worker.Monitor(self.platform, self.queue, self.downloads, self.storage, self.state,
                              runner=self.runner, notifier=lambda text: self.notices.append(text) or "confirmed",
                              clock=lambda: self.now)

    def archive_calls(self):
        return [call for call in self.calls if Path(call[1]).name == "archive_outputs.py" and "--dry-run" not in call]


class MonitorChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="jobsniper_p3_checks_")
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        # Include runtime/write-lock artifacts in this test's cleanup boundary too.
        runtime_patch = patch.object(tempfile, "tempdir", str(self.root))
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)

    def cases(self, label):
        for platform in ("zhilian", "boss"):
            for queue in ("detail", "list"):
                yield Fixture(self.root / f"{label}_{platform}_{queue}", platform, queue)

    def test_all_done_only_done_outputs_and_restart(self):
        for f in self.cases("done"):
            with self.subTest(platform=f.platform, queue=f.queue):
                f.write(f.tasks_path, [f.task(1)])
                f.write(f.results_path, [f.result(1)])
                output = f.output(1)
                unrelated = f.downloads / f"{f.platform.upper()}_DETAIL_未完成_其他岗位_20260101_120000.md"
                unrelated.write_text("unrelated", encoding="utf-8")
                m = f.monitor()
                self.assertEqual(m.step(), "waiting_outputs")
                self.assertFalse(f.archive_calls())
                self.assertEqual(m.step(), "complete")
                self.assertEqual(len(f.archive_calls()), 1)
                self.assertFalse(output.exists())
                self.assertTrue(unrelated.exists())
                self.assertTrue(f.tasks_path.exists() and f.results_path.exists())
                target_dir = f.storage / "positions" / f"{f.platform}_intelligence_vault" / f"{f.platform}行业" / f"{f.platform}领域" / KW
                self.assertTrue(target_dir.is_dir())  # BOSS must not use Zhilian's taxonomy.
                self.assertEqual(f.monitor().step(), "complete")
                self.assertEqual(len(f.archive_calls()), 1)

    def test_partial_failure_retry_budget_survives_restart(self):
        for f in self.cases("partial"):
            with self.subTest(platform=f.platform, queue=f.queue):
                f.write(f.tasks_path, [f.task(1), f.task(2)])
                f.write(f.results_path, [f.result(1), f.result(2, "failed", "synthetic timeout")])
                f.output(1)
                m = f.monitor()
                self.assertEqual(m.step(), "crawling")
                after_retry = f.tasks_path.read_bytes()
                self.assertEqual(len(worker.rows_from_bytes(after_retry)), 3)
                for _ in range(3):
                    self.assertEqual(f.monitor().step(), "crawling")
                    self.assertEqual(f.tasks_path.read_bytes(), after_retry)
                self.assertFalse(f.archive_calls())
                f.write(f.results_path, [f.result(1), f.result(2, "failed", "synthetic timeout"),
                                        f.result(2, "failed", "synthetic timeout", attempt=2)])
                m = f.monitor()
                self.assertEqual(m.step(), "waiting_outputs")
                self.assertEqual(m.step(), "complete")
                self.assertEqual(len(f.archive_calls()), 1)
                self.assertEqual(f.tasks_path.read_bytes(), after_retry)
                self.assertTrue(all(retry["count"] == 1 for retry in m.state["retries"].values()))
                self.assertEqual(f.monitor().step(), "complete")

    def test_retry_success_archives_multiple_outputs_without_target_collision(self):
        for f in self.cases("retry_success"):
            with self.subTest(platform=f.platform, queue=f.queue):
                f.write(f.tasks_path, [f.task(1), f.task(2)])
                f.write(f.results_path, [f.result(1), f.result(2, "failed", "synthetic timeout")])
                f.output(1)
                m = f.monitor()
                self.assertEqual(m.step(), "crawling")
                f.write(f.results_path, [f.result(1), f.result(2, "failed", "synthetic timeout"), f.result(2, attempt=2)])
                f.output(2)
                self.assertEqual(m.step(), "waiting_outputs")
                self.assertEqual(m.step(), "complete")
                receipt = json.loads((f.state / "archive_receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(receipt["moved_count"], 2)
                self.assertEqual(len({entry["target"] for entry in receipt["moved"]}), 2)
                self.assertEqual(f.monitor().step(), "complete")
                self.assertEqual(len(f.archive_calls()), 1)

    def test_all_failed_stops_after_one_retry_without_archive(self):
        f = Fixture(self.root / "all_failed")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1, "failed", "synthetic timeout")])
        m = f.monitor()
        self.assertEqual(m.step(), "crawling")
        f.write(f.results_path, [f.result(1, "failed", "synthetic timeout"), f.result(1, "failed", "synthetic timeout", attempt=1)])
        self.assertEqual(m.step(), "complete")
        self.assertFalse(f.archive_calls())
        self.assertEqual(len(worker.rows_from_bytes(f.tasks_path.read_bytes())), 2)

    def test_notification_budget_survives_restart_without_rearchive(self):
        f = Fixture(self.root / "notifications")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1)])
        f.output(1)
        notices = []
        def monitor():
            result = f.monitor()
            result.notifier = lambda message: notices.append(message) or "timeout"
            return result
        m = monitor()
        self.assertEqual(m.step(), "waiting_outputs")
        self.assertEqual(m.step(), "notifying")
        self.assertEqual(monitor().step(), "notifying")
        f.now += 300
        self.assertEqual(monitor().step(), "notifying")
        f.now += 300
        self.assertEqual(monitor().step(), "complete")
        self.assertEqual(len(notices), 3)
        self.assertEqual(len(f.archive_calls()), 1)
        self.assertTrue(f.tasks_path.exists() and f.results_path.exists())

    def test_security_failures_never_retry_or_archive(self):
        for message in ("captcha detected", "login required"):
            for f in self.cases(message.split()[0]):
                with self.subTest(error=message, platform=f.platform, queue=f.queue):
                    f.write(f.tasks_path, [f.task(1), f.task(2)])
                    f.write(f.results_path, [f.result(1), f.result(2, "failed", message)])
                    f.output(1)
                    before = f.tasks_path.read_bytes(), f.results_path.read_bytes()
                    m = f.monitor()
                    self.assertEqual(m.step(), "paused")
                    self.assertFalse(m.state["retries"])
                    self.assertFalse(f.archive_calls())
                    self.assertEqual(f.monitor().step(), "paused")
                    self.assertEqual(len(f.notices), 1)
                    self.assertEqual((f.tasks_path.read_bytes(), f.results_path.read_bytes()), before)

    def test_incomplete_and_stuck_queues_are_not_archived(self):
        f = Fixture(self.root / "stuck")
        f.write(f.tasks_path, [f.task(1), f.task(2)])
        f.write(f.results_path, [f.result(1)])
        f.output(1)
        m = f.monitor()
        self.assertEqual(m.step(), "crawling")
        f.now += 301
        self.assertEqual(m.step(), "stalled")
        self.assertFalse(f.archive_calls())
        original = f.tasks_path.read_bytes() + b'{"url":'
        f.tasks_path.write_bytes(original)
        with self.assertRaises(worker.SnapshotError):
            f.monitor().step()
        with self.assertRaises(ValueError):
            worker.append_queue_tasks(f.tasks_path, [f.task(3)])
        self.assertEqual(f.tasks_path.read_bytes(), original)

    def test_missing_download_waits_for_stability(self):
        f = Fixture(self.root / "download")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1)])
        m = f.monitor()
        self.assertEqual(m.step(), "waiting_outputs")
        self.assertFalse(f.archive_calls())
        f.output(1)
        self.assertEqual(m.step(), "waiting_outputs")
        self.assertEqual(m.step(), "complete")

    def test_detail_archive_rejects_stale_or_wrong_keyword_artifacts(self):
        f = Fixture(self.root / "stale_detail")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1)])
        source = f.output(1)
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        source.write_text(f"---\nkeyword: historical-other-keyword\nurl: {f.task(1)['url']}\ncollected: {old}\n---\nold output\n", encoding="utf-8")
        m = f.monitor()
        self.assertEqual(m.step(), "waiting_outputs")
        f.now += worker.STUCK_MINUTES["detail"] * 60 + 1
        self.assertEqual(f.monitor().step(), "stalled")
        self.assertTrue(source.exists())
        self.assertFalse(f.archive_calls())

    def test_late_success_reopens_complete_and_archives_output(self):
        f = Fixture(self.root / "late_success")
        f.write(f.tasks_path, [f.task(1)])
        first = f.result(1, "failed", "synthetic timeout")
        retry_failed = f.result(1, "failed", "synthetic timeout", attempt=1)
        f.write(f.results_path, [first])
        m = f.monitor()
        self.assertEqual(m.step(), "crawling")
        f.write(f.results_path, [first, retry_failed])
        self.assertEqual(f.monitor().step(), "complete")
        f.write(f.results_path, [first, retry_failed, f.result(1, "done", attempt=2)])
        f.output(1)
        reopened = f.monitor()
        self.assertEqual(reopened.step(), "waiting_outputs")
        self.assertEqual(f.monitor().step(), "complete")
        self.assertEqual(len(f.archive_calls()), 1)
        self.assertEqual(f.monitor().state["stats"]["done"], 1)

    def test_new_done_task_is_not_handled_by_recovered_old_archive_plan(self):
        f = Fixture(self.root / "new_task_recovery")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1)])
        f.output(1)
        m = f.monitor()
        self.assertEqual(m.step(), "waiting_outputs")
        with patch.object(m, "_archive", side_effect=RuntimeError("synthetic crash before archive")):
            with self.assertRaises(RuntimeError):
                m.step()
        f.write(f.tasks_path, [f.task(1), f.task(2)])
        f.write(f.results_path, [f.result(1), f.result(2)])
        second_output = f.output(2)
        recovered = f.monitor()
        self.assertEqual(recovered.step(), "crawling")
        second_id = worker.identity(f.task(2), f.queue)
        self.assertNotIn(second_id, recovered.state["handled"])
        self.assertTrue(second_output.exists())
        self.assertEqual(f.monitor().step(), "waiting_outputs")
        self.assertEqual(f.monitor().step(), "complete")
        self.assertFalse(second_output.exists())
        self.assertEqual(len(f.archive_calls()), 2)

    def test_enqueue_during_final_notification_reopens_worker(self):
        f = Fixture(self.root / "enqueue_during_notify")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1)])
        f.output(1)
        m = f.monitor()
        self.assertEqual(m.step(), "waiting_outputs")
        def enqueue_during_popup(_message):
            worker.append_queue_tasks(f.tasks_path, [f.task(2)])
            return "confirmed"
        m.notifier = enqueue_during_popup
        self.assertEqual(m.step(), "crawling")
        self.assertEqual(len(worker.rows_from_bytes(f.tasks_path.read_bytes())), 2)
        self.assertEqual(f.monitor().step(), "crawling")
        self.assertEqual(f.monitor().state["phase"], "crawling")

    def test_partial_index_recovery_preserves_persisted_target(self):
        f = Fixture(self.root / "partial_index", "zhilian", "list")
        f.write(f.tasks_path, [f.task(1), f.task(2)])
        f.write(f.results_path, [f.result(1), f.result(2)])
        first_source, second_source = f.output(1), f.output(2)
        m = f.monitor()
        self.assertEqual(m.step(), "waiting_outputs")
        with patch.object(m, "_archive", side_effect=RuntimeError("synthetic crash before archive")):
            with self.assertRaises(RuntimeError):
                m.step()
        saved = json.loads((f.state / "state.json").read_text(encoding="utf-8"))
        entries = saved["archive_jobs"][0]["entries"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(len({entry["target"] for entry in entries}), 2)
        first_entry = next(entry for entry in entries if entry["source"] == str(first_source))
        second_entry = next(entry for entry in entries if entry["source"] == str(second_source))
        Path(first_entry["target"]).parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(first_entry["source"], first_entry["target"])
        self.assertEqual(f.monitor().step(), "complete")
        receipt = json.loads((f.state / "archive_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["moved"][0]["target"], second_entry["target"])
        self.assertTrue(Path(first_entry["target"]).exists() and Path(second_entry["target"]).exists())
        self.assertEqual(worker.file_digest(first_entry["target"]), first_entry["sha256"])
        self.assertEqual(worker.file_digest(second_entry["target"]), second_entry["sha256"])

    def test_retry_crash_does_not_append_twice(self):
        f = Fixture(self.root / "retry_crash")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1, "failed", "synthetic timeout")])
        original = worker.append_queue_tasks
        def append_then_crash(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError("synthetic crash after append")
        with patch.object(worker, "append_queue_tasks", append_then_crash):
            with self.assertRaises(OSError):
                f.monitor().step()
        before = f.tasks_path.read_bytes()
        self.assertEqual(len(worker.rows_from_bytes(before)), 2)
        self.assertEqual(f.monitor().step(), "crawling")
        self.assertEqual(f.tasks_path.read_bytes(), before)

    def test_archive_crash_reconciles_without_duplicate_archive(self):
        f = Fixture(self.root / "archive_crash")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1)])
        f.output(1)
        m = f.monitor()
        self.assertEqual(m.step(), "waiting_outputs")
        def archive_then_crash(command, **kwargs):
            result = f.runner(command, **kwargs)
            if Path(command[1]).name == "archive_outputs.py" and "--dry-run" not in command:
                raise RuntimeError("synthetic parent crash after archive")
            return result
        m.runner = archive_then_crash
        with self.assertRaises(RuntimeError):
            m.step()
        self.assertEqual(len(f.archive_calls()), 1)
        self.assertEqual(f.monitor().step(), "complete")
        self.assertEqual(len(f.archive_calls()), 1)

    def test_changed_output_after_plan_is_rejected(self):
        f = Fixture(self.root / "changed")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1)])
        source = f.output(1)
        m = f.monitor()
        m.step()
        def modify_after_plan(command, **kwargs):
            result = f.runner(command, **kwargs)
            if Path(command[1]).name == "archive_outputs.py" and "--dry-run" in command:
                source.write_text("changed during planning", encoding="utf-8")
            return result
        m.runner = modify_after_plan
        with self.assertRaises(ValueError):
            m.step()
        self.assertTrue(source.exists())
        self.assertFalse(f.archive_calls())

    def test_lock_exclusion_and_release_after_process_exit(self):
        path = self.root / "process.lock"
        first, second = worker.FileLock(path), worker.FileLock(path)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()
        code = ("import sys,time; from pathlib import Path; "
                "from scraping_layer.scripts.jobsniper_monitor import FileLock; "
                "lock=FileLock(Path(sys.argv[1])); assert lock.acquire(); "
                "print('locked',flush=True); time.sleep(0.5)")
        child = subprocess.Popen([sys.executable, "-c", code, str(path)], cwd=ROOT,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(child.stdout.readline().strip(), "locked")
        self.assertFalse(first.acquire())
        child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0)
        self.assertTrue(first.acquire())
        first.release()

    def test_cli_security_exit_and_malformed_queue_are_non_destructive(self):
        for label, malformed in (("cli_pause", False), ("cli_bad", True)):
            f = Fixture(self.root / label, "boss", "detail")
            f.write(f.tasks_path, [f.task(1)])
            f.write(f.results_path, [f.result(1, "failed", "login required")])
            if malformed:
                f.tasks_path.write_bytes(f.tasks_path.read_bytes() + b'{"url":')
            original = f.tasks_path.read_bytes(), f.results_path.read_bytes()
            result = subprocess.run([
                sys.executable, "-X", "utf8", str(worker.SCRIPT_DIR / "jobsniper_monitor.py"),
                "--platform", f.platform, "--queue", f.queue, "--downloads", str(f.downloads),
                "--storage-root", str(f.storage), "--state-dir", str(f.state), "--once", "--no-notify",
            ], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 3 if malformed else 2, result.stderr)
            self.assertEqual((f.tasks_path.read_bytes(), f.results_path.read_bytes()), original)
            state = json.loads((f.state / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["phase"], "input_error" if malformed else "paused")
            self.assertFalse(state["retries"])

    def test_concurrent_queue_writers_preserve_every_row(self):
        from concurrent.futures import ThreadPoolExecutor
        f = Fixture(self.root / "concurrent")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda index: worker.append_queue_tasks(f.tasks_path, [f.task(index)]), range(1, 9)))
        rows = worker.rows_from_bytes(f.tasks_path.read_bytes())
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row["url"] for row in rows}), 8)

    def test_shell_quoted_parser_output_is_data_not_code(self):
        result = worker.parse_assignments("total=1\ndone=1\nfailed=0\nkeyword='合成'\\''技能'\n")
        self.assertEqual(result["keyword"], "合成'技能")

    def test_mcp_routes_all_queues_after_successful_append(self):
        import mcp_server as m
        for f in self.cases("mcp_routes"):
            with self.subTest(platform=f.platform, queue=f.queue):
                def started(platform, queue):
                    self.assertEqual((platform, queue), (f.platform, f.queue))
                    self.assertTrue(f.tasks_path.exists())  # Spawn only after durable enqueue.
                    return {"started": True, "running": True}
                with patch.object(m, "DOWNLOADS_PATH", str(f.downloads)), patch.object(m, "STORAGE_PATH", f.storage), patch.object(m, "_start_native_monitor", side_effect=started) as start, patch.object(m.subprocess, "Popen") as browser:
                    if f.queue == "list":
                        result = json.loads(m.launch_job_list_collection(f.platform, KW))
                    else:
                        domain = "zhaopin.com" if f.platform == "zhilian" else "zhipin.com"
                        result = json.loads(m.launch_job_detail_collection(f.platform, f"https://www.{domain}/synthetic", KW))
                    self.assertTrue(result["ok"])
                    self.assertTrue(result["monitor"]["started"])
                    start.assert_called_once()
                    browser.assert_not_called()
                    original = f.tasks_path.read_bytes() + b"incomplete"
                    f.tasks_path.write_bytes(original)
                    start.reset_mock()
                    if f.queue == "list":
                        failure = json.loads(m.launch_job_list_collection(f.platform, KW))
                    else:
                        failure = json.loads(m.launch_job_detail_collection(f.platform, f"https://www.{domain}/synthetic", KW))
                    self.assertFalse(failure["ok"])
                    start.assert_not_called()
                    self.assertEqual(f.tasks_path.read_bytes(), original)

    def test_native_worker_stays_alive_for_task_enqueued_after_completion(self):
        # Real local worker/MCP helper; all queue/state paths are temporary. Terminate
        # only this synthetic subprocess during test cleanup.
        import mcp_server as m
        f = Fixture(self.root / "native_start", "zhilian", "detail")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1)])
        identity = worker.identity(f.task(1), f.queue)
        task_bytes, result_bytes = f.tasks_path.read_bytes(), f.results_path.read_bytes()
        unique = {identity: f.task(1)}
        with patch.object(tempfile, "tempdir", str(f.root)), patch.dict(os.environ, {
            "TEMP": str(f.root), "TMP": str(f.root), "TMPDIR": str(f.root),
        }), patch.object(m, "DOWNLOADS_PATH", str(f.downloads)), patch.object(m, "STORAGE_PATH", f.storage):
            directory = worker.state_directory(f.platform, f.queue, f.downloads, f.storage)
            monitor = worker.Monitor(f.platform, f.queue, f.downloads, f.storage, directory,
                                     runner=f.runner, notifier=lambda _message: "confirmed", clock=lambda: f.now)
            monitor.state.update(
                phase="complete",
                batch_id=worker.checksum(worker.canonical(list(unique.items())).encode("utf-8")),
                complete_snapshot=worker.checksum(task_bytes + b"\\0" + result_bytes),
                handled=[identity],
                stats={"total": 1, "done": 1, "failed": 0, "keyword": KW},
            )
            monitor.save()
            original_popen = subprocess.Popen
            children = []
            def capture_worker(*args, **kwargs):
                child = original_popen(*args, **kwargs)
                children.append(child)
                return child
            with patch.object(m.subprocess, "Popen", side_effect=capture_worker):
                result = m._start_monitor_if_needed("zhilian")
            self.assertTrue(result["started"], result)
            try:
                deadline = time.monotonic() + 10
                while not (directory / "heartbeat.json").exists():
                    self.assertLess(time.monotonic(), deadline, "Worker failed startup acknowledgement")
                    time.sleep(0.02)
                with patch.object(m.subprocess, "Popen", side_effect=AssertionError("Existing worker must be reused")):
                    queued = json.loads(m.launch_job_detail_collection(
                        "zhilian", "https://www.zhaopin.com/jobdetail/id2.htm", KW
                    ))
                self.assertTrue(queued["ok"])
                self.assertTrue(queued["monitor"].get("running"))
                deadline = time.monotonic() + 22
                while time.monotonic() < deadline:
                    state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
                    if state.get("stats", {}).get("total") == 2:
                        break
                    time.sleep(0.1)
                self.assertEqual(state["stats"]["total"], 2)
                self.assertEqual(state["phase"], "crawling")
                self.assertEqual(len(worker.rows_from_bytes(f.tasks_path.read_bytes())), 2)
            finally:
                # Safe: this captured child and all its I/O are confined to TemporaryDirectory.
                for child in children:
                    if child.poll() is None:
                        child.terminate()
                    try:
                        child.communicate(timeout=5)
                    except Exception:
                        pass
                for thread in __import__("threading").enumerate():
                    if thread.name == "jobsniper-monitor-reaper":
                        thread.join(timeout=10)

    def test_startup_recovery_decision_is_fail_closed(self):
        # No queue: do not create directories or launch a process.
        empty = Fixture(self.root / "startup_empty")
        should, reason = worker.startup_recovery_decision("zhilian", "detail", empty.downloads, empty.storage)
        self.assertFalse(should)
        self.assertEqual(reason, "queue file absent")
        self.assertFalse(worker.state_directory("zhilian", "detail", empty.downloads, empty.storage).exists())

        # Valid unfinished queue with no results is resumable.
        pending = Fixture(self.root / "startup_pending")
        pending.write(pending.tasks_path, [pending.task(1)])
        self.assertTrue(worker.startup_recovery_decision("zhilian", "detail", pending.downloads, pending.storage)[0])

        # State loss with failed results must not reset retry budget or requeue blindly.
        failed = Fixture(self.root / "startup_failed")
        failed.write(failed.tasks_path, [failed.task(1)])
        failed.write(failed.results_path, [failed.result(1, "failed", "synthetic timeout")])
        should, reason = worker.startup_recovery_decision("zhilian", "detail", failed.downloads, failed.storage)
        self.assertFalse(should)
        self.assertIn("retry budget", reason)
        self.assertEqual(len(worker.rows_from_bytes(failed.tasks_path.read_bytes())), 1)

        security = Fixture(self.root / "startup_security")
        security.write(security.tasks_path, [security.task(1)])
        security.write(security.results_path, [security.result(1, "failed", "captcha detected")])
        should, reason = worker.startup_recovery_decision("zhilian", "detail", security.downloads, security.storage)
        self.assertFalse(should)
        self.assertIn("manual intervention", reason)

        # State loss with a done task and verifiable fresh source can resume archiving.
        done = Fixture(self.root / "startup_done")
        done.write(done.tasks_path, [done.task(1)])
        done.write(done.results_path, [done.result(1)])
        done.output(1)
        self.assertTrue(worker.startup_recovery_decision("zhilian", "detail", done.downloads, done.storage)[0])

        # State loss with done results but no source output is ambiguous: leave it untouched.
        missing = Fixture(self.root / "startup_missing")
        missing.write(missing.tasks_path, [missing.task(1)])
        missing.write(missing.results_path, [missing.result(1)])
        should, reason = worker.startup_recovery_decision("zhilian", "detail", missing.downloads, missing.storage)
        self.assertFalse(should)
        self.assertIn("manual review", reason)

        # Malformed queue and malformed state are never repaired or overwritten.
        malformed = Fixture(self.root / "startup_malformed")
        malformed.write(malformed.tasks_path, [malformed.task(1)])
        malformed.tasks_path.write_bytes(malformed.tasks_path.read_bytes() + b'{"url":')
        original = malformed.tasks_path.read_bytes()
        self.assertFalse(worker.startup_recovery_decision("zhilian", "detail", malformed.downloads, malformed.storage)[0])
        self.assertEqual(malformed.tasks_path.read_bytes(), original)

        bad_state = Fixture(self.root / "startup_bad_state")
        bad_state.write(bad_state.tasks_path, [bad_state.task(1)])
        bad_state_dir = worker.state_directory("zhilian", "detail", bad_state.downloads, bad_state.storage)
        bad_monitor = worker.Monitor("zhilian", "detail", bad_state.downloads, bad_state.storage, bad_state_dir)
        bad_monitor.state_file.write_text("{invalid", encoding="utf-8")
        original = bad_state.tasks_path.read_bytes()
        should, reason = worker.startup_recovery_decision("zhilian", "detail", bad_state.downloads, bad_state.storage)
        self.assertFalse(should)
        self.assertIn("state is unreadable", reason)
        self.assertEqual(bad_state.tasks_path.read_bytes(), original)

        schema_state = Fixture(self.root / "startup_bad_state_schema")
        schema_state.write(schema_state.tasks_path, [schema_state.task(1)])
        schema_monitor = worker.Monitor("zhilian", "detail", schema_state.downloads, schema_state.storage,
                                       worker.state_directory("zhilian", "detail", schema_state.downloads, schema_state.storage))
        schema_monitor.state["handled"] = "not-a-list"
        schema_monitor.save()
        should, reason = worker.startup_recovery_decision("zhilian", "detail", schema_state.downloads, schema_state.storage)
        self.assertFalse(should)
        self.assertIn("schema is invalid", reason)

        # A matching complete snapshot is not restarted; a validated archive intent is.
        complete = Fixture(self.root / "startup_complete")
        complete.write(complete.tasks_path, [complete.task(1)])
        complete.write(complete.results_path, [complete.result(1)])
        complete_state_dir = worker.state_directory("zhilian", "detail", complete.downloads, complete.storage)
        cm = worker.Monitor("zhilian", "detail", complete.downloads, complete.storage, complete_state_dir)
        ident = worker.identity(complete.task(1), complete.queue)
        task_bytes, result_bytes = complete.tasks_path.read_bytes(), complete.results_path.read_bytes()
        cm.state.update(phase="complete", batch_id=worker.checksum(worker.canonical([(ident, complete.task(1))]).encode("utf-8")),
                        complete_snapshot=worker.checksum(task_bytes + b"\\0" + result_bytes), handled=[ident])
        cm.save()
        self.assertFalse(worker.startup_recovery_decision("zhilian", "detail", complete.downloads, complete.storage)[0])

        intent = Fixture(self.root / "startup_archive_intent")
        intent.write(intent.tasks_path, [intent.task(1)])
        intent.write(intent.results_path, [intent.result(1)])
        source = intent.output(1)
        intent_state_dir = worker.state_directory("zhilian", "detail", intent.downloads, intent.storage)
        im = worker.Monitor("zhilian", "detail", intent.downloads, intent.storage, intent_state_dir)
        im.state["phase"] = "error"
        im.state["archive_jobs"] = [{"keyword": KW, "done": False, "entries": [
            {"source": str(source), "target": str(intent.storage / "positions" / "zhilian_intelligence_vault" / "target.md"),
             "sha256": worker.file_digest(source)}]}]
        im.save()
        self.assertTrue(worker.startup_recovery_decision("zhilian", "detail", intent.downloads, intent.storage)[0])

    def test_mcp_startup_schedules_only_eligible_native_queues(self):
        if os.name != "nt":
            self.skipTest("Native Windows startup recovery is platform-specific")
        import mcp_server as m
        f = Fixture(self.root / "startup_schedule")
        pending = f.task(1)
        f.write(f.downloads / "zhilian_detail_tasks.jsonl", [pending])
        (f.downloads / "zhilian_list_tasks.jsonl").write_bytes(b'{"url":')  # One bad queue must not block the other three.

        complete_task = {**f.task(2), "task_id": "task2"}
        complete_result = {**complete_task, "task_index": 0, "status": "done", "recorded_at": datetime.now(timezone.utc).isoformat(), "file_name": "BOSS_合成岗位_20261016_120000.md"}
        f.write(f.downloads / "boss_list_tasks.jsonl", [complete_task])
        f.write(f.downloads / "boss_list_results.jsonl", [complete_result])
        output = f.downloads / complete_result["file_name"]
        output.write_text("done", encoding="utf-8")
        complete_state_dir = worker.state_directory("boss", "list", f.downloads, f.storage)
        complete_monitor = worker.Monitor("boss", "list", f.downloads, f.storage, complete_state_dir)
        done_id = worker.identity(complete_task, "list")
        task_bytes = (f.downloads / "boss_list_tasks.jsonl").read_bytes()
        result_bytes = (f.downloads / "boss_list_results.jsonl").read_bytes()
        complete_monitor.state.update(phase="complete", batch_id=worker.checksum(worker.canonical([(done_id, complete_task)]).encode("utf-8")),
                                      complete_snapshot=worker.checksum(task_bytes + b"\\0" + result_bytes), handled=[done_id])
        complete_monitor.save()

        starts = []
        class InlineThread:
            def __init__(self, *, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
        with (
            patch.object(m, "DOWNLOADS_PATH", str(f.downloads)),
            patch.object(m, "STORAGE_PATH", f.storage),
            patch.object(m.threading, "Thread", InlineThread),
            patch.object(m, "_start_native_monitor", side_effect=lambda platform, queue: starts.append((platform, queue)) or {"started": True}),
        ):
            m._recover_native_monitors()
        self.assertEqual(starts, [("zhilian", "detail")])

    def test_mcp_startup_resumes_pending_queue_in_background(self):
        if os.name != "nt":
            self.skipTest("Native Windows startup recovery is platform-specific")
        import mcp_server as m
        f = Fixture(self.root / "startup_worker")
        f.write(f.downloads / "zhilian_detail_tasks.jsonl", [f.task(1)])
        directory = worker.state_directory("zhilian", "detail", f.downloads, f.storage)
        original_popen = subprocess.Popen
        children = []
        def capture_worker(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child
        with (
            patch.object(tempfile, "tempdir", str(self.root)),
            patch.dict(os.environ, {"TEMP": str(self.root), "TMP": str(self.root), "TMPDIR": str(self.root)}),
            patch.object(m, "DOWNLOADS_PATH", str(f.downloads)),
            patch.object(m, "STORAGE_PATH", f.storage),
            patch.object(m.subprocess, "Popen", side_effect=capture_worker),
        ):
            m._recover_native_monitors()
            try:
                deadline = time.monotonic() + 15
                state = None
                while time.monotonic() < deadline:
                    if (directory / "state.json").exists():
                        try:
                            state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
                            if state.get("stats", {}).get("total") == 1:
                                break
                        except (OSError, ValueError):
                            pass
                    time.sleep(0.05)
                self.assertEqual(len(children), 1)
                self.assertTrue((directory / "heartbeat.json").exists())
                self.assertIsNone(children[0].poll(), "Recovered worker should remain active for the pending task")
                self.assertIsNotNone(state, "Worker did not persist a startup snapshot")
                self.assertEqual(state["stats"]["total"], 1)
                self.assertEqual(state["phase"], "crawling")
                competing = worker.FileLock(directory / "monitor.lock")
                self.assertFalse(competing.acquire(), "Recovered worker must hold the queue lock")
            finally:
                for child in children:
                    if child.poll() is None:
                        child.terminate()
                    child.communicate(timeout=10)
                import threading
                for thread in threading.enumerate():
                    if thread.name in ("jobsniper-startup-recovery", "jobsniper-monitor-reaper"):
                        thread.join(timeout=10)

    def test_test_mode_output_is_retained_without_archive(self):
        f = Fixture(self.root / "test_output", "zhilian", "list")
        f.write(f.tasks_path, [f.task(1)])
        result = f.result(1)
        result["file_name"] = "ZHILIAN_TEST_合成岗位_20260101_120000.md"
        f.write(f.results_path, [result])
        source = f.downloads / result["file_name"]
        source.write_text("test output", encoding="utf-8")
        state_dir = worker.state_directory("zhilian", "list", f.downloads, f.storage)
        m = worker.Monitor(f.platform, f.queue, f.downloads, f.storage, state_dir,
                           runner=f.runner, notifier=lambda message: f.notices.append(message) or "confirmed",
                           clock=lambda: f.now)
        self.assertEqual(m.step(), "complete")
        self.assertEqual(m.step(), "complete")
        self.assertFalse(f.archive_calls())
        self.assertTrue(source.exists())
        self.assertIn(worker.identity(f.task(1), f.queue), m.state["handled"])
        self.assertFalse(worker.startup_recovery_decision("zhilian", "list", f.downloads, f.storage)[0])

    def test_legacy_r6_equivalent_branches_reproduce_unbounded_requeues(self):
        # No bash/WSL execution. Apply the old shell's checksum-reset/requeue branches
        # to real synthetic files, using its real parser at each iteration.
        f = Fixture(self.root / "legacy_r6")
        f.write(f.tasks_path, [f.task(1)])
        f.write(f.results_path, [f.result(1, "failed", "synthetic timeout")])
        previous, retries = worker.checksum(f.tasks_path.read_bytes()), 0
        for _ in range(5):
            signature = worker.checksum(f.tasks_path.read_bytes())
            if signature != previous:
                retries = 0  # NEW BATCH in old shell; this is the bug.
                previous = signature
            result = subprocess.run([sys.executable, "-X", "utf8", str(worker.SCRIPT_DIR / "parse_detail_results.py"),
                                     str(f.results_path), str(f.tasks_path)],
                                    capture_output=True, text=True, encoding="utf-8", check=True)
            stats = worker.parse_assignments(result.stdout)
            if stats["failed"] and stats["done"] + stats["failed"] >= stats["total"] and retries < 1:
                with f.tasks_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(f.task(1)) + "\n")
                retries += 1
        self.assertEqual(len(worker.rows_from_bytes(f.tasks_path.read_bytes())), 6)

    def test_manifest_validation_backup_and_copy_idempotency(self):
        f = Fixture(self.root / "archiver")
        with patch.dict(os.environ, {"JOBSNIPER_STORAGE_ROOT": str(f.storage), "JOBSNIPER_DOWNLOADS_PATH": str(f.downloads)}):
            spec = importlib.util.spec_from_file_location("synthetic_archiver", worker.SCRIPT_DIR / "archive_outputs.py")
            archive = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(archive)
        source = f.output(1)
        manifest = f.root / "manifest.json"
        worker.save_json(manifest, [{"source": str(source), "sha256": "0" * 64}])
        result = archive.archive(KW, files_manifest=manifest)
        self.assertFalse(result["ok"])
        self.assertTrue(source.exists())
        worker.save_json(manifest, [{"source": str(f.root / "outside.md"), "sha256": "0" * 64}])
        self.assertFalse(archive.archive(KW, files_manifest=manifest)["ok"])
        worker.save_json(manifest, [])
        self.assertEqual(archive.archive(KW, files_manifest=manifest)["planned_count"], 0)
        worker.save_json(manifest, [{"source": str(source), "sha256": worker.file_digest(source)}])
        with patch.object(archive.shutil, "move", side_effect=PermissionError("synthetic read-only source")):
            first = archive.archive(KW, files_manifest=manifest)
        self.assertTrue(first["ok"])
        self.assertEqual(first["copied_count"], 1)
        again = archive.archive(KW, files_manifest=manifest)
        self.assertEqual(again["already_archived_count"], 1)
        self.assertEqual(again["moved_count"], 0)
        index = f.downloads / f"ZHILIAN_{KW}_index.md"
        index.write_text("new index", encoding="utf-8")
        task = archive._load_zhilian_task(KW)
        target = archive._target_for_joblens_output(index, KW, task, archive.VAULT_PATH, "zhilian")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("manual index", encoding="utf-8")
        worker.save_json(manifest, [{"source": str(index), "sha256": worker.file_digest(index)}])
        with patch.object(archive.shutil, "copy2", side_effect=PermissionError("synthetic backup failure")):
            failure = archive.archive(KW, files_manifest=manifest)
        self.assertFalse(failure["ok"])
        self.assertEqual(target.read_text(encoding="utf-8"), "manual index")
        result = archive.archive(KW, files_manifest=manifest)
        self.assertTrue(result["ok"])
        self.assertEqual(Path(result["backups"][0]["backup"]).read_text(encoding="utf-8"), "manual index")


if __name__ == "__main__":
    unittest.main(verbosity=2)
