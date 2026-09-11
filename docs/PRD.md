# JobSniper PRD

## 1. 产品概述

JobSniper 是一个面向本地求职情报工作的 MCP Server。它让 Codex、Claude Desktop 等 AI Client 可以通过统一 MCP 接口读取岗位知识库、启动招聘平台采集、归档采集产物、维护用户画像，并为后续简历、推荐和面试准备工作流提供本地数据基础。

当前版本支持智联招聘（Zhilian）与 BOSS 直聘（Boss Zhipin）两条情报链路：job menu 发现、职业关键词岗位列表采集、单岗位详情采集（BOSS 详情与公司信息合并为单一 Markdown）、Downloads 产物归档、岗位详情检索和用户画像更新。

## 2. 目标用户

- **求职者 / 操作者**：维护自己的岗位知识库、用户画像、简历和会话产物。
- **AI Agent**：通过 MCP 工具读取资料、启动采集、检索岗位、归档产物和更新画像。
- **后续求职工作流**：基于本地岗位库和用户画像生成岗位推荐、简历改写、面试准备和决策分析。

## 3. 当前 MVP 范围

### 已包含

- FastMCP stdio 服务入口。
- MCP Resource：读取当前用户画像。
- MCP Resource：按平台和自然嵌套路径读取岗位详情 Markdown。
- MCP Tool：按文件名搜索岗位详情。
- MCP Tool：以统一 `platform` 参数（`zhilian` / `boss`）启动 job menu、job list、job detail 三类采集。
- BOSS 直聘采集闭环：列表滚动采集、详情页采集、详情与公司信息合并归档。
- MCP Tool：归档 Joblens 下载产物到 `storage_layer/positions`。
- MCP Tool：更新用户画像技能置信度。
- Chrome 扩展 Joblens：负责浏览器内页面访问、队列消费和数据导出。
- 仓库内监视脚本：根据 results JSONL 判断完成、失败、重试和归档。

### 暂不包含

- 完整推荐报告、简历生成和面试准备流水线。
- 本地配置文件支持（`.env` / `jobsniper.local.json`）。
- Joblens 扩展队列路径配置化（扩展内仍硬编码 `D:/Downloads`）。
- 更多招聘平台接入与更完整的多平台抽象。
- 远程托管、多用户账号体系或云端数据库。

## 4. 产品结构

JobSniper 当前采用本地三层目录结构：

```text
scraping_layer/   # 浏览器采集、Joblens 扩展、队列监视和归档辅助脚本
storage_layer/    # 用户画像、岗位知识库、平台岗位库
session_layer/    # 简历、会议记录、报告等会话产物
```

核心运行链路：

```text
AI Client -> MCP Server -> scraping_layer/Joblens -> Downloads 队列与产物
          -> monitor scripts -> storage_layer/positions
```

`scraping_layer/joblens/` 是 Joblens 扩展子项目；本文档是 JobSniper 项目级 PRD。

## 5. 当前限制

- 当前采集依赖本机 Chrome 或 Edge（自动探测常见安装位置，可用 `JOBSNIPER_CHROME_PATH` 显式指定）。
- 当前 Joblens 扩展依赖浏览器登录态访问招聘平台。
- 队列与归档目录可用 `JOBSNIPER_DOWNLOADS_PATH` 配置并支持自动探测；但 Joblens 扩展内部队列路径仍硬编码，暂不支持自定义目录。
- WSL 与 Windows 文件系统之间的 `/mnt/*` 挂载权限可能影响移动归档。
- 智联安全验证/验证码需要人工处理，不自动绕过。

## 6. 本地环境配置化（已实现，剩余收尾）

为支持其他用户从 GitHub 下载并部署 JobSniper，本机硬编码路径依赖已移除，改为「环境变量 > 自动探测 > 默认值」。

### Downloads 路径

- 支持环境变量 `JOBSNIPER_DOWNLOADS_PATH`。
- 未设置时自动探测：`/mnt/d/Downloads` → `~/Downloads` → `/mnt/*/Users/*/Downloads` → `/mnt/*/Downloads`。
- MCP Server 会将解析结果注入监视/归档脚本子进程，保证 MCP Server、监视脚本、归档脚本路径一致。

### Chrome 路径

- 支持环境变量 `JOBSNIPER_CHROME_PATH`。
- 未设置时自动探测 Chrome 稳定版/x86 与 Edge x64/x86 的常见安装位置，以及每用户 Chrome 安装位置。
- 未探测到且路径不存在时，采集入口返回包含实际路径的错误信息。

### 剩余收尾

- 本地配置文件支持（`.env` / `jobsniper.local.json`）。
- Joblens 扩展队列路径配置化（扩展内仍硬编码 `D:/Downloads`，需 `chrome.storage` 方案）。
- Linux / macOS 原生环境的分阶段验证。

## 7. 成功标准

- MCP Client 能完成 `initialize`、`list_tools` 和 `list_resources`。
- 智联 job menu、job list、job detail 采集入口可用。
- 队列结果写入后，监视脚本能自动触发归档。
- 岗位详情可在 `storage_layer/positions` 中按自然嵌套结构保存和检索。
- 用户画像可被读取和更新。
- 本地路径配置化已落地：新用户无需修改源码即可部署运行（环境变量或自动探测），本地配置文件支持待收尾。

## 8. 风险

- 招聘平台页面结构变化会影响采集稳定性。
- 招聘平台安全验证会中断自动化流程。
- 浏览器扩展、MCP Server、监视脚本运行在不同上下文，路径配置必须保持一致。
- Windows/WSL、Linux、macOS 的路径和权限模型不同，配置化方案需要分阶段验证。
