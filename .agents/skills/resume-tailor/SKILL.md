---
name: resume-tailor
description: 根据目标公司/岗位 JD 与用户真实画像，运用 STAR 原则与 ATS 关键词对齐技术，深度定制高通过率定向简历与 HR 打招呼话术
argument-hint: <目标岗位文件路径 或 岗位URL 或 目标JD文本> [--company <公司名>] [--mode <full|greeting|delta>] [--pdf]
---

# /resume-tailor

根据目标公司岗位 JD（支持情报库文件、BOSS/智联 URL 或直接文本），结合候选人真实履历事实库（`storage_layer/personas/current_user.json`），自动生成高匹配度、ATS 友好、遵循 STAR 原则的定制化简历与定向 HR 打招呼话术。

## 设计原则

- **绝对真实性（Truth Source Moat）**：以 `current_user.json` 及用户已确认履历为唯一事实底稿，严禁无中生有编造公司、学历、虚假时间线或从未涉足的技术。
- **履历边界隔离（Strict Experience Boundary）**：
  - **上海小码王（2024.11 – 2026.03）**：定义为信奥算法教练，负责 NOI 高等算法教研体系研发、信息学奥赛题库平台搭建、升学手册编撰及 C++ 算法授课。
  - **江苏南京童程童美（2023.03 – 2024.11）**：定义为 CSP-J/S 与 Python 机器学习一线教学交付与转化，服务 300+ 学员，辅导 50+ 省部级奖项，单月口碑续费突破 30 万元；**不承担课程研发职责**；2024年底母公司达内资金链断裂及全国多地校区破产停业作为客观离职背景。
- **ATS 关键词强对齐（Keyword Alignment）**：将目标 JD 中出现的硬核技术名词（如 Agent Framework、RAG、Tool Calling/MCP、Context Engineering 等）高频且自然地植入个人总结与项目 Bullet Points 中。
- **双模态输出**：同时产出排版优雅的 Markdown 完整定向简历与配套的「HR 极速破冰打招呼语」。

---

## 前置数据依赖

1. **用户画像事实库**：
   ```text
   storage_layer/personas/current_user.json
   ```
   若不存在或核心关键字段缺失，先与用户互动确认核心事实，再执行生成。
2. **目标岗位 JD 来源**：
   - 方式 A（本地情报库路径）：`storage_layer/positions/{platform}_intelligence_vault/.../{file}.md`
   - 方式 B（招聘平台链接）：`https://www.zhipin.com/job_detail/...` 或智联 URL
   - 方式 C（用户直接粘贴文本）：用户直接提供的职责与要求文本

---

## 执行流程

### 第 1 步：加载与校准事实底稿
1. 读取 `storage_layer/personas/current_user.json`；
2. 提取并锁定候选人核心档案：
   - 真实姓名/代称、联系方式、目标城市（上海为主）；
   - 核心技能评级（置信度分数与对应证据链）；
   - 各阶段公司名称、职务、时间段与严格职责红线。

### 第 2 步：解析与解构目标岗位 JD
提取 JD 中的 4 维核心画像：
1. **硬性技术关键词**：编程语言（Python/C++ 等）、框架（FastMCP/Agent/RAG/Vue/Node）、协议等；
2. **业务与场景关键词**：K12教育、信奥、答疑批改、数据中台、出海、SaaS等；
3. **软实力与工作习惯**：自驱力、跨部门协作、从 0 到 1、抗压交付；
4. **招聘门槛**：学历要求、经验年限、工作地点（如上海杨浦/浦东等）。

### 第 3 步：定调打法轨迹（Track Selection）
根据 JD 偏向，自动选定简历的核心叙事侧重：
- **A 轨（工程/Agent/全栈研发）**：突出 FastMCP、Agent 编排架构、RAG 向量检索、高并发与工程落地；
- **B 轨（AI 产品经理/教育解决方案）**：突出对教育痛点的敏锐洞察、教研体系转化、Prompt/Workflow 设计与产品商业化数据；
- **C 轨（信奥与算法教研）**：突出 NOI 竞赛成绩、高质量题库建设、算法授课与高额续费口碑转化。

### 第 4 步：基于 STAR 原则重构子弹条（Bullet Points）
遵循 `references/star-guidelines.md` 规范：
- **S (Situation)**：痛点或背景引入；
- **T (Task)**：攻坚任务与边界；
- **A (Action)**：采用的技术方案、设计模式与核心行动（强嵌入 JD 原词）；
- **R (Result)**：量化指标与成果。

### 第 5 步：生成与持久化定向简历
1. 基于 `templates/standard-resume-template.md` 输出完整 Markdown 简历；
2. 自动保存至项目仓库路径：
   ```text
   session_layer/resume/{company}_{job_title}_resume.md
   ```
3. 同步写入并展示在当前会话的 Artifact 目录中。

### 第 6 步：生成配套 HR 打招呼语（Opening Greetings）
提供两个定制版本：
- **极速破冰版（100-130字）**：3 秒抓人，突出“核心技术栈强匹配 + 本地常住杨浦/上海 + 随时到岗”，适合 BOSS 直接发送；
- **技术深度版（200-250字）**：按“架构能力 + 工具/RAG生态 + 业务理解”三点展开，适合给技术负责人或业务主管看。

### 第 7 步：自动化编译高质感 PDF（PDF Export）
技能内置 Headless Chrome/Edge 渲染管线，通过专用脚本将 Markdown 一键编译为像素级对齐、分页友好的专业 PDF：
```bash
D:\Projects\repo\JobSniper\venv\Scripts\python.exe .agents/skills/resume-tailor/scripts/export_pdf.py <markdown_path> [-o <pdf_path>]
```
- **排版标准**：A4 纸张规范（12mm 边距）、`break-inside: avoid` 防止项目卡片跨页截断、品牌蓝标题标线、高可读性系统字体栈；
- **产出路径**：默认同步输出至 `session_layer/resume/{company}_{job_title}_resume.pdf`。

---

## 输出规范

在对话中向用户呈现：
1. **JD 匹配度与核心命中词诊断表**（命中词 vs 待突出项）；
2. **两版 HR 打招呼开场白**；
3. **定向定制简历 Markdown 文件直达链接**；
4. **编译生成的 PDF 简历直达链接**（可直接投递）。
