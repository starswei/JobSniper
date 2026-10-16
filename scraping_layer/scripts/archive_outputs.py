#!/usr/bin/env python3
"""Standalone archiver; --files-manifest restricts automatic archiving to done outputs."""
import argparse
import filecmp
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DOWNLOADS_PATH = Path(os.environ.get("JOBSNIPER_DOWNLOADS_PATH", "").strip() or
                      (r"D:\Downloads" if os.name == "nt" else "/mnt/d/Downloads"))
STORAGE_PATH = Path(os.environ.get("JOBSNIPER_STORAGE_ROOT", "").strip() or BASE_DIR / "storage_layer")
POSITIONS_PATH = STORAGE_PATH / "positions"
VAULT_PATH = POSITIONS_PATH / "zhilian_intelligence_vault"
BOSS_VAULT_PATH = POSITIONS_PATH / "boss_intelligence_vault"
TASKS_PATH = POSITIONS_PATH / "zhilian_master_tasks.json"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _safe_keyword_dir(keyword):
    return re.sub(r'[\\/:*?"<>|]+', "_", keyword).strip() or "Unknown"


def _load_zhilian_task(keyword, platform="zhilian"):
    fallback = {"keyword": keyword, "industry": "Unknown_Industry", "domain": "Unknown_Domain", "url": ""}
    path = POSITIONS_PATH / f"{platform}_master_tasks.json"
    try:
        tasks = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    for task in tasks:
        if task.get("keyword") == keyword:
            return {key: task.get(key) or value for key, value in fallback.items()}
    return fallback


def _job_category_dir(keyword, task, vault_path):
    return vault_path / _safe_keyword_dir(task["industry"]) / _safe_keyword_dir(task["domain"]) / _safe_keyword_dir(keyword)


def _platform_task_prefix(platform):
    return "ZHILIAN" if platform == "zhilian" else "BOSS"


def _contains_keyword(file_name, keyword):
    return keyword.lower() in file_name.lower()


def _parse_frontmatter_keyword(file_path):
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:30]:
        if line.strip() == "---":
            break
        match = re.match(r"^keyword:\s*(.+)", line)
        if match:
            return match.group(1).strip().strip("\"'")
    return None


def _target_for_joblens_output(file_path, keyword, task, vault_path, platform):
    name, suffix = file_path.name, file_path.suffix.lower()
    pfx = _platform_task_prefix(platform)
    is_raw = suffix in {".json", ".html"} or "_RAW_" in name or name.startswith(f"{pfx}_RAW_")
    job_dir = _job_category_dir(keyword, task, vault_path)
    if (name.startswith(f"{platform}_keyword_discovery_") or name.startswith(f"{pfx}_KEYWORDS_")) and suffix == ".md":
        return POSITIONS_PATH / name
    if name.startswith(f"{pfx}_DETAIL_"):
        if is_raw:
            return job_dir / "raw" / name
        match = re.match(rf"{pfx}_DETAIL_(.+)_\d{{8}}_\d{{6}}\.md$", name)
        return job_dir / (f"{match.group(1)}.md" if match else name)
    if name.startswith(f"{pfx}_COMPANY_"):
        if is_raw or "MANIFEST" in name:
            return job_dir / "company" / "raw" / name
        match = re.match(rf"{pfx}_COMPANY_(.+)_\d{{8}}_\d{{6}}\.md$", name)
        return job_dir / "company" / (f"{match.group(1)}.md" if match else name)
    if name.startswith(f"{pfx}_RAW_"):
        return job_dir / "raw" / name
    if name.startswith(f"{pfx}_") and suffix == ".md":
        return job_dir / f"_岗位索引表_{_safe_keyword_dir(keyword)}.md"
    return job_dir / name if suffix == ".md" else None


def _unique_target_path(target, overwrite=False, reserved=()):
    # Even overwriteable indexes need distinct destinations inside one manifest.
    if (overwrite or not target.exists()) and target not in reserved:
        return target
    counter = 1
    while True:
        candidate = target.with_name(f"{target.stem}_{counter}{target.suffix}")
        if not candidate.exists() and candidate not in reserved:
            return candidate
        counter += 1


def archive(keyword, platform="zhilian", since_minutes=60, dry_run=False, include_test=False, files_manifest=None):
    planned, skipped, failed = [], [], []
    moved, copied, already_archived, backups = [], [], [], []
    if platform not in ("zhilian", "boss") or not keyword.strip() or since_minutes <= 0:
        return {"ok": False, "error": "Invalid platform, keyword or since_minutes"}
    downloads = DOWNLOADS_PATH.resolve()
    if not downloads.is_dir():
        return {"ok": False, "error": f"Downloads directory does not exist: {downloads}"}
    vault = VAULT_PATH if platform == "zhilian" else BOSS_VAULT_PATH
    pfx = _platform_task_prefix(platform)
    cutoff = datetime.now() - timedelta(minutes=since_minutes)
    expected = {}
    if files_manifest is not None:
        # No glob in automatic mode. Empty manifest means no files, never "all files".
        try:
            entries = json.loads(Path(files_manifest).read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                raise ValueError("Manifest must be a list")
            for entry in entries:
                source = Path(entry["source"])
                checksum = entry["sha256"]
                fixed_target = entry.get("target")
                if fixed_target is not None and (not isinstance(fixed_target, str) or not Path(fixed_target).is_absolute()):
                    raise ValueError("Manifest target must be an absolute path")
                if not source.is_absolute() or source.is_symlink() or source.resolve().parent != downloads:
                    raise ValueError("Manifest source must be a direct, non-symlink Downloads child")
                if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                    raise ValueError("Manifest must contain a SHA-256 per source")
                expected[source.resolve()] = {"sha256": checksum, "target": fixed_target}
            candidates = sorted(expected)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return {"ok": False, "error": f"Invalid manifest: {exc}"}
    else:
        candidates = sorted({path for pattern in (f"{pfx}_*", f"{platform}_keyword_discovery_*.md")
                             for path in downloads.glob(pattern)})
    reserved = set()
    for source in candidates:
        try:
            if source.is_symlink() or source.resolve().parent != downloads or not source.is_file():
                raise ValueError("Source is missing, outside Downloads, or is a symlink")
            if not (source.name.startswith(f"{pfx}_") or source.name.startswith(f"{platform}_keyword_discovery_")):
                raise ValueError("Source platform mismatch")
            if source.suffix.lower() != ".md" or any(part in source.name for part in ("_RAW_", "_MANIFEST_")):
                raise ValueError("Only Markdown outputs, not RAW/MANIFEST files, can be archived")
            if not include_test and "TEST" in source.name.upper():
                skipped.append({"file": str(source), "reason": "TEST output excluded"})
                continue
            if files_manifest is None and datetime.fromtimestamp(source.stat().st_mtime) < cutoff:
                skipped.append({"file": str(source), "reason": "outside since_minutes window"})
                continue
            source_hash = digest(source)
            if source in expected and source_hash != expected[source]["sha256"]:
                raise ValueError("Source changed since monitor snapshot")
            is_detail = source.name.startswith((f"{pfx}_DETAIL_", f"{pfx}_COMPANY_"))
            file_keyword = _parse_frontmatter_keyword(source) if is_detail else None
            if files_manifest is None and not is_detail and not source.name.startswith((f"{pfx}_KEYWORDS_", f"{platform}_keyword_discovery_")) and not _contains_keyword(source.name, keyword):
                skipped.append({"file": str(source), "reason": "keyword mismatch"})
                continue
            file_keyword = file_keyword or keyword
            task = _load_zhilian_task(file_keyword, platform)
            target = _target_for_joblens_output(source, file_keyword, task, vault, platform)
            if target is None or not target.resolve().is_relative_to(POSITIONS_PATH.resolve()):
                raise ValueError("Invalid archive target")
            identical = target.is_file() and filecmp.cmp(source, target, shallow=False)
            is_index = target.stem.startswith(("_岗位索引表", "_关键词发现结果"))
            if source in expected and expected[source]["target"] is not None:
                fixed_target = Path(expected[source]["target"]).resolve()
                if not fixed_target.is_relative_to(POSITIONS_PATH.resolve()) or fixed_target.parent != target.parent:
                    raise ValueError("Manifest target is outside the expected archive directory")
                is_collision_sibling = re.fullmatch(re.escape(target.stem) + r"_\d+" + re.escape(target.suffix), fixed_target.name)
                if fixed_target != target and not is_collision_sibling:
                    raise ValueError("Manifest target does not match the planned archive target")
                target = fixed_target
            elif not identical:
                target = _unique_target_path(target, overwrite=is_index, reserved=reserved)
            reserved.add(target)
            planned.append({"source": str(source), "target": str(target), "sha256": source_hash,
                            "modified": datetime.fromtimestamp(source.stat().st_mtime).isoformat(timespec="seconds")})
        except Exception as exc:
            failed.append({"source": str(source), "error": str(exc), "stage": "plan"})

    if not dry_run:
        for item in planned:
            source, target = Path(item["source"]), Path(item["target"])
            try:
                if digest(source) != item["sha256"]:
                    raise ValueError("Source changed before archive execution")
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file() and filecmp.cmp(source, target, shallow=False):
                    already_archived.append(item)
                    continue
                is_index = target.stem.startswith(("_岗位索引表", "_关键词发现结果"))
                if target.exists() and not is_index:
                    raise FileExistsError(f"Refusing to overwrite non-index archive target: {target}")
                if is_index and target.exists():
                    backup = _unique_target_path(Path(str(target) + ".bak"))
                    shutil.copy2(target, backup)
                    backups.append({"target": str(target), "backup": str(backup)})
                try:
                    shutil.move(str(source), str(target))
                    moved.append(item)
                except OSError:
                    # Preserve WSL's read-only-downloads copy fallback; failures are now explicit.
                    if not (target.is_file() and filecmp.cmp(source, target, shallow=False)):
                        shutil.copy2(source, target)
                    copied.append(item)
            except Exception as exc:
                failed.append({"source": str(source), "target": str(target), "error": str(exc), "stage": "execute"})
    return {"ok": not failed, "dry_run": dry_run, "planned_count": len(planned), "planned": planned,
            "moved_count": len(moved), "moved": moved, "copied_count": len(copied), "copied": copied,
            "already_archived_count": len(already_archived), "already_archived": already_archived,
            "failed_count": len(failed), "failed": failed, "backups": backups,
            "skipped_count": len(skipped), "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("keyword")
    parser.add_argument("--platform", choices=("zhilian", "boss"), default="zhilian")
    parser.add_argument("--since-minutes", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-test", action="store_true")
    parser.add_argument("--files-manifest", help="JSON list of absolute source paths and SHA-256 checksums")
    args = parser.parse_args()
    result = archive(args.keyword, args.platform, args.since_minutes, args.dry_run, args.include_test, args.files_manifest)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
