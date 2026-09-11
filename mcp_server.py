from mcp.server.fastmcp import FastMCP
from mcp.client.session import SessionMessage
from mcp import types
import anyio
import os
import json
import base64
import re
import shutil
import subprocess
import sys
import time
import queue
import threading
import hashlib
import glob
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# 初始化 FastMCP
mcp = FastMCP("JobSniper")

# 基础路径配置
BASE_DIR = Path(__file__).resolve().parent
STORAGE_PATH = BASE_DIR / "storage_layer"
PERSONA_PATH = STORAGE_PATH / "personas" / "current_user.json"
POSITIONS_PATH = STORAGE_PATH / "positions"
VAULT_PATH = POSITIONS_PATH / "zhilian_intelligence_vault"
BOSS_VAULT_PATH = POSITIONS_PATH / "boss_intelligence_vault"
TASKS_PATH = POSITIONS_PATH / "zhilian_master_tasks.json"
BOSS_TASKS_PATH = POSITIONS_PATH / "boss_master_tasks.json"
SCRAPING_PATH = BASE_DIR / "scraping_layer"
JOBLENS_PATH = SCRAPING_PATH / "joblens"
JOBLENS_DIST_PATH = JOBLENS_PATH / "dist"
# 本地路径解析：环境变量 > 自动探测 > 默认值（见 README「本地路径配置」）
def _detect_downloads_path() -> Path:
    """解析 Downloads 目录。

    优先级：环境变量 JOBSNIPER_DOWNLOADS_PATH > 自动探测常见路径 > 默认 /mnt/d/Downloads。
    """
    env_value = os.environ.get("JOBSNIPER_DOWNLOADS_PATH", "").strip()
    if env_value:
        return Path(env_value)
    candidates = [
        Path("/mnt/d/Downloads"),
        Path.home() / "Downloads",
        *sorted(Path(p) for p in glob.glob("/mnt/*/Users/*/Downloads")),
        *sorted(Path(p) for p in glob.glob("/mnt/*/Downloads")),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def _detect_windows_chrome() -> str:
    """解析 Windows 侧浏览器可执行文件路径。

    优先级：环境变量 JOBSNIPER_CHROME_PATH > 自动探测常见安装位置 > 默认 Chrome 稳定版。
    """
    env_value = os.environ.get("JOBSNIPER_CHROME_PATH", "").strip()
    if env_value:
        return env_value
    candidates = [
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
        "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        *sorted(glob.glob("/mnt/*/Users/*/AppData/Local/Google/Chrome/Application/chrome.exe")),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"


DOWNLOADS_PATH = str(_detect_downloads_path())
WINDOWS_CHROME_PATH = _detect_windows_chrome()
MONITOR_SCRIPT = SCRAPING_PATH / "scripts" / "watch_downloads.sh"
LIST_MONITOR_SCRIPT = SCRAPING_PATH / "scripts" / "watch_job_list.sh"
BOSS_MONITOR_SCRIPT = SCRAPING_PATH / "scripts" / "watch_boss_downloads.sh"
BOSS_LIST_MONITOR_SCRIPT = SCRAPING_PATH / "scripts" / "watch_boss_job_list.sh"
DETAIL_WAKE_LOCK = Path("/tmp/jobsniper_detail_queue_wake")
DETAIL_WAKE_DEBOUNCE_SECONDS = 10
LIST_WAKE_LOCK = Path("/tmp/jobsniper_list_queue_wake")
LIST_WAKE_DEBOUNCE_SECONDS = 10

# ----------------------------------------------------------------
# 通用 helper
# ----------------------------------------------------------------

def _json_response(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _base64url_utf8(value: str) -> str:
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _safe_keyword_dir(keyword: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", keyword).strip()
    return cleaned or "Unknown"


# ----------------------------------------------------------------
# 监控/唤醒 helper
# ----------------------------------------------------------------

def _start_monitor_if_needed() -> None:
    """启动下载目录监控脚本，如果未在运行"""
    if not MONITOR_SCRIPT.exists():
        return
    lock_file = Path("/tmp/watch_downloads/lock")
    # 检查是否已在运行
    if lock_file.exists():
        try:
            old_pid = int(lock_file.read_text().strip())
            os.kill(old_pid, 0)  # 信号0仅检测进程是否存在
            return  # 已在运行
        except (ValueError, OSError):
            pass  # 锁文件过期，继续启动
    try:
        subprocess.Popen(
            ["bash", str(MONITOR_SCRIPT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def _start_list_monitor_if_needed() -> None:
    """启动岗位列表队列监控脚本（如果未在运行）。"""
    if not LIST_MONITOR_SCRIPT.exists():
        return
    lock_file = Path("/tmp/watch_job_list/lock")
    if lock_file.exists():
        try:
            old_pid = int(lock_file.read_text().strip())
            os.kill(old_pid, 0)
            return
        except (ValueError, OSError):
            pass
    try:
        subprocess.Popen(
            ["bash", str(LIST_MONITOR_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def _launch_detail_queue_wake(wake_url: str) -> tuple[bool, str | None, bool]:
    """Launch Chrome wake URL unless another detail wake happened recently."""
    now = time.time()
    try:
        last_wake = float(DETAIL_WAKE_LOCK.read_text().strip()) if DETAIL_WAKE_LOCK.exists() else 0.0
    except Exception:
        last_wake = 0.0

    if now - last_wake < DETAIL_WAKE_DEBOUNCE_SECONDS:
        return False, None, True

    try:
        DETAIL_WAKE_LOCK.write_text(str(now), encoding="utf-8")
        subprocess.Popen([WINDOWS_CHROME_PATH, wake_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, None, False
    except Exception as exc:
        return False, str(exc), False


def _launch_list_queue_wake(wake_url: str) -> tuple[bool, str | None, bool]:
    """Launch Chrome wake URL unless another list wake happened recently."""
    now = time.time()
    try:
        last_wake = float(LIST_WAKE_LOCK.read_text().strip()) if LIST_WAKE_LOCK.exists() else 0.0
    except Exception:
        last_wake = 0.0

    if now - last_wake < LIST_WAKE_DEBOUNCE_SECONDS:
        return False, None, True

    try:
        LIST_WAKE_LOCK.write_text(str(now), encoding="utf-8")
        subprocess.Popen([WINDOWS_CHROME_PATH, wake_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, None, False
    except Exception as exc:
        return False, str(exc), False


# ----------------------------------------------------------------
# 岗位库 helper
# ----------------------------------------------------------------

def _platform_vault_path(platform: str) -> Path:
    normalized = platform.strip().lower()
    aliases = {
        "zhilian": VAULT_PATH,
        "智联": VAULT_PATH,
        "智联招聘": VAULT_PATH,
        "boss": BOSS_VAULT_PATH,
        "boss直聘": BOSS_VAULT_PATH,
    }
    if normalized not in aliases:
        raise ValueError("platform must be one of: zhilian, boss")
    return aliases[normalized]

def _safe_relative_path(value: str) -> Path:
    relative = Path(value.strip().strip("/"))
    if not str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("path_to_job must be a relative path inside the platform vault")
    return relative

def _read_text_file(file_path: Path) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def _find_job_files(vault_path: Path, keyword: str, company: str | None = None) -> list[Path]:
    normalized_keyword = keyword.strip().lower()
    normalized_company = company.strip().lower() if company else None
    if not normalized_keyword:
        return []

    matches: list[Path] = []
    for file_path in vault_path.rglob("*.md"):
        name = file_path.name
        if name.startswith("_"):
            continue
        normalized_name = name.lower()
        if normalized_keyword not in normalized_name:
            continue
        if normalized_company and normalized_company not in normalized_name:
            continue
        matches.append(file_path)
    return sorted(matches)


# ----------------------------------------------------------------
# 归档/采集 helper
# ----------------------------------------------------------------

def _job_category_dir(keyword: str, task: dict[str, str], vault_path: Path) -> Path:
    industry_dir = _safe_keyword_dir(task["industry"])
    domain_dir = _safe_keyword_dir(task["domain"])
    keyword_dir = _safe_keyword_dir(keyword)
    return vault_path / industry_dir / domain_dir / keyword_dir

def _platform_task_prefix(platform: str) -> str:
    return "ZHILIAN" if platform == "zhilian" else "BOSS"


def _platform_tasks_path(platform: str) -> Path:
    return TASKS_PATH if platform == "zhilian" else BOSS_TASKS_PATH


def _platform_task_file(platform: str, queue_type: str) -> Path:
    """queue_type: 'list_tasks' 或 'detail_tasks'"""
    prefix = {"zhilian": "zhilian", "boss": "boss"}[platform]
    return Path(DOWNLOADS_PATH) / f"{prefix}_{queue_type}.jsonl"


def _load_zhilian_task(keyword: str) -> dict[str, str]:
    return _load_platform_task("zhilian", keyword)


def _load_platform_task(platform: str, keyword: str) -> dict[str, str]:
    fallback = {
        "keyword": keyword,
        "industry": "Unknown_Industry",
        "domain": "Unknown_Domain",
        "url": "",
    }
    tasks_path = _platform_tasks_path(platform)
    try:
        with open(tasks_path, "r", encoding="utf-8") as f:
            tasks = json.load(f)
    except Exception:
        return fallback

    for task in tasks:
        if task.get("keyword") == keyword:
            return {
                "keyword": task.get("keyword", keyword),
                "industry": task.get("industry") or fallback["industry"],
                "domain": task.get("domain") or fallback["domain"],
                "url": task.get("url") or "",
            }
    return fallback


# ----------------------------------------------------------------
# 平台 URL 构建 helper
# ----------------------------------------------------------------

def _build_list_url(platform: str, keyword: str, city_id: str, pages: str, test: bool, debug: bool) -> str:
    if platform == "boss":
        params: dict[str, str] = {
            "query": keyword,
            "city": city_id,
            "joblens_auto": "1",
            "joblens_pages": str(pages),
            "joblens_keyword": keyword,
            "joblens_keyword_b64u": _base64url_utf8(keyword),
            "joblens_list_queue": "1",
        }
        if test:
            params["joblens_test"] = "1"
        if debug:
            params["debug"] = "1"
        params["_t"] = str(int(time.time()))
        return f"https://www.zhipin.com/web/geek/jobs?{urlencode(params)}"

    params = {
        "kw": keyword,
        "jl": city_id,
        "cityId": city_id,
        "joblens_city": city_id,
        "joblens_auto": "1",
        "joblens_pages": str(pages),
        "joblens_keyword": keyword,
        "joblens_keyword_b64u": _base64url_utf8(keyword),
        "joblens_list_queue": "1",
    }
    if test:
        params["joblens_test"] = "1"
    if debug:
        params["debug"] = "1"
    return f"https://sou.zhaopin.com/?{urlencode(params)}"


def _build_detail_url(platform: str, job_url: str, keyword: str, debug: bool, save_html: bool, save_json: bool) -> str:
    parsed = urlparse(job_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["detail"] = "1"
    if keyword.strip():
        params["kw"] = keyword.strip()
        params["kw64"] = _base64url_utf8(keyword.strip())
    if debug:
        params["debug"] = "1"
    params["html"] = "1" if save_html else "0"
    params["json"] = "1" if save_json else "0"
    return urlunparse(parsed._replace(query=urlencode(params)))


def _build_menu_url(platform: str, city_id: str, debug: bool) -> str:
    if platform == "boss":
        # BOSS SEO landing pages use city name slugs, not numeric codes
        _BOSS_CITY_SLUG: dict[str, str] = {
            "101020100": "shanghai",
            "101010100": "beijing",
            "101280100": "guangzhou",
            "101280600": "shenzhen",
            "101210100": "hangzhou",
        }
        city_slug = _BOSS_CITY_SLUG.get(city_id, city_id)
        params: dict[str, str] = {"joblens_keyword_discovery": "1", "joblens_city": city_id}
        if debug:
            params["debug"] = "1"
        return f"https://www.zhipin.com/{city_slug}/?{urlencode(params)}"

    params: dict[str, str] = {"jl": city_id, "joblens_keyword_discovery": "1"}
    if debug:
        params["debug"] = "1"
    return f"https://www.zhaopin.com/?{urlencode(params)}"


def _build_platform_wake_url(platform: str, queue_type: str, debug: bool) -> str:
    """queue_type: 'list' 或 'detail'"""
    if platform == "boss":
        params: dict[str, str] = {f"joblens_{queue_type}_queue_wake": "1"}
        if debug:
            params["debug"] = "1"
        return f"https://www.zhipin.com/?{urlencode(params)}"

    params: dict[str, str] = {f"joblens_{queue_type}_queue_wake": "1"}
    if debug:
        params["debug"] = "1"
    return f"https://www.zhaopin.com/?{urlencode(params)}"


def _validate_job_url(job_url: str, platform: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(job_url)
    except Exception:
        return False, "job_url is invalid"
    if parsed.scheme not in {"http", "https"}:
        return False, "job_url must be an http(s) URL"
    if platform == "zhilian" and "zhaopin.com" not in parsed.netloc:
        return False, "zhilian job_url must be a zhaopin.com URL"
    if platform == "boss" and "zhipin.com" not in parsed.netloc:
        return False, "boss job_url must be a zhipin.com URL"
    return True, ""

def _parse_frontmatter(file_path: Path) -> dict[str, str]:
    """从 markdown 文件 YAML frontmatter 中提取简单 key/value 字段。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    frontmatter: dict[str, str] = {}
    for i in range(1, min(len(lines), 30)):
        line = lines[i].strip()
        if line == "---":
            break
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            value = m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            frontmatter[m.group(1).strip()] = value
    return frontmatter

def _parse_frontmatter_keyword(file_path: Path) -> str | None:
    """从 markdown 文件 YAML frontmatter 中提取 keyword 字段。"""
    return _parse_frontmatter(file_path).get("keyword") or None

def _contains_keyword(file_name: str, keyword: str) -> bool:
    normalized_name = file_name.lower()
    normalized_keyword = keyword.lower()
    if normalized_keyword in normalized_name:
        return True
    encoded_keyword = _base64url_utf8(keyword).lower()
    return encoded_keyword and encoded_keyword in normalized_name

def _target_for_joblens_output(file_path: Path, keyword: str, task: dict[str, str], vault_path: Path, platform: str) -> Path | None:
    name = file_path.name
    suffix = file_path.suffix.lower()
    pfx = _platform_task_prefix(platform)
    is_raw = suffix in {".json", ".html"} or "_RAW_" in name or name.startswith(f"{pfx}_RAW_")
    job_dir = _job_category_dir(keyword, task, vault_path)

    if (name.startswith(f"{pfx.lower()}_keyword_discovery_") or name.startswith("zhilian_keyword_discovery_") or name.startswith(f"{pfx}_KEYWORDS_")) and suffix == ".md":
        return POSITIONS_PATH / name

    if name.startswith(f"{pfx}_DETAIL_"):
        if is_raw:
            return job_dir / "raw" / name
        direct_detail_match = re.match(rf"{pfx}_DETAIL_(.+)_\d{{8}}_\d{{6}}\.md$", name)
        if direct_detail_match:
            return job_dir / f"{direct_detail_match.group(1)}.md"
        return job_dir / name

    if name.startswith(f"{pfx}_COMPANY_"):
        if is_raw or "MANIFEST" in name:
            return job_dir / "company" / "raw" / name
        direct_company_match = re.match(rf"{pfx}_COMPANY_(.+)_\d{{8}}_\d{{6}}\.md$", name)
        if direct_company_match:
            return job_dir / "company" / f"{direct_company_match.group(1)}.md"
        return job_dir / "company" / name

    if name.startswith(f"{pfx}_RAW_"):
        return job_dir / "raw" / name

    if name.startswith(f"{pfx}_") and suffix == ".md":
        return job_dir / f"_岗位索引表_{_safe_keyword_dir(keyword)}.md"

    if suffix == ".md":
        return job_dir / name

    return None

def _unique_target_path(target: Path, overwrite: bool = False) -> Path:
    if overwrite or not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

def _launch_zhilian_with_url(collection_url: str, keyword: str, launch_label: str) -> str:
    return _launch_platform_with_url(collection_url, "zhilian", keyword, launch_label)


def _launch_platform_with_url(collection_url: str, platform: str, keyword: str, launch_label: str) -> str:
    chrome_command = [WINDOWS_CHROME_PATH, collection_url]

    result: dict[str, Any] = {
        "ok": False,
        "url": collection_url,
        "chrome_command": chrome_command,
        "expected_download_dir": DOWNLOADS_PATH,
        "launch_label": launch_label,
        "suggested_archive_tool": (
            f'archive_joblens_outputs(keyword="{keyword}", platform="{platform}", since_minutes=60, '
            "dry_run=true, include_test=false)"
        ),
    }

    if not (JOBLENS_DIST_PATH / "manifest.json").exists():
        result["error"] = "Joblens dist/manifest.json not found"
        return _json_response(result)
    if not os.path.exists(WINDOWS_CHROME_PATH):
        result["error"] = "Windows Chrome executable not found"
        return _json_response(result)

    try:
        subprocess.Popen(chrome_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result["ok"] = True
        result["message"] = "Chrome launched with default profile."
    except Exception as exc:
        result["error"] = f"Failed to launch Chrome: {exc}"

    return _json_response(result)

# ----------------------------------------------------------------
# Resources: 暴露本地情报数据
# ----------------------------------------------------------------

@mcp.resource("jobsniper://persona")
def get_persona() -> str:
    """获取当前求职者的动态画像及其技能置信度"""
    if not PERSONA_PATH.exists():
        # 如果文件不存在，返回一个默认骨架
        default_persona = {
            "name": "User",
            "goals": [],
            "skills": {},
            "audit_log": []
        }
        return json.dumps(default_persona, indent=2, ensure_ascii=False)

    with open(PERSONA_PATH, "r", encoding="utf-8") as f:
        return f.read()


@mcp.resource("jobsniper://vault/positions/{platform}/{path_to_job}")
def get_position_detail(platform: str, path_to_job: str) -> str:
    """按自然嵌套路径读取岗位详情 Markdown。"""
    try:
        vault_path = _platform_vault_path(platform)
        relative_path = _safe_relative_path(path_to_job)
    except ValueError as exc:
        return str(exc)

    file_path = vault_path / relative_path
    if file_path.suffix != ".md":
        file_path = file_path.with_suffix(".md")
    try:
        file_path.resolve().relative_to(vault_path.resolve())
    except ValueError:
        return "path_to_job must stay inside the platform vault"

    if not file_path.exists():
        return f"未找到岗位详情文件: {file_path}"
    return _read_text_file(file_path)


# ----------------------------------------------------------------
# Tools: 暴露操作指令
# ----------------------------------------------------------------

@mcp.tool()
def find_job_detail(platform: str, keyword: str, company: str | None = None, limit: int = 5) -> str:
    """
    在自然嵌套岗位库中按文件名搜索岗位详情。
    参数:
    - platform: zhilian 或 boss
    - keyword: 岗位名或文件名关键词
    - company: 可选公司名关键词
    - limit: 最多返回的匹配数量
    """
    try:
        vault_path = _platform_vault_path(platform)
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc)})

    if limit <= 0:
        return _json_response({"ok": False, "error": "limit must be greater than 0"})

    matches = _find_job_files(vault_path, keyword, company)[:limit]
    return _json_response({
        "ok": True,
        "platform": platform,
        "keyword": keyword,
        "company": company,
        "count": len(matches),
        "matches": [
            {
                "path": str(path),
                "relative_path": str(path.relative_to(vault_path)),
                "resource_uri": f"jobsniper://vault/positions/{platform}/{path.relative_to(vault_path)}",
            }
            for path in matches
        ],
    })

@mcp.tool()
def launch_job_list_collection(
    platform: str = "zhilian",
    keyword: str = "",
    city_id: str = "538",
    pages: str = "auto",
    test: bool = False,
    debug: bool = True,
    wake_browser: bool = False,
) -> str:
    """
    采集某个职业关键词下的岗位列表。通过写入任务文件，由 Chrome 扩展后台采集。
    参数:
    - platform: zhilian 或 boss
    - keyword: 岗位关键词
    - city_id: 城市 ID (zhilian: 538=上海, boss: 101020100=上海)
    - pages: auto 或指定页码数
    - test: 测试模式（仅采集少量页面）
    - debug: 调试模式
    - wake_browser: 是否唤醒浏览器
    """
    platform = platform.strip().lower()
    if platform not in ("zhilian", "boss"):
        return _json_response({"ok": False, "error": "platform must be zhilian or boss"})
    if not keyword.strip():
        return _json_response({"ok": False, "error": "keyword must not be empty"})

    _start_list_monitor_if_needed()
    collection_url = _build_list_url(platform, keyword, city_id, pages, test, debug)

    task_file = _platform_task_file(platform, "list_tasks")
    task_id = hashlib.sha1(collection_url.encode("utf-8")).hexdigest()[:16]
    task_line = json.dumps({"task_id": task_id, "url": collection_url, "keyword": keyword.strip()}) + "\n"
    try:
        with open(task_file, "a", encoding="utf-8") as f:
            f.write(task_line)
        wake_url = None
        chrome_launched = False
        chrome_error = None
        wake_debounced = False
        if wake_browser:
            wake_url = _build_platform_wake_url(platform, "list", debug)
            chrome_launched, chrome_error, wake_debounced = _launch_list_queue_wake(wake_url)
        return _json_response({
            "ok": True,
            "platform": platform,
            "task_id": task_id,
            "url": collection_url,
            "task_file": str(task_file),
            "wake_url": wake_url,
            "chrome_launched": chrome_launched,
            "chrome_error": chrome_error,
            "wake_debounced": wake_debounced,
            "message": "Task enqueued. Chrome extension alarm polling will process it in background.",
        })
    except Exception as exc:
        return _json_response({"ok": False, "error": f"Failed to write task file: {exc}"})


@mcp.tool()
def launch_job_menu_collection(
    platform: str = "zhilian",
    city_id: str = "538",
    debug: bool = True,
) -> str:
    """
    采集平台 job menu，提取行业-职能-职业三级结构。
    参数:
    - platform: zhilian 或 boss
    - city_id: 城市 ID
    - debug: 调试模式
    """
    platform = platform.strip().lower()
    if platform not in ("zhilian", "boss"):
        return _json_response({"ok": False, "error": "platform must be zhilian or boss"})

    collection_url = _build_menu_url(platform, city_id, debug)
    launch_label = f"{platform}_job_menu"
    return _launch_platform_with_url(collection_url, platform, "job_menu", launch_label)


@mcp.tool()
def launch_job_detail_collection(
    platform: str = "zhilian",
    job_url: str = "",
    keyword: str = "",
    debug: bool = True,
    save_html: bool = False,
    save_json: bool = False,
    wake_browser: bool = False,
) -> str:
    """
    采集单个岗位详情页。通过写入任务文件，由 Chrome 扩展后台静默采集。
    参数:
    - platform: zhilian 或 boss
    - job_url: 岗位详情页完整 URL
    - keyword: 岗位关键词
    - debug: 调试模式
    - save_html: 保存原始 HTML
    - save_json: 保存原始 JSON
    - wake_browser: 唤醒浏览器
    """
    platform = platform.strip().lower()
    if platform not in ("zhilian", "boss"):
        return _json_response({"ok": False, "error": "platform must be zhilian or boss"})
    if not job_url.strip():
        return _json_response({"ok": False, "error": "job_url must not be empty"})

    is_valid, error_msg = _validate_job_url(job_url, platform)
    if not is_valid:
        return _json_response({"ok": False, "error": error_msg})

    _start_monitor_if_needed()

    detail_url = _build_detail_url(platform, job_url, keyword, debug, save_html, save_json)
    wake_url = None
    if wake_browser:
        wake_url = _build_platform_wake_url(platform, "detail", debug)

    task_file = _platform_task_file(platform, "detail_tasks")
    task_line = json.dumps({"url": detail_url, "keyword": keyword.strip() or "job_detail"}) + "\n"
    try:
        with open(task_file, "a", encoding="utf-8") as f:
            f.write(task_line)
        chrome_launched = False
        chrome_error = None
        wake_debounced = False
        if wake_url:
            chrome_launched, chrome_error, wake_debounced = _launch_detail_queue_wake(wake_url)
        return _json_response({
            "ok": True,
            "platform": platform,
            "url": detail_url,
            "task_file": str(task_file),
            "wake_url": wake_url,
            "chrome_launched": chrome_launched,
            "chrome_error": chrome_error,
            "wake_debounced": wake_debounced,
            "message": "Task enqueued. Chrome extension alarm polling will process it in background.",
        })
    except Exception as exc:
        return _json_response({"ok": False, "error": f"Failed to write task file: {exc}"})


@mcp.tool()
def archive_joblens_outputs(
    keyword: str,
    platform: str = "zhilian",
    since_minutes: int = 60,
    dry_run: bool = False,
    include_test: bool = False,
) -> str:
    """
    将 D:\\Downloads 中的 Joblens 输出归档到 storage_layer/positions/{platform}_intelligence_vault。
    - platform=zhilian → storage_layer/positions/zhilian_intelligence_vault
    - platform=boss    → storage_layer/positions/boss_intelligence_vault
    参数:
    - platform: zhilian 或 boss
    """
    if not keyword.strip():
        return _json_response({"ok": False, "error": "keyword must not be empty"})
    if since_minutes <= 0:
        return _json_response({"ok": False, "error": "since_minutes must be greater than 0"})

    try:
        vault_path = _platform_vault_path(platform)
    except ValueError as exc:
        return _json_response({"ok": False, "error": str(exc)})

    downloads = Path(DOWNLOADS_PATH)
    cutoff = datetime.now() - timedelta(minutes=since_minutes)
    task = _load_platform_task(platform, keyword)
    pfx = _platform_task_prefix(platform)
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    if not downloads.exists():
        return _json_response({"ok": False, "error": f"downloads path not found: {DOWNLOADS_PATH}"})

    discovery_pattern = "zhilian_keyword_discovery_*.md" if platform == "zhilian" else "boss_keyword_discovery_*.md"
    candidates = {
        path
        for pattern in (f"{pfx}_*", discovery_pattern)
        for path in downloads.glob(pattern)
    }
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
        if file_path.name.startswith((f"{pfx}_DETAIL_RAW_", f"{pfx}_DETAIL_MANIFEST_", f"{pfx}_COMPANY_MANIFEST_", f"{pfx}_RAW_")):
            skipped.append({"file": str(file_path), "reason": "raw or manifest file"})
            continue

        # For detail and company files, try to read keyword/status from YAML frontmatter.
        is_detail = file_path.name.startswith(f"{pfx}_DETAIL_") and not file_path.name.startswith((f"{pfx}_DETAIL_RAW_", f"{pfx}_DETAIL_MANIFEST_"))
        is_company = file_path.name.startswith(f"{pfx}_COMPANY_") and not file_path.name.startswith(f"{pfx}_COMPANY_MANIFEST_")
        frontmatter = _parse_frontmatter(file_path) if ((is_detail or is_company) and file_path.suffix.lower() == ".md") else {}
        frontmatter_keyword = frontmatter.get("keyword") or None

        if (
            not file_path.name.startswith((f"{pfx}_KEYWORDS_", f"{pfx}_DETAIL_RAW_", f"{pfx}_DETAIL_MANIFEST_", f"{pfx}_COMPANY_"))
            and not file_path.name.startswith(f"{pfx.lower()}_keyword_discovery_")
            and not file_path.name.startswith("zhilian_keyword_discovery_")
            and not re.match(rf"{pfx}_DETAIL_.+_\d{{8}}_\d{{6}}\.md$", file_path.name)
            and not _contains_keyword(file_path.name, keyword)
        ):
            skipped.append({"file": str(file_path), "reason": "keyword mismatch"})
            continue

        file_task = _load_platform_task(platform, frontmatter_keyword) if frontmatter_keyword else task
        file_keyword = frontmatter_keyword if frontmatter_keyword else keyword
        target = _target_for_joblens_output(file_path, file_keyword, file_task, vault_path, platform)
        if target is None:
            skipped.append({"file": str(file_path), "reason": "unrecognized Joblens output pattern"})
            continue
        is_index = target.stem.startswith("_岗位索引表") or target.stem.startswith("_关键词发现结果")
        final_target = _unique_target_path(target, overwrite=is_index)
        planned_item = {
            "source": str(file_path),
            "target": str(final_target),
            "modified": modified.isoformat(timespec="seconds"),
        }
        if is_detail and frontmatter.get("recruitment_status"):
            planned_item["recruitment_status"] = frontmatter.get("recruitment_status")
            planned_item["recruitment_status_label"] = frontmatter.get("recruitment_status_label", "")
            planned_item["status_checked_at"] = frontmatter.get("status_checked_at", "")
        planned.append(planned_item)

    moved: list[dict[str, str]] = []
    if not dry_run:
        for item in planned:
            source = Path(item["source"])
            target = Path(item["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moved.append({"source": str(source), "target": str(target)})

    return _json_response({
        "ok": True,
        "dry_run": dry_run,
        "platform": platform,
        "keyword": keyword,
        "task": task,
        "since_minutes": since_minutes,
        "include_test": include_test,
        "planned_count": len(planned),
        "moved_count": len(moved),
        "planned": planned,
        "moved": moved,
        "skipped_count": len(skipped),
        "skipped": skipped,
    })

@mcp.tool()
def update_persona(skill_name: str, confidence_score: int, reasoning: str) -> str:
    """
    更新用户画像中的技能置信度。
    参数:
    - skill_name: 技能名称 (如 'Python', 'RAG')
    - confidence_score: 调整后的分值 (0-100)
    - reasoning: 调整原因
    """
    # 简单的持久化逻辑
    data = {}
    if PERSONA_PATH.exists():
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    
    if "skills" not in data: data["skills"] = {}
    data["skills"][skill_name] = {
        "score": confidence_score,
        "last_audit_reason": reasoning
    }
    
    # 确保目录存在
    PERSONA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PERSONA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    return f"[Spotter] 画像已更新：{skill_name} 置信度 -> {confidence_score}。原因：{reasoning}"

async def _run_stdio_transport() -> None:
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)
    stdin_queue: queue.Queue[SessionMessage | Exception | None] = queue.Queue()

    def stdin_reader() -> None:
        try:
            while True:
                line = sys.stdin.readline()
                if line == "":
                    stdin_queue.put(None)
                    return
                try:
                    message = types.JSONRPCMessage.model_validate_json(line)
                except Exception as exc:
                    stdin_queue.put(exc)
                    continue
                stdin_queue.put(SessionMessage(message))
        except Exception as exc:
            stdin_queue.put(exc)
        finally:
            stdin_queue.put(None)

    async def queue_pump() -> None:
        while True:
            try:
                item = stdin_queue.get_nowait()
            except queue.Empty:
                await anyio.sleep(0.01)
                continue
            if item is None:
                break
            await read_stream_writer.send(item)

    async def stdout_pump() -> None:
        async with write_stream_reader:
            async for session_message in write_stream_reader:
                payload = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                sys.stdout.write(payload + "\n")
                sys.stdout.flush()

    reader = threading.Thread(target=stdin_reader, daemon=True)
    reader.start()

    async with read_stream_writer, write_stream:
        async with anyio.create_task_group() as tg:
            tg.start_soon(queue_pump)
            tg.start_soon(stdout_pump)
            await mcp._mcp_server.run(
                read_stream,
                write_stream,
                mcp._mcp_server.create_initialization_options(),
            )

if __name__ == "__main__":
    anyio.run(_run_stdio_transport)
