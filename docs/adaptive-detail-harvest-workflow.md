# 自适应详情页爬取工作流

## 触发场景

当某个职业关键词的岗位列表已经采集并归档后，可以从岗位索引表中提取岗位详情 URL，批量采集智联招聘岗位详情页。

当前项目的详情页采集采用队列式流程：

```text
Agent / MCP Tool
  -> 写入 zhilian_detail_tasks.jsonl
  -> Joblens Chrome 扩展后台采集详情页
  -> 写入 zhilian_detail_results.jsonl
  -> watch_downloads.sh 监视结果
  -> archive_outputs.py 归档到 storage_layer/positions
```

BOSS 直聘使用同一队列式流程，队列文件为 `boss_detail_tasks.jsonl` / `boss_detail_results.jsonl`，由 `watch_boss_downloads.sh` 监视，归档时详情与公司信息合并为单一 Markdown。

## 前置条件

- [ ] Chrome 已安装并启用 Joblens 扩展。
- [ ] Chrome 已登录智联招聘账号。
- [ ] 岗位列表索引表已归档至 `storage_layer/positions/{platform}_intelligence_vault/`。
- [ ] 已从岗位索引表或候选岗位文件中提取详情页 URL 清单。
- [ ] `scraping_layer/scripts/watch_downloads.sh` 可以正常运行。
- [ ] `scraping_layer/scripts/archive_outputs.py` 可以正常归档。
- [ ] Downloads 目录使用默认 `/mnt/d/Downloads`，或已通过 `JOBSNIPER_DOWNLOADS_PATH` 指定自定义路径（MCP Server 会将路径传给监视脚本）。

## 自适应降级阶梯

批量入队时不要无节制地一次性唤醒大量详情页。建议按批次提交任务，并在每批完成后根据结果调整节奏。

| 级别 | 每批任务数 | 批间间隔 | 触发条件 |
|------|------------|----------|----------|
| 正常 | 5 | 0s | 初始状态 |
| 一级 | 3 | 90s | 首次出现 `failed`，且原因为验证码或安全验证 |
| 二级 | 1 | 180s | 第二次出现验证码或安全验证 |
| 三级 | 暂停 | - | 第三次出现验证码或安全验证，等待用户手动处理 |

说明：

- `每批任务数` 指 Agent 一轮向 MCP tool 提交的详情页采集任务数量，不代表 Chrome 内部必须同时打开同等数量标签页。
- 当前扩展和监视脚本已经具备失败结果记录能力；自适应策略的重点是控制入队节奏，降低连续触发验证码的概率。

## 验证码检测方式

以 `zhilian_detail_results.jsonl` 和监视脚本状态为准：

- 结果行出现 `status="failed"`。
- 失败原因包含 `captcha detected`、`security verification page detected` 或类似安全验证描述。
- 详情 Markdown 未生成，且对应任务长时间没有 `done` 结果。
- 生成的详情内容明显是安全验证页，而不是岗位详情。

遇到验证码或安全验证时，不要绕过或自动破解验证。应暂停批量采集，等待用户在浏览器中手动完成验证后再继续。

## 执行流程

```text
初始状态: 每批=5, 间隔=0s
      |
      v
+------------------------------+
|  向 MCP tool 提交一批详情 URL |
|  Joblens 后台采集             |
|  监视脚本等待 results JSONL   |
|  检查 done / failed 状态      |
+--------------+---------------+
               |
       +-------+-------+
       |               |
    全部 done       出现 failed
       |               |
       v               v
  归档成功文件    判断失败原因
  继续下一批          |
                       v
              +----------------+
              | 是否验证码/安全 |
              | 验证相关失败?   |
              +-------+--------+
                      |
             +--------+--------+
             |                 |
            否                是
             |                 |
             v                 v
      记录失败 URL       降级采集节奏
      继续后续批次       记录已完成 URL
                               |
                               v
                      第 1 次: 每批=3, 间隔=90s
                      第 2 次: 每批=1, 间隔=180s
                      第 3 次: 暂停并通知用户
                               |
                               v
                      用户手动完成验证后继续
```

## 三层防御叠加

| 层级 | 策略 | 作用 |
|------|------|------|
| 前置 | 使用已登录的 Chrome Profile | 降低验证码触发概率 |
| 实时 | 按批次入队并自适应降级 | 触发后降低访问强度 |
| 兜底 | results JSONL + 监视脚本状态 | 保留完成/失败记录，避免丢进度 |

## 归档规则

详情页采集成功后，监视脚本会调用归档脚本，将 Joblens 输出归档到：

```text
storage_layer/positions/zhilian_intelligence_vault/{industry}/{domain}/{keyword}/
```

例如：

```text
storage_layer/positions/zhilian_intelligence_vault/产品/互联网产品经理/AI产品经理/
```

详情文件通常按以下格式命名：

```text
[公司名称]_[岗位名称].md
```

BOSS 公司信息产物归档至职业目录下的 `company/` 子目录；原始 HTML / manifest 归档至 `raw/`（公司产物再下沉至 `company/raw/`）。

如果需要手动触发归档，可通过 MCP tool 执行：

```text
archive_joblens_outputs(
  keyword="AI产品经理",
  platform="zhilian",
  since_minutes=600,
  dry_run=false,
  include_test=false
)
```

## 执行记录模板

| 批次 | URL 范围 | 每批任务数 | 批间间隔 | done | failed | 是否降级 | 备注 |
|------|----------|------------|----------|------|--------|----------|------|
| 1 | 1-5 | 5 | 0s | | | | |
| 2 | 6-10 | | | | | | |
| ... | ... | ... | ... | ... | ... | ... | ... |

