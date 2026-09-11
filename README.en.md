# JobSniper

JobSniper is a local MCP Server for job-search intelligence work. It keeps platform collection, job intelligence, candidate persona data, and session outputs in one local workspace, so MCP clients such as Codex and Claude Desktop can read data, launch collection tasks, archive job artifacts, and update persona signals through a consistent interface.

The current implementation focuses on Zhilian recruitment intelligence: platform job-menu discovery, occupation keyword job-list collection, single job-detail collection, Downloads artifact archiving, job-detail search, and candidate persona maintenance.

## Capability Scope

Implemented:

- FastMCP stdio server entrypoint: `mcp_server.py`
- MCP resource for reading the current candidate persona
- MCP resource for reading job-detail Markdown files by nested vault path
- MCP tool for searching job-detail files
- MCP tool for collecting the job menu (industry-function-occupation tree), currently for Zhilian
- MCP tool for collecting job lists under an occupation keyword, for both Zhilian and BOSS Zhipin
- MCP tool for collecting a concrete job detail page, for both Zhilian and BOSS Zhipin; BOSS detail and company info are merged into a single Markdown
- Unified `platform` argument (`zhilian` / `boss`) shared by all collection tools
- MCP tool for archiving Joblens outputs from `D:\Downloads`
- MCP tool for updating persona skill confidence scores
- Joblens Chrome extension integration: `scraping_layer/joblens`
- Background queue collection through `zhilian_detail_tasks.jsonl` and `zhilian_list_tasks.jsonl`
- Monitor scripts that inspect results JSONL files, detect completion/failure, retry when appropriate, and archive outputs

Still evolving:

- More recruitment platforms
- Fuller recommendation-report and resume-generation workflows
- Archive move behavior across Windows/WSL permission differences
- Configurable local paths (`DOWNLOADS_PATH` / `WINDOWS_CHROME_PATH`)

## Directory Layout

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

## Data Model

`storage_layer/positions` is split by platform. Each platform vault uses a natural nested structure:

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

Core concepts:

- **Platform index table**: the navigation entry for one platform vault, such as `_行业索引表_智联招聘.md`.
- **Occupation job index table**: the archived job list under one occupation keyword, such as `_岗位索引表_人工智能讲师.md`.
- **Job detail page**: the final leaf file, named `{Company Name}_{Job Title}.md`.
- **Keyword discovery artifact**: the platform job-menu discovery output, named `{platform}_keyword_discovery_{timestamp}.md`, stored at the root of `storage_layer/positions/`. It is not the platform index table.

See [docs/CODING_GUIDELINES.md](docs/CODING_GUIDELINES.md) for detailed naming rules.

## MCP Setup

Install Python dependencies:

```bash
cd /path/to/JobSniper
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

MCP client configuration example:

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

Protocol-level smoke test:

```bash
cd /path/to/JobSniper
venv/bin/python scraping_layer/scripts/smoke_mcp_server.py --stdio
```

Expected result: the client completes `initialize`, `list_tools`, and `list_resources`, and sees 6 tools plus 1 resource.

## MCP Resources

### `jobsniper://persona`

Reads the current candidate persona:

```text
storage_layer/personas/current_user.json
```

If the persona file does not exist, the server returns a default empty persona skeleton.

### `jobsniper://vault/positions/{platform}/{path_to_job}`

Reads a job-detail Markdown file by natural nested path.

Example:

```text
jobsniper://vault/positions/zhilian/产品/互联网产品经理/AI产品经理/上海倍通医药科技咨询有限公司_AI产品经理.md
```

## MCP Tools

### `find_job_detail`

Searches the job intelligence vault by job-detail filename.

Parameters:

- `platform`: `zhilian` or `boss`
- `keyword`: job-title or filename keyword
- `company`: optional company-name keyword
- `limit`: maximum number of matches

The response includes absolute paths, relative paths, and MCP resource URIs for matched files.

### `launch_zhilian_job_menu_collection`

Collects the Zhilian platform job menu: an industry-function-occupation hierarchy.

Behavior:

- Opens the Zhilian homepage
- Adds `joblens_keyword_discovery=1`
- Lets the Joblens extension export a keyword discovery Markdown file

Output filename:

```text
zhilian_keyword_discovery_{timestamp}.md
```

Archive target:

```text
storage_layer/positions/
```

### `launch_zhilian_job_list_collection`

Collects the job list under one occupation keyword.

Behavior:

- Writes a task to `D:\Downloads\zhilian_list_tasks.jsonl`
- The Joblens extension polls the queue in the background
- The extension writes `D:\Downloads\zhilian_list_results.jsonl`
- The monitor script archives outputs according to the results file

Key parameters:

- `keyword`: occupation keyword, for example `人工智能讲师`
- `city_id`: Zhilian city ID, default `538`
- `pages`: page count, default `auto`
- `test`: test mode
- `debug`: debug parameters
- `wake_browser`: whether to open a lightweight wake page to trigger the background queue

### `launch_zhilian_job_detail_collection`

Collects one concrete Zhilian job detail page.

Behavior:

- Validates that the URL is a `zhaopin.com` job URL
- Writes a task to `D:\Downloads\zhilian_detail_tasks.jsonl`
- The Joblens extension opens and collects the detail page in the background
- The extension writes `D:\Downloads\zhilian_detail_results.jsonl`
- The monitor script archives outputs according to the results file

Key parameters:

- `job_url`: Zhilian job-detail URL
- `keyword`: occupation keyword used for archive routing
- `save_html`: whether to keep raw HTML
- `save_json`: whether to keep manifest JSON
- `wake_browser`: whether to open a wake page to trigger the background queue

Final archived detail filename:

```text
{Company Name}_{Job Title}.md
```

### `archive_joblens_outputs`

Archives Joblens outputs from `D:\Downloads` into `storage_layer/positions`.

Parameters:

- `keyword`: occupation keyword
- `platform`: `zhilian` or `boss`
- `since_minutes`: only process artifacts modified within the last N minutes
- `dry_run`: preview the archive plan without moving files
- `include_test`: include TEST artifacts

Routing rules:

- `zhilian_keyword_discovery_*.md` -> `storage_layer/positions/`
- `ZHILIAN_<keyword>_*.md` -> `_岗位索引表_{keyword}.md` under the occupation directory
- `ZHILIAN_DETAIL_{Company}_{Job}_{timestamp}.md` -> `{Company}_{Job}.md` under the occupation directory
- raw / manifest files -> `raw/` under the occupation directory

Note: the MCP archive tool uses move semantics. If `/mnt/d/Downloads` is mounted read-only in the current WSL session, the move will fail. In that case, run the move from Windows, or use the fallback copy behavior in `scraping_layer/scripts/archive_outputs.py`.

### `update_persona`

Updates a skill confidence score in the current candidate persona.

Parameters:

- `skill_name`
- `confidence_score`, from `0` to `100`
- `reasoning`

## Queue Files

Zhilian detail queue:

```text
D:\Downloads\zhilian_detail_tasks.jsonl
D:\Downloads\zhilian_detail_results.jsonl
```

Zhilian list queue:

```text
D:\Downloads\zhilian_list_tasks.jsonl
D:\Downloads\zhilian_list_results.jsonl
```

Typical results JSONL record:

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

## Security Verification Handling

The Joblens content script detects captcha, human verification, and security verification pages. During detail collection, once a verification page appears:

- The current task is written as `failed`
- The failure reason includes `captcha detected`
- The extension marks the detail queue as paused
- No further detail tasks are collected
- The browser brings the verification page to the foreground for manual handling
- The monitor script notifies and exits; it does not retry or archive automatically

After manually completing verification, wake the detail queue again to continue collection.

## Joblens Extension

Joblens is the Chrome extension integration layer used by JobSniper. Source path:

```text
scraping_layer/joblens
```

Build the Chrome extension:

```bash
cd /path/to/JobSniper/scraping_layer/joblens
npm install
npm run build
```

After building, reload the extension in Chrome's extension management page so the new background queue logic takes effect.

## Common Operations

Collect the job menu:

```text
launch_zhilian_job_menu_collection(debug=true)
```

Collect a job list by occupation keyword:

```text
launch_zhilian_job_list_collection(keyword="人工智能讲师", pages="auto", wake_browser=true)
```

Collect a job detail page:

```text
launch_zhilian_job_detail_collection(
  job_url="https://www.zhaopin.com/jobdetail/....htm",
  keyword="人工智能讲师",
  wake_browser=true
)
```

Preview archive:

```text
archive_joblens_outputs(keyword="人工智能讲师", platform="zhilian", dry_run=true)
```

Run archive:

```text
archive_joblens_outputs(keyword="人工智能讲师", platform="zhilian", dry_run=false)
```

## Development Checks

Python smoke test:

```bash
cd /path/to/JobSniper
venv/bin/python scraping_layer/scripts/smoke_mcp_server.py
```

MCP stdio smoke test:

```bash
cd /path/to/JobSniper
venv/bin/python scraping_layer/scripts/smoke_mcp_server.py --stdio
```

Joblens build:

```bash
cd /path/to/JobSniper/scraping_layer/joblens
npm run build
```

Git hygiene:

```bash
git status --short --branch
git diff --check
```

## License

This project is licensed under the PolyForm Noncommercial License 1.0.0. The source code may be used for personal, educational, research, and other non-commercial purposes only. Commercial use, commercial integration, SaaS use, internal production use by a business, and commercial training use require prior written permission from the author.
