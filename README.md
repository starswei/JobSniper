# JobSniper

JobSniper 是一个面向本地求职情报工作的 MCP Server。它把招聘平台采集、岗位知识库、用户画像和会话产物组织在同一个本地工作区里，让 Codex、Claude Desktop 等 MCP Client 可以通过统一工具读取资料、启动采集、归档岗位数据和更新画像。

当前重点支持智联招聘（Zhilian）的招聘情报工作流：平台岗位菜单发现、职业关键词岗位列表采集、单岗位详情页采集、Downloads 产物归档、岗位详情检索和用户画像维护。

## 能力边界

已实现：

- FastMCP stdio 服务入口：`mcp_server.py`
- MCP Resource：读取当前用户画像
- MCP Resource：按自然嵌套路径读取岗位详情 Markdown
- MCP Tool：搜索岗位详情文件
- MCP Tool：采集 job menu（行业-职能-职业三级结构），支持智联招聘
- MCP Tool：采集 job list（某个职业关键词下的岗位列表），支持智联招聘与 BOSS 直聘
- MCP Tool：采集 job detail（岗位详情页），支持智联招聘与 BOSS 直聘；BOSS 详情与公司信息合并为单一 Markdown 归档
- MCP Tool：统一 `platform` 参数（`zhilian` / `boss`），各采集入口共用同一套工具签名
- MCP Tool：归档 `D:\Downloads` 中的 Joblens 采集产物
- MCP Tool：更新用户画像技能置信度
- Joblens Chrome 扩展集成：`scraping_layer/joblens`
- 队列式后台采集：`zhilian_detail_tasks.jsonl` / `zhilian_list_tasks.jsonl`
- 监视脚本：根据 results JSONL 判断完成、失败、重试和归档

仍在演进：

- 更多招聘平台接入
- 更完整的推荐报告和简历生成流水线
- Windows/WSL 权限差异下的归档移动策略
- 本地路径配置化（`DOWNLOADS_PATH` / `WINDOWS_CHROME_PATH`）

## 目录结构

```text
JobSniper/
  mcp_server.py                       # FastMCP server
  requirements.txt                    # Python dependency pin
  scraping_layer/
    scripts/
      archive_outputs.py              # Standalone archive helper
      parse_queue_results.py          # Queue task/results parser
      smoke_mcp_server.py             # Import + stdio smoke tests
    joblens/                          # Chrome extension integration
      src/
      dist/
      package.json
  docs/
    CODING_GUIDELINES.md              # Storage and naming rules
    DEV_LOG.md
  storage_layer/
    personas/
      current_user.json               # Current candidate persona
    positions/
      zhilian_master_tasks.json       # Keyword -> industry/domain mapping
      zhilian_intelligence_vault/     # Zhilian job intelligence vault
      boss_intelligence_vault/        # Reserved for BOSS
  session_layer/                      # Reports, resumes, meeting notes
```

## 数据模型

`storage_layer/positions` 按平台分库，每个平台库采用自然嵌套结构：

```text
storage_layer/positions/
  zhilian_intelligence_vault/
    _行业索引表_智联招聘.md
    教育培训/
      _职能索引表_教育培训.md
      IT培训/
        _职业索引表_IT培训.md
        人工智能讲师/
          _岗位索引表_人工智能讲师.md
          上海某公司_人工智能讲师.md
```

核心概念：

- **平台索引表**：平台知识库内部的导航入口，例如 `_行业索引表_智联招聘.md`。
- **职业岗位索引表**：某个职业关键词下的岗位列表归档，例如 `_岗位索引表_人工智能讲师.md`。
- **岗位详情页**：最终叶子文件，命名为 `{公司名称}_{岗位名称}.md`。
- **关键词发现产物**：平台 job menu 发现结果，命名为 `{platform}_keyword_discovery_{timestamp}.md`，存放在 `storage_layer/positions/` 根目录；它不是平台索引表。

详细命名规则见 [docs/CODING_GUIDELINES.md](docs/CODING_GUIDELINES.md)。

## MCP 接入

安装 Python 依赖：

```bash
cd /path/to/JobSniper
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

MCP Client 配置示例：

```json
{
  "mcpServers": {
    "jobsniper": {
      "command": "/path/to/JobSniper/venv/bin/python",
      "args": ["/path/to/JobSniper/mcp_server.py"],
      "cwd": "/path/to/JobSniper"
    }
  }
}
```

协议级 smoke test：

```bash
cd /path/to/JobSniper
venv/bin/python scraping_layer/scripts/smoke_mcp_server.py --stdio
```

期望结果：客户端可以完成 `initialize`、`list_tools` 和 `list_resources`，并看到 6 个工具、1 个资源。

## MCP Resources

### `jobsniper://persona`

读取当前用户画像：

```text
storage_layer/personas/current_user.json
```

如果画像文件不存在，服务返回默认空画像骨架。

### `jobsniper://vault/positions/{platform}/{path_to_job}`

按自然嵌套路径读取岗位详情 Markdown。

示例：

```text
jobsniper://vault/positions/zhilian/产品/互联网产品经理/AI产品经理/上海倍通医药科技咨询有限公司_AI产品经理.md
```

## MCP Tools

### `find_job_detail`

在岗位知识库中按文件名搜索岗位详情。

参数：

- `platform`: `zhilian` 或 `boss`
- `keyword`: 岗位名或文件名关键词
- `company`: 可选公司名关键词
- `limit`: 返回数量上限

返回匹配文件的绝对路径、相对路径和 MCP Resource URI。

### `launch_zhilian_job_menu_collection`

采集智联平台 job menu，也就是行业-职能-职业三级岗位体系。

行为：

- 打开智联首页
- 附加 `joblens_keyword_discovery=1`
- 由 Joblens 扩展导出关键词发现 Markdown

产物命名：

```text
zhilian_keyword_discovery_{timestamp}.md
```

归档位置：

```text
storage_layer/positions/
```

### `launch_zhilian_job_list_collection`

采集某个职业关键词下的岗位列表。

行为：

- 写入 `D:\Downloads\zhilian_list_tasks.jsonl`
- Joblens 扩展后台轮询队列
- 完成后写入 `D:\Downloads\zhilian_list_results.jsonl`
- 监视脚本根据结果自动归档

关键参数：

- `keyword`: 职业关键词，例如 `人工智能讲师`
- `city_id`: 智联城市 ID，默认 `538`
- `pages`: 页数，默认 `auto`
- `test`: 测试模式
- `debug`: 调试参数
- `wake_browser`: 是否打开轻量唤醒页触发后台队列

### `launch_zhilian_job_detail_collection`

采集某个具体岗位详情页。

行为：

- 校验 `zhaopin.com` 岗位 URL
- 写入 `D:\Downloads\zhilian_detail_tasks.jsonl`
- Joblens 扩展后台打开详情页并采集
- 写入 `D:\Downloads\zhilian_detail_results.jsonl`
- 监视脚本根据结果自动归档

关键参数：

- `job_url`: 智联详情页 URL
- `keyword`: 所属职业关键词，用于归档定位
- `save_html`: 是否保留原始 HTML
- `save_json`: 是否保留 manifest JSON
- `wake_browser`: 是否打开唤醒页触发后台队列

详情页归档后的最终命名：

```text
{公司名称}_{岗位名称}.md
```

### `archive_joblens_outputs`

将 `D:\Downloads` 中的 Joblens 产物归档到 `storage_layer/positions`。

参数：

- `keyword`: 职业关键词
- `platform`: `zhilian` 或 `boss`
- `since_minutes`: 只处理最近 N 分钟产物
- `dry_run`: 只预览归档计划
- `include_test`: 是否包含 TEST 产物

路由规则：

- `zhilian_keyword_discovery_*.md` -> `storage_layer/positions/`
- `ZHILIAN_<keyword>_*.md` -> 职业目录下的 `_岗位索引表_{keyword}.md`
- `ZHILIAN_DETAIL_{公司}_{岗位}_{timestamp}.md` -> 职业目录下的 `{公司}_{岗位}.md`
- raw / manifest 文件 -> 职业目录下的 `raw/`

注意：MCP 内置归档工具使用移动语义。如果 `/mnt/d/Downloads` 在当前 WSL 会话中是只读挂载，移动会失败；这种情况下应在 Windows 侧执行移动，或使用 `scraping_layer/scripts/archive_outputs.py` 的降级复制策略。

### `update_persona`

更新当前用户画像中的技能置信度。

参数：

- `skill_name`
- `confidence_score`，范围 `0-100`
- `reasoning`

## 队列文件

智联详情页队列：

```text
D:\Downloads\zhilian_detail_tasks.jsonl
D:\Downloads\zhilian_detail_results.jsonl
```

智联列表页队列：

```text
D:\Downloads\zhilian_list_tasks.jsonl
D:\Downloads\zhilian_list_results.jsonl
```

results JSONL 的典型记录：

```json
{
  "task_index": 1,
  "url": "https://www.zhaopin.com/jobdetail/....htm?detail=1",
  "normalized_url": "https://www.zhaopin.com/jobdetail/....htm",
  "job_id": "...",
  "keyword": "人工智能讲师",
  "status": "done",
  "recorded_at": "2026-05-07T11:32:35.036Z"
}
```

## 安全验证处理

Joblens 内容脚本会检测验证码/人机验证/安全验证页。详情采集中一旦出现安全验证：

- 当前任务写入 `failed`
- 失败原因包含 `captcha detected`
- 扩展将详情队列置为暂停
- 停止继续采集后续任务
- 浏览器将验证页带到前台，等待人工处理
- 监视脚本收到 captcha 失败后通知并退出，不自动重试、不归档

手动完成验证后，需要重新唤醒详情队列再继续采集。

## Joblens 扩展

Joblens 是 JobSniper 使用的 Chrome 扩展集成层。源码位于：

```text
scraping_layer/joblens
```

构建 Chrome 扩展：

```bash
cd /path/to/JobSniper/scraping_layer/joblens
npm install
npm run build
```

构建后需要在 Chrome 扩展管理页重新加载扩展，新的后台队列逻辑才会生效。

## 常用操作

采集 job menu：

```text
launch_zhilian_job_menu_collection(debug=true)
```

采集职业关键词列表：

```text
launch_zhilian_job_list_collection(keyword="人工智能讲师", pages="auto", wake_browser=true)
```

采集岗位详情：

```text
launch_zhilian_job_detail_collection(
  job_url="https://www.zhaopin.com/jobdetail/....htm",
  keyword="人工智能讲师",
  wake_browser=true
)
```

预览归档：

```text
archive_joblens_outputs(keyword="人工智能讲师", platform="zhilian", dry_run=true)
```

执行归档：

```text
archive_joblens_outputs(keyword="人工智能讲师", platform="zhilian", dry_run=false)
```

## 开发验证

Python smoke test：

```bash
cd /path/to/JobSniper
venv/bin/python scraping_layer/scripts/smoke_mcp_server.py
```

MCP stdio smoke test：

```bash
cd /path/to/JobSniper
venv/bin/python scraping_layer/scripts/smoke_mcp_server.py --stdio
```

Joblens build：

```bash
cd /path/to/JobSniper/scraping_layer/joblens
npm run build
```

Git hygiene：

```bash
git status --short --branch
git diff --check
```

## 许可证

本项目采用 PolyForm Noncommercial License 1.0.0。源码仅允许个人学习、研究、教育和非商业用途。任何商业使用、商业集成、SaaS 服务、企业内部生产使用或商业培训使用，均需获得作者书面授权。
