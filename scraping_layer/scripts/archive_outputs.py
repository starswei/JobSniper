#!/usr/bin/env python3
"""Standalone archiver: archive Joblens output from Downloads to vault.
Usage: python3 scraping_layer/scripts/archive_outputs.py <keyword> <platform> [--since-minutes N] [--dry-run] [--include-test]
"""
import filecmp
import json, os, re, shutil, sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DOWNLOADS_PATH = Path(os.environ.get("JOBSNIPER_DOWNLOADS_PATH", "/mnt/d/Downloads"))
STORAGE_PATH = BASE_DIR / "storage_layer"
POSITIONS_PATH = STORAGE_PATH / "positions"
VAULT_PATH = POSITIONS_PATH / "zhilian_intelligence_vault"
BOSS_VAULT_PATH = POSITIONS_PATH / "boss_intelligence_vault"
TASKS_PATH = POSITIONS_PATH / "zhilian_master_tasks.json"

def _safe_keyword_dir(keyword):
    return re.sub(r'[\\/:*?"<>|]+', "_", keyword).strip() or "Unknown"

def _load_zhilian_task(keyword):
    fallback = {"keyword": keyword, "industry": "Unknown_Industry", "domain": "Unknown_Domain", "url": ""}
    try:
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            tasks = json.load(f)
    except Exception:
        return fallback
    for task in tasks:
        if task.get("keyword") == keyword:
            return {"keyword": task.get("keyword", keyword),
                    "industry": task.get("industry") or fallback["industry"],
                    "domain": task.get("domain") or fallback["domain"],
                    "url": task.get("url") or ""}
    return fallback

def _job_category_dir(keyword, task, vault_path):
    return vault_path / _safe_keyword_dir(task["industry"]) / _safe_keyword_dir(task["domain"]) / _safe_keyword_dir(keyword)

def _platform_task_prefix(platform):
    return "ZHILIAN" if platform == "zhilian" else "BOSS"

def _contains_keyword(file_name, keyword):
    return keyword.lower() in file_name.lower()

def _parse_frontmatter_keyword(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, min(len(lines), 30)):
        line = lines[i].strip()
        if line == "---":
            break
        m = re.match(r"^keyword:\s*(.+)", line)
        if m:
            return m.group(1).strip()
    return None

def _target_for_joblens_output(file_path, keyword, task, vault_path, platform):
    name = file_path.name
    suffix = file_path.suffix.lower()
    pfx = _platform_task_prefix(platform)
    is_raw = suffix in {".json", ".html"} or "_RAW_" in name or name.startswith(f"{pfx}_RAW_")
    job_dir = _job_category_dir(keyword, task, vault_path)

    if (name.startswith("zhilian_keyword_discovery_") or name.startswith(f"{pfx}_KEYWORDS_")) and suffix == ".md":
        return POSITIONS_PATH / name
    if name.startswith(f"{pfx}_DETAIL_"):
        if is_raw:
            return job_dir / "raw" / name
        m = re.match(rf"{pfx}_DETAIL_(.+)_\d{{8}}_\d{{6}}\.md$", name)
        if m:
            return job_dir / f"{m.group(1)}.md"
        return job_dir / name
    if name.startswith(f"{pfx}_RAW_"):
        return job_dir / "raw" / name
    if name.startswith(f"{pfx}_") and suffix == ".md":
        return job_dir / f"_岗位索引表_{_safe_keyword_dir(keyword)}.md"
    if suffix == ".md":
        return job_dir / name
    return None

def _unique_target_path(target, overwrite=False):
    if overwrite or not target.exists():
        return target
    stem, suffix, parent = target.stem, target.suffix, target.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

def archive(keyword, platform="zhilian", since_minutes=60, dry_run=False, include_test=False):
    vault_path = {"zhilian": VAULT_PATH, "boss": BOSS_VAULT_PATH}[platform]
    downloads = DOWNLOADS_PATH
    cutoff = datetime.now() - timedelta(minutes=since_minutes)
    task = _load_zhilian_task(keyword)
    pfx = _platform_task_prefix(platform)
    can_unlink_sources = os.access(str(downloads), os.W_OK)

    planned, skipped = [], []
    candidates = {p for pattern in (f"{pfx}_*", "zhilian_keyword_discovery_*.md") for p in downloads.glob(pattern)}
    for file_path in sorted(candidates):
        if not file_path.is_file():
            continue
        modified = datetime.fromtimestamp(file_path.stat().st_mtime)
        if modified < cutoff:
            skipped.append({"file": str(file_path), "reason": "outside since_minutes window"})
            continue
        if not include_test and "TEST" in file_path.name.upper():
            skipped.append({"file": str(file_path), "reason": "TEST output excluded"})
            continue
        if file_path.suffix.lower() != ".md":
            skipped.append({"file": str(file_path), "reason": "not a markdown file"})
            continue
        if file_path.name.startswith((f"{pfx}_DETAIL_RAW_", f"{pfx}_DETAIL_MANIFEST_", f"{pfx}_RAW_")):
            skipped.append({"file": str(file_path), "reason": "raw or manifest file"})
            continue

        is_detail = file_path.name.startswith(f"{pfx}_DETAIL_") and not file_path.name.startswith((f"{pfx}_DETAIL_RAW_", f"{pfx}_DETAIL_MANIFEST_"))
        fm_kw = _parse_frontmatter_keyword(file_path) if (is_detail and file_path.suffix.lower() == ".md") else None

        if (not file_path.name.startswith((f"{pfx}_KEYWORDS_", "zhilian_keyword_discovery_", f"{pfx}_DETAIL_RAW_", f"{pfx}_DETAIL_MANIFEST_"))
                and not re.match(rf"{pfx}_DETAIL_.+_\d{{8}}_\d{{6}}\.md$", file_path.name)
                and not _contains_keyword(file_path.name, keyword)):
            skipped.append({"file": str(file_path), "reason": "keyword mismatch"})
            continue

        file_task = _load_zhilian_task(fm_kw) if fm_kw else task
        file_kw = fm_kw if fm_kw else keyword
        target = _target_for_joblens_output(file_path, file_kw, file_task, vault_path, platform)
        if target is None:
            skipped.append({"file": str(file_path), "reason": "unrecognized pattern"})
            continue
        # If we can't unlink sources (e.g. `/mnt/d` is mounted read-only), prefer an idempotent
        # plan and decide the final target during execution:
        # - if target exists and contents match: skip
        # - if target exists and differs: write to a unique sibling
        is_index = target.stem.startswith("_岗位索引表") or target.stem.startswith("_关键词发现结果")
        final_target = _unique_target_path(target, overwrite=is_index) if can_unlink_sources else target
        planned.append({"source": str(file_path), "target": str(final_target), "modified": modified.isoformat(timespec="seconds")})

    moved = []
    copied = []
    already_archived = []
    if not dry_run:
        for item in planned:
            source, target = Path(item["source"]), Path(item["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                if can_unlink_sources:
                    shutil.move(str(source), str(target))
                    moved.append({"source": str(source), "target": str(target)})
                else:
                    # Copy mode (can't delete sources): avoid creating duplicates on repeated runs.
                    if target.exists():
                        try:
                            if filecmp.cmp(str(source), str(target), shallow=False):
                                already_archived.append({"source": str(source), "target": str(target)})
                                continue
                        except Exception:
                            pass
                        is_idx = target.stem.startswith("_岗位索引表") or target.stem.startswith("_关键词发现结果")
                        target = _unique_target_path(target, overwrite=is_idx)
                        target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(source), str(target))
                    copied.append({"source": str(source), "target": str(target)})
            except OSError:
                # Last resort: copy when move fails.
                try:
                    if target.exists():
                        try:
                            if filecmp.cmp(str(source), str(target), shallow=False):
                                already_archived.append({"source": str(source), "target": str(target)})
                                continue
                        except Exception:
                            pass
                        is_idx = target.stem.startswith("_岗位索引表") or target.stem.startswith("_关键词发现结果")
                        target = _unique_target_path(target, overwrite=is_idx)
                        target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(source), str(target))
                    copied.append({"source": str(source), "target": str(target)})
                except Exception:
                    # Keep going; we'll report it as skipped by omission from moved/copied.
                    pass

    return {"ok": True, "dry_run": dry_run, "planned_count": len(planned),
            "moved_count": len(moved), "copied_count": len(copied),
            "planned": planned, "moved": moved, "copied": copied,
            "already_archived_count": len(already_archived), "already_archived": already_archived,
            "skipped_count": len(skipped), "skipped": skipped}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("keyword")
    p.add_argument("--platform", default="zhilian")
    p.add_argument("--since-minutes", type=int, default=60)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--include-test", action="store_true")
    args = p.parse_args()
    result = archive(args.keyword, args.platform, args.since_minutes, args.dry_run, args.include_test)
    print(json.dumps(result, indent=2, ensure_ascii=False))
