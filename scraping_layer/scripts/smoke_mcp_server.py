#!/usr/bin/env python3
"""JobSniper MCP 冒烟测试（可移植版 / P1）。

设计约束（对应 docs/DEV_LOG.md 的 P1 阶段与 Issue #4 验收第 6 条）：

1. 不依赖 ``D:\\Downloads``、WSL 路径、仓库内私有岗位数据、persona、Chrome 或网络。
   因此可在任意机器与 GitHub Windows runner 上运行。
2. 所有数据都是临时目录里的**合成夹具**，通过 ``JOBSNIPER_STORAGE_ROOT`` /
   ``JOBSNIPER_DOWNLOADS_PATH`` 环境变量注入。被测代码路径与生产完全一致，
   不再 monkeypatch 模块全局变量（旧写法跨进程失效，且绿灯无法证明配置可用）。
3. import 段与 stdio 段使用**两个相互独立的夹具根目录**，因此归档写入不会
   污染协议段，运行顺序不影响结果。
4. 若环境变量未生效（例如 D1 被移除），测试会**主动中止**，绝不在真实
   ``storage_layer`` 或真实下载目录上执行。

已知红灯（预期失败，作为缺陷证据，不是测试自身的问题）：
  - R1：Windows 管道下 stdio 传输层编码为 GBK，服务端含中文 docstring 的
    响应无法被 UTF-8 客户端解码，传输层在 ``list_tools`` 即死亡。
    本脚本的 stdio 段**刻意不设置** ``PYTHONUTF8`` / ``PYTHONIOENCODING``，
    以断言「代码级 UTF-8 修复」这一需求。P2 修复后该段应转为绿灯。
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = PROJECT_ROOT / "mcp_server.py"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 合成夹具常量（纯占位数据，不含任何真实 persona / 岗位 / 公司信息）
# ---------------------------------------------------------------------------
KW = "测试岗位"
INDUSTRY = "测试行业"
DOMAIN = "测试领域"
COMPANY = "合成测试公司"
ARCHIVE_COMPANY = "归档测试公司"
DETAIL_MARKER = "SMOKE_BODY_MARKER"
PERSONA_SKILL = "合成技能"

ENV_STORAGE = "JOBSNIPER_STORAGE_ROOT"
ENV_DOWNLOADS = "JOBSNIPER_DOWNLOADS_PATH"

_TEMP_ROOTS: list[Path] = []


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _under(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _make_fixture_root(name: str) -> dict[str, Path]:
    """创建一个独立的合成 storage_root + downloads 目录。"""
    root = Path(tempfile.mkdtemp(prefix=f"jobsniper_smoke_{name}_"))
    _TEMP_ROOTS.append(root)

    storage = root / "storage"
    positions = storage / "positions"
    vault = positions / "zhilian_intelligence_vault"
    boss_vault = positions / "boss_intelligence_vault"
    personas = storage / "personas"
    downloads = root / "downloads"
    for directory in (vault, boss_vault, personas, downloads):
        directory.mkdir(parents=True, exist_ok=True)

    persona = {
        "name": "合成用户",
        "goals": ["合成目标"],
        "skills": {PERSONA_SKILL: {"score": 60, "last_audit_reason": "夹具初始化"}},
        "audit_log": [],
    }
    (personas / "current_user.json").write_text(
        json.dumps(persona, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    tasks = [{"keyword": KW, "industry": INDUSTRY, "domain": DOMAIN, "url": ""}]
    for filename in ("zhilian_master_tasks.json", "boss_master_tasks.json"):
        (positions / filename).write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    job_dir = vault / INDUSTRY / DOMAIN / KW
    job_dir.mkdir(parents=True, exist_ok=True)
    detail_body = (
        "---\n"
        f"keyword: {KW}\n"
        f"company: {COMPANY}\n"
        "recruitment_status: open\n"
        "---\n\n"
        f"# {COMPANY} - {KW}\n\n"
        f"{DETAIL_MARKER}\n"
    )
    (job_dir / f"{COMPANY}_{KW}.md").write_text(detail_body, encoding="utf-8")

    return {
        "root": root,
        "storage": storage,
        "positions": positions,
        "vault": vault,
        "boss_vault": boss_vault,
        "personas": personas,
        "downloads": downloads,
        "job_dir": job_dir,
    }


def _apply_env(paths: dict[str, Path], extra: dict[str, str] | None = None) -> dict[str, str]:
    """把夹具路径写入环境变量并返回完整 env（供子进程使用）。"""
    values = {ENV_STORAGE: str(paths["storage"]), ENV_DOWNLOADS: str(paths["downloads"])}
    if extra:
        values.update(extra)
    os.environ.update(values)
    return values


def _guardrail(ms, paths: dict[str, Path]) -> None:
    """确认被测模块解析出的全部路径都落在临时夹具内，否则拒绝运行。"""
    root = paths["root"]
    checked = {
        "STORAGE_PATH": Path(ms.STORAGE_PATH),
        "POSITIONS_PATH": Path(ms.POSITIONS_PATH),
        "VAULT_PATH": Path(ms.VAULT_PATH),
        "BOSS_VAULT_PATH": Path(ms.BOSS_VAULT_PATH),
        "PERSONA_PATH": Path(ms.PERSONA_PATH),
        "TASKS_PATH": Path(ms.TASKS_PATH),
        "BOSS_TASKS_PATH": Path(ms.BOSS_TASKS_PATH),
        "DOWNLOADS_PATH": Path(ms.DOWNLOADS_PATH),
    }
    for label, value in checked.items():
        _assert(
            _under(value, root),
            f"{label} 解析为 {value}，未指向临时夹具 {root}；"
            f"拒绝在真实数据上运行测试（检查 {ENV_STORAGE} / {ENV_DOWNLOADS} 是否生效）",
        )


def _write_transport_files(paths: dict[str, Path]) -> dict[str, str]:
    """在临时 downloads 中生成三类 Joblens 传输产物，返回预期归档目标。"""
    downloads = paths["downloads"]
    discovery = downloads / "zhilian_keyword_discovery_20260101_031600.md"
    discovery.write_text("# discovery\n", encoding="utf-8")
    detail = downloads / f"ZHILIAN_DETAIL_{ARCHIVE_COMPANY}_{KW}_20260101_120000.md"
    detail.write_text(
        "---\n"
        f"keyword: {KW}\n"
        f"company: {ARCHIVE_COMPANY}\n"
        "recruitment_status: open\n"
        "---\n\n"
        f"# {ARCHIVE_COMPANY} - {KW}\n\n"
        f"{DETAIL_MARKER}\n",
        encoding="utf-8",
    )
    index = downloads / f"ZHILIAN_{KW}_20260101_130000.md"
    index.write_text("# 列表\n", encoding="utf-8")
    return {
        "discovery": str(paths["positions"] / discovery.name),
        "detail": str(paths["job_dir"] / f"{ARCHIVE_COMPANY}_{KW}.md"),
        "index": str(paths["job_dir"] / f"_岗位索引表_{KW}.md"),
    }


# ---------------------------------------------------------------------------
# import 段
# ---------------------------------------------------------------------------

def run_import_smoke(paths: dict[str, Path]) -> None:
    import mcp_server as ms

    _guardrail(ms, paths)

    # 1) persona 资源
    persona = json.loads(ms.get_persona())
    _assert("skills" in persona, "persona 资源应包含 skills 字段")
    _assert(PERSONA_SKILL in persona["skills"], "persona 应读回合成技能（中文键名）")

    # 2) 岗位详情资源：修 N1（旧断言把「未找到岗位详情文件: <含公司名的路径>」当成正文，
    #    文件缺失时也会假通过）。这里先校验文件真实存在，再校验正文特征。
    job_path = paths["job_dir"] / f"{COMPANY}_{KW}.md"
    _assert(job_path.exists(), "夹具岗位文件必须真实存在")
    relative_path = str(job_path.relative_to(paths["vault"]))
    detail = ms.get_position_detail("zhilian", relative_path)
    _assert("未找到岗位详情文件" not in detail, f"N1 假通过场景：读取返回未找到：{detail[:120]}")
    _assert(DETAIL_MARKER in detail, "get_position_detail 应返回岗位正文内容")

    # 3) 路径穿越防护：模块里有两处消息（_safe_relative_path 的
    #    "must be a relative path inside the platform vault" 与 resolve 校验的
    #    "must stay inside the platform vault"），断言两者共有的子串。
    for attempt in ("../boss_intelligence_vault/x.md", "..\\x.md", "a/../../x.md"):
        escape = ms.get_position_detail("zhilian", attempt)
        _assert(
            "inside the platform vault" in escape,
            f"vault 外的相对路径应被拒绝：{attempt!r} -> {escape!r}",
        )
    # 当前实现会剥离前导 /，将 /etc/passwd 解释为 vault 内的 etc/passwd.md。
    # 精确校验返回的完整目标路径，而非仅检查返回值里没有正文 marker。
    expected_missing = paths["vault"] / "etc" / "passwd.md"
    _assert(_under(expected_missing, paths["vault"]), "预期目标必须位于 vault 内")
    absolute_result = ms.get_position_detail("zhilian", "/etc/passwd")
    _assert(
        absolute_result == f"未找到岗位详情文件: {expected_missing}",
        f"前导斜杠路径应解析到 vault 内的目标：{absolute_result!r}",
    )

    # 4) find_job_detail：中文关键词 + 中文公司名
    search = json.loads(ms.find_job_detail("zhilian", KW, COMPANY))
    _assert(search["ok"] is True, "find_job_detail 应成功")
    _assert(search["count"] == 1, f"find_job_detail 应命中 1 条，实际 {search['count']}")
    _assert(search["keyword"] == KW, "中文 keyword 应原样回显")
    _assert(search["company"] == COMPANY, "中文 company 应原样回显")
    first = search["matches"][0]
    _assert(first["relative_path"].replace("\\", "/") == relative_path.replace("\\", "/"),
            "match 的 relative_path 应与夹具路径一致")
    _assert(first["resource_uri"].startswith(f"jobsniper://vault/positions/zhilian/"),
            "match 应带可读取的 resource_uri")

    # 5) 未知平台报错走 JSON 而非异常
    bad = json.loads(ms.find_job_detail("unknown_platform", KW))
    _assert(bad["ok"] is False, "未知 platform 应返回 ok=false")

    # 6) 归档路由（纯函数）：discovery / detail / index 三类
    task = ms._load_platform_task("zhilian", KW)
    pfx = "ZHILIAN"
    discovery_target = ms._target_for_joblens_output(
        Path(f"/mnt/d/Downloads/zhilian_keyword_discovery_20260504_024700.md"),
        KW, task, ms.VAULT_PATH, "zhilian",
    )
    _assert(discovery_target is not None, "keyword discovery 应解析出目标")
    _assert(discovery_target.parent == ms.POSITIONS_PATH, "discovery 应归档到 positions 根目录")
    _assert(discovery_target.name == "zhilian_keyword_discovery_20260504_024700.md",
            "discovery 文件名应保留")
    detail_target = ms._target_for_joblens_output(
        Path(f"/mnt/d/Downloads/{pfx}_DETAIL_{COMPANY}_{KW}_20260504_031500.md"),
        KW, task, ms.VAULT_PATH, "zhilian",
    )
    _assert(detail_target is not None, "detail 应解析出目标")
    _assert(detail_target.name == f"{COMPANY}_{KW}.md", "detail 归档应剥离传输前缀")
    index_target = ms._target_for_joblens_output(
        Path(f"/mnt/d/Downloads/{pfx}_{KW}_20260504_031500.md"),
        KW, task, ms.VAULT_PATH, "zhilian",
    )
    _assert(index_target is not None, "列表文件应解析出索引表目标")
    _assert(index_target.name.startswith("_岗位索引表_"), "列表文件应路由到岗位索引表")

    # 7) 归档工具：先 dry_run 断言「不写入」，再真实归档断言幂等
    expected = _write_transport_files(paths)
    before_download = sorted(p.name for p in paths["downloads"].iterdir())
    before_vault = sorted(p.relative_to(paths["vault"]).as_posix() for p in paths["vault"].rglob("*") if p.is_file())

    dry = json.loads(ms.archive_joblens_outputs(KW, platform="zhilian", since_minutes=60, dry_run=True))
    _assert(dry["ok"] is True, "归档 dry-run 应成功")
    _assert(dry["planned_count"] == 3, f"dry-run 应计划 3 个文件，实际 {dry['planned_count']}")
    _assert(dry["moved_count"] == 0, "dry-run 不应移动文件")
    after_download = sorted(p.name for p in paths["downloads"].iterdir())
    after_vault = sorted(p.relative_to(paths["vault"]).as_posix() for p in paths["vault"].rglob("*") if p.is_file())
    _assert(after_download == before_download, "dry-run 不应改动 downloads 目录")
    _assert(after_vault == before_vault, "dry-run 不应写入 vault")

    real = json.loads(ms.archive_joblens_outputs(KW, platform="zhilian", since_minutes=60, dry_run=False))
    _assert(real["ok"] is True, "真实归档应成功")
    _assert(real["moved_count"] == 3, f"应移动 3 个文件，实际 {real['moved_count']}")
    for key in ("discovery", "detail", "index"):
        _assert(Path(expected[key]).exists(), f"归档目标应存在：{key} -> {expected[key]}")
    _assert(not (paths["downloads"] / f"ZHILIAN_DETAIL_{ARCHIVE_COMPANY}_{KW}_20260101_120000.md").exists(),
            "归档后源文件应被移走")

    again = json.loads(ms.archive_joblens_outputs(KW, platform="zhilian", since_minutes=60, dry_run=True))
    _assert(again["planned_count"] == 0, f"重复运行不应再计划文件，实际 {again['planned_count']}（不重复归档）")

    # 8) update_persona 写回临时 persona
    msg = ms.update_persona(PERSONA_SKILL, 75, "冒烟测试")
    _assert(PERSONA_SKILL in msg, "update_persona 返回应含技能名")
    updated = json.loads((paths["personas"] / "current_user.json").read_text(encoding="utf-8"))
    _assert(updated["skills"][PERSONA_SKILL]["score"] == 75, "update_persona 应持久化分值")

    print("import smoke passed")


# ---------------------------------------------------------------------------
# stdio 段
# ---------------------------------------------------------------------------

def _unwrap(exc: BaseException) -> str:
    seen: list[str] = []
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        seen.append(f"{type(current).__name__}: {str(current)[:200]}")
        for attr in ("exceptions", "__cause__", "__context__"):
            value = getattr(current, attr, None)
            if isinstance(value, BaseException):
                stack.append(value)
            elif isinstance(value, (list, tuple)):
                stack.extend([item for item in value if isinstance(item, BaseException)])
    return " | ".join(seen)


def _child_env(paths: dict[str, Path]) -> dict[str, str]:
    """构造子进程环境：给出夹具路径，但**刻意不提供**任何编码修复变量。

    这样 stdio 段断言的正是「代码自带 UTF-8」这一需求（R1），而非靠环境变量掩盖。
    """
    env = dict(os.environ)
    for key in ("PYTHONUTF8", "PYTHONIOENCODING"):
        env.pop(key, None)
    env[ENV_STORAGE] = str(paths["storage"])
    env[ENV_DOWNLOADS] = str(paths["downloads"])
    env.setdefault("SYSTEMROOT", os.environ.get("SYSTEMROOT", "C:\\Windows"))
    return env


async def run_stdio_smoke(timeout_seconds: float) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # 协议段使用独立夹具，避免 import 段的归档写入影响命中数
    paths = _make_fixture_root("stdio")
    env = _child_env(paths)

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        env=env,
    )

    async def _call(session: ClientSession, name: str, arguments: dict) -> dict:
        result = await asyncio.wait_for(session.call_tool(name, arguments), timeout=timeout_seconds)
        text = "".join(getattr(block, "text", "") for block in result.content)
        return json.loads(text)

    async def _run() -> None:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout_seconds)

                tools = await asyncio.wait_for(session.list_tools(), timeout=timeout_seconds)
                tool_names = {tool.name for tool in tools.tools}
                _assert(len(tool_names) == 6, f"应暴露恰好 6 个工具，实际 {len(tool_names)}")
                _assert("find_job_detail" in tool_names, "应包含 find_job_detail")
                _assert("launch_job_list_collection" in tool_names, "应包含统一列表采集工具")
                _assert("launch_job_menu_collection" in tool_names, "应包含菜单采集工具")
                _assert("launch_job_detail_collection" in tool_names, "应包含详情采集工具")
                _assert("archive_joblens_outputs" in tool_names, "应包含归档工具")
                for deprecated in (
                    "launch_zhilian_job_list_collection",
                    "launch_zhilian_collection",
                    "launch_zhilian_keyword_discovery",
                    "trigger_clipper",
                ):
                    _assert(deprecated not in tool_names, f"不应暴露已废弃工具 {deprecated}")

                resources = await asyncio.wait_for(session.list_resources(), timeout=timeout_seconds)
                resource_uris = {str(resource.uri) for resource in resources.resources}
                _assert("jobsniper://persona" in resource_uris, "资源列表应包含 persona")

                # R1 核心断言：中文入参 + 中文回显必须逐码位往返
                search = await _call(session, "find_job_detail", {"platform": "zhilian", "keyword": KW})
                _assert(search["ok"] is True, "find_job_detail 应成功")
                _assert(search["count"] == 1,
                        f"应命中 1 条（命中数为 0 说明子进程未使用夹具，命中 >1 说明夹具被污染），实际 {search['count']}")
                _assert(search["keyword"] == KW,
                        f"中文 keyword 往返损坏：期望 {[hex(ord(c)) for c in KW]}，实际 {[hex(ord(c)) for c in str(search['keyword'])]}")
                echoed = search["matches"][0]["relative_path"]
                _assert(COMPANY in echoed and KW in echoed, f"中文路径往返损坏：{echoed}")

                detail = await asyncio.wait_for(
                    session.read_resource("jobsniper://persona"), timeout=timeout_seconds
                )
                persona_text = "".join(getattr(item, "text", "") for item in detail.contents)
                _assert(PERSONA_SKILL in persona_text, "persona 资源应含中文技能名（往返不损坏）")

    try:
        await _run()
    except BaseException as exc:
        chain = _unwrap(exc)
        hint = ""
        if "UnicodeDecodeError" in chain or "UnicodeEncodeError" in chain:
            hint = (
                "\n>>> 这是已知缺陷 R1：Windows 管道下 sys.stdin/sys.stdout 默认按本地编码（GBK/cp936）"
                "解帧，服务端含中文的工具描述与返回值无法被 UTF-8 客户端解码，MCP 传输层在 list_tools "
                "即死亡。修复位置：mcp_server.py::_run_stdio_transport（需用 TextIOWrapper 强制 utf-8）。"
            )
        raise AssertionError(f"stdio smoke failed: {chain}{hint}") from None
    finally:
        shutil.rmtree(paths["root"], ignore_errors=True)
        if paths["root"] in _TEMP_ROOTS:
            _TEMP_ROOTS.remove(paths["root"])

    print("stdio smoke passed")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test JobSniper MCP server behavior.")
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Also run the protocol-level stdio MCP client smoke test.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    paths = _make_fixture_root("import")
    _apply_env(paths)
    exit_code = 0
    try:
        run_import_smoke(paths)
        if args.stdio:
            asyncio.run(run_stdio_smoke(args.timeout))
    except AssertionError as exc:
        print(f"smoke failed: AssertionError: {exc}", file=sys.stderr)
        exit_code = 1
    except Exception as exc:
        print(f"smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        for key in (ENV_STORAGE, ENV_DOWNLOADS):
            os.environ.pop(key, None)
        for root in list(_TEMP_ROOTS):
            shutil.rmtree(root, ignore_errors=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
