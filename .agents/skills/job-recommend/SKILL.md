---
name: job-recommend
description: 从 JobSniper 本地岗位知识库中按岗位关键词推荐匹配岗位，结合用户画像打分排序
argument-hint: <岗位关键词> [地点/薪资/偏好等约束]
---

# /job-recommend

根据用户指定的岗位关键词，从 JobSniper 本地岗位知识库（智联招聘 / BOSS直聘）遍历岗位详情，结合用户画像和本次会话约束做匹配推荐。

## 设计原则

- **本地优先**：优先使用当前仓库内的 `storage_layer` 数据，不调用外部画像服务，除非用户明确要求。
- **可解释**：每个推荐必须说明匹配理由、主要风险和投递优先级。

## 前置数据

### 项目根目录

从当前仓库根目录推导：

```text
<repo>/storage_layer/positions/
<repo>/storage_layer/personas/current_user.json
```

### 岗位知识库

支持智联招聘与 BOSS直聘两大平台：

```text
storage_layer/positions/{platform}_intelligence_vault/
```

- 智联招聘：`storage_layer/positions/zhilian_intelligence_vault/`
- BOSS直聘：`storage_layer/positions/boss_intelligence_vault/`

默认优先读取已收录该关键词的知识库。如用户指定平台，则切换到对应平台库。

### 岗位分类索引

读取对应平台的任务映射文件：

- 智联招聘：`storage_layer/positions/zhilian_master_tasks.json`
- BOSS直聘：`storage_layer/positions/boss_master_tasks.json`

用于将用户输入的岗位关键词映射到 `{industry, domain, keyword}`。

### 用户画像

优先读取：

```text
storage_layer/personas/current_user.json
```

提取推荐所需的关键维度：

- 目标岗位方向（及具体细分领域，如 LLM、CV、规控等）
- 目标城市或可接受地点（及区域偏好）
- 薪资底线或期望区间
- 核心技能栈（技能名称及自我评级/置信度）
- 行业/公司类型偏好
- 学历、工作年限与硬性约束条件

> ⚠️ **强阻断约束**：
> 若 `storage_layer/personas/current_user.json` 不存在或关键信息缺失，**禁止直接跳过并给出通用模糊推荐**。
> 必须立即转入**「交互式画像建档访谈」**模式，向用户提问采集上述关键维度，生成并持久化写入 `storage_layer/personas/current_user.json` 后，再继续执行后续的岗位匹配与打分。

## 执行流程

### 第 1 步：解析关键词

```text
用户输入岗位关键词
  ↓
读取 storage_layer/positions/{platform}_master_tasks.json
  ↓
精确匹配 keyword 字段
  ↓
命中 → { keyword, industry, domain }
未命中 → 使用语义理解映射到最接近的 keyword，并在输出中说明映射结果
```

如果无法合理映射，列出 3-5 个相近关键词供用户选择，不要臆造目录。

### 第 2 步：定位岗位目录

```text
storage_layer/positions/{platform}_intelligence_vault/{industry}/{domain}/{keyword}/
```

处理规则：

- 排除 `_` 开头的索引文件（例如 `_岗位索引表_*.md`）。
- 遍历剩余 `*.md` 岗位详情文件。
- 优先读取 YAML frontmatter 中的 `title`、`company`、`salary`、`location`、`url`、`keyword` 等字段。
- frontmatter 缺失时，再从正文中提取必要字段。

### 第 3 步：初筛

根据用户画像和本次约束进行硬条件过滤：

- 地点明显不符合且用户未表示可接受远程/异地 → 剔除。
- 薪资上限低于用户薪资底线 → 剔除。
- 学历或证书要求明显不可满足 → 剔除或标记高风险。
- 年限要求明显超出用户经验且无弹性措辞 → 标记低优先级。
- 岗位方向与用户目标明显无关 → 剔除。

如果候选太少，可适度放宽非硬性条件，并在输出中说明。

### 第 4 步：精选打分

对初筛候选读取岗位详情全文，按 100 分制评分：

| 维度 | 权重 | 判据 |
|------|------|------|
| 岗位方向契合 | 30% | JD 职责是否匹配用户目标岗位 |
| 技能匹配 | 25% | 用户技能是否被 JD 提及，或可合理迁移 |
| 门槛友好 | 20% | 经验年限、学历、行业背景、专业要求是否友好 |
| 发展价值 | 15% | 公司背书、业务方向、成长空间、稳定性 |
| 薪资与地点 | 10% | 是否满足薪资和地点偏好 |

推荐输出 Top 10-15 个；如果岗位库候选较少，输出全部候选。

### 第 5 步：分档输出

按匹配度分三档：

- **S 档**：高度契合，建议优先投递。
- **A 档**：整体匹配，存在少量风险但值得尝试。
- **B 档**：备选岗位，适合补充投递或保底。

输出格式示例：

```markdown
# [岗位关键词] — 岗位匹配推荐

## S 档
### 1. 公司 — 岗位名
| 维度 | 内容 |
|------|------|
| 匹配分 | 92/100 |
| 薪资/地点 | 30-45K / 上海 |
| 推荐理由 | 核心要求与用户技能栈高度吻合... |
| 主要风险 | 要求有大模型微调经验... |
| 相对路径 | storage_layer/positions/... |

## A 档
...

## B 档
...

## 投递优先级建议
| 优先级 | 岗位 | 理由 |
|--------|------|------|
```

### 第 6 步：新鲜度检查

如果岗位详情文件采集时间超过 7 天，或缺少采集时间字段，应在末尾提示：

```text
> ⚠️ 提示：部分岗位数据可能已过期，建议先通过 MCP 工具重新采集岗位列表或详情后再做最终投递决策。
```

## 注意事项

- **不要使用 `find_job_detail` 作为推荐主流程**：它仅做文件名字面匹配，会遗漏大量候选。
- 必须遍历目标目录下全部岗位详情文件，不能用文件名筛选代替全文分析。
- 若岗位目录不存在或为空，提示用户先运行岗位列表采集（`launch_job_list_collection`）。
- 若用户未给出薪资、地点等约束，优先从本地画像读取；仍缺失时再询问用户。
- 输出建议应避免绝对化承诺（如“必过”、“一定匹配”），使用“建议优先”、“风险较低”、“值得尝试”等客观措辞。
