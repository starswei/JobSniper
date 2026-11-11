# 文件组织规范
1. `storage_layer` 文件夹用于构建「环境（Environment）- 岗位（Position）- 用户（User）」三位一体本地核心知识库。
2. `storage_layer` 文件夹分为 `personas`、`positions` 和 `markets` 共三个子文件夹：
   - `personas` 文件夹用于存储用户层画像与能力事实库文档（`current_user.json`、`master_profile.md`、`career_profile.md`）。
   - `positions` 文件夹用于存储岗位层微观招聘信息，按平台分成若干个子文件夹（如 `boss_intelligence_vault`、`zhilian_intelligence_vault`）。
   - `markets` 文件夹用于存储环境层（社会、人口、宏观政经、政策、行业与市场行情）情报，下设五个标准子目录：
     - `demographics/`：人口学与人才供给统计（高校本科/硕士/博士历年在校人数、同年毕业人数、就业/失业人口、适龄/学龄人口统计）；
     - `macro_policy/`：国内外宏观经济、国际政治经济关系、国家政策与地方政府产业政策；
     - `industries/`：行业结构、市场环境与行情发展、产业链与人才断层雷达；
     - `companies/`：重点企业财报与经营战略档案；
     - `papers_and_trends/`：学术论文前沿（Papers）与跨行业技术/求职趋势专题。
3. `boss_intelligence_vault` 文件夹用于存放 BOSS 直聘平台的招聘信息。
4. `zhilian_intelligence_vault` 文件夹用于存放智联招聘平台的招聘信息。
5. 每一个平台文件夹采用自然嵌套（树形聚合）的结构组织，通过层层递进的目录来表达行业、职能、职业分类，各层级将自己的索引文档存放于当前目录下。
6. 平台根目录用于存放该平台的行业索引表，称为平台文档。
7. 平台根目录下的子文件夹按“行业”划分，行业目录下存放该行业的职能索引表，称为行业文档。
8. 行业目录下的子文件夹按“职能”划分，职能目录下存放该职能的职业索引表，称为职能文档。
9. 职能目录下的子文件夹按“职业”划分，职业目录下存放该职业的岗位概要索引表，称为职业文档。
10. 职业目录下存放具体的岗位详情文件，称为岗位文档或岗位详情页。


# 文件命名规范
1. `_行业索引表_[平台名称].md`，如`_行业索引表_智联招聘.md`
2. `_职能索引表_[行业名称].md`，如`_职能索引表_产品.md`
3. `_职业索引表_[职能名称].md`，如`_职业索引表_教务管理.md`
4. `_岗位索引表_[职业名称].md`，如`_岗位索引表_课程设计.md`
5. `[公司名称]_[岗位名称].md`，此处的岗位名称为具体的招聘信息中的岗位名称，如`昂立教育_教研经理.md`
6. `{平台}_keyword_discovery_{timestamp}.md`，平台关键词发现产物，直接存放于 `positions/` 根目录（属于发现产物，不是平台索引表）
7. `raw/` 子目录：归档时保留的原始 HTML 与 manifest JSON 放入所属职业目录下的 `raw/`
8. `company/` 子目录：BOSS 公司信息产物归档至所属职业目录下的 `company/`，其原始文件进一步下沉至 `company/raw/`
9. `markets/` 环境情报命名规范：
   - 索引文件统一以 `_` 开头：`_市场情报总索引.md`、`_人口与人才统计索引表.md`、`_宏观政经与政策索引表.md`、`_行业赛道索引表.md`、`_重点企业索引表.md`、`_论文与趋势专题索引表.md`。
   - 人口学与人才供给统计：`demographics/{周期或区域}_{主题}_统计分析.md`（如 `中国高校本硕博规模与学龄人口结构推演.md`）。
   - 宏观政经与国家政策：`macro_policy/{领域或地区}_{政策或宏观主题}.md`（如 `国内外宏观经济与AI教育产业政策演进.md`）。
   - 行业雷达文档：`industries/{行业名称}/{年份或周期}_{主题}_雷达报告.md`（如 `2025-2026_教育大模型商业化与人才断层报告.md`）。
   - 企业经营与财报档案：`companies/{公司名称}_财报与业务战略档案.md`（如 `好未来_财报与AI业务战略档案.md`）。
   - 学术论文与趋势专题：`papers_and_trends/{专题或核心论文名称}.md`（如 `FSRS自适应算法与认知负荷论文工程化综述.md`、`AI-Native产品工程与Vibe-Coding求职生态位.md`）。


# 元数据规范 (Metadata)
所有**岗位详情页**（岗位文档）必须以 YAML Front Matter 格式在文件开头包含以下元数据：

```yaml
---
job_title: [岗位名称]
company: [公司名称]
position: [职业名称]（对应目录结构的第三层，即关键词）
domain: [职能/领域]（对应目录结构的第二层）
industry: [行业名称]（对应目录结构的第一层）
platform: [平台名称]
---
```

示例：
```yaml
---
job_title: 软件开发助理工程师
company: 上海旗盈企业管理咨询有限公司
position: 小程序开发
domain: 移动研发
industry: 技术
platform: 智联招聘
---
```

BOSS 直聘产物（含详情与公司信息合并后的 Markdown）使用平台扩展字段：

```yaml
---
source: boss
keyword: [职业关键词]
company: [公司名称]
companyUrl: [公司页 URL]
title: [岗位名称]
url: [岗位详情 URL]
collected: [采集时间 ISO8601]
recruitment_status: [招聘状态标识]
recruitment_status_label: [招聘状态文本]
status_checked_at: [状态检查时间]
status_source: [状态来源]
status_evidence: ""
---
```

字段解析器按简单 `key: value` 规则读取 frontmatter，未列出的平台扩展字段原样保留。

所有**市场与行业环境情报文档**（存放于 `storage_layer/markets/` 下非 `_` 开头的文档）必须包含以下 YAML Front Matter 元数据：

```yaml
---
intel_type: demographics_stat | macro_policy | industry_radar | company_profile | paper_and_trend
title: [情报文档标题]
dimension: demographics | macro_economy | geopolitics | policy | industry | company_financials | academic_paper
industry: [所属一级行业名称或 "跨行业"]
company: [关联企业名称或 "N/A"]
media_types: [statistical_bulletin | policy_doc | financial_report | academic_paper | news_research]
fiscal_or_stat_period: [关联统计/财报周期]
hc_weather: booming | expanding | steady | shrinking | frozen | N/A
talent_gap_level: critical | high | moderate | saturated | N/A
collected_at: [采集时间 ISO8601]
valid_until: [建议复核有效期 YYYY-MM-DD]
evidence_level: verified | mixed | preliminary
sources:
  - [数据来源与链接]
---
```


示例：
```text
storage_layer/  
├── personas/  
│   ├── current_user.json
│   ├── master_profile.md
│   └── career_profile.md  
│
├── markets/
│   ├── _市场情报总索引.md
│   ├── demographics/
│   │   ├── _人口与人才统计索引表.md
│   │   └── 中国高校本硕博规模与学龄人口结构推演.md
│   ├── macro_policy/
│   │   ├── _宏观政经与政策索引表.md
│   │   └── 国内外宏观经济与AI教育产业政策演进.md
│   ├── industries/
│   │   ├── _行业赛道索引表.md
│   │   └── AI与教育科技/
│   │       └── 2025-2026_教育大模型商业化与人才断层报告.md
│   ├── companies/
│   │   ├── _重点企业索引表.md
│   │   ├── 好未来_财报与AI业务战略档案.md
│   │   └── 网易有道_财报与AI业务战略档案.md
│   └── papers_and_trends/
│       ├── _论文与趋势专题索引表.md
│       ├── FSRS自适应算法与认知负荷论文工程化综述.md
│       └── AI-Native产品工程与Vibe-Coding求职生态位.md
│
└── positions/  
    ├── boss_intelligence_vault/
    │   ├── _行业索引表_BOSS直聘.md                  ← 平台文档
    │   ├── 产品/  
    │   │   ├── _职能索引表_产品.md                  ← 行业文档
    │   │   ├── 互联网产品经理/  
    │   │   │   ├── _职业索引表_互联网产品经理.md     ← 职能文档
    │   │   │   ├── AI产品经理/  
    │   │   │   │   ├── _岗位索引表_AI产品经理.md    ← 职业文档
    │   │   │   │   ├── 字节跳动_AI产品经理.md      ← 岗位文档（岗位详情页）  
    │   │   │   │   └── ……
    │   │   │   ├── 软件产品经理/
    │   │   │   └── ……
    │   │   ├── 游戏策划or制作/
    │   │   └── ……
    │   ├── 教育培训/  
    │   │   ├── _职能索引表_教育培训.md                      
    │   │   ├── 教务管理/  
    │   │   │   ├── _职业索引表_教务管理.md                  
    │   │   │   ├── 课程设计/  
    │   │   │   │   ├── _岗位索引表_课程设计.md              
    │   │   │   │   ├── 昂立教育_教研经理.md  
    │   │   │   │   └── ……
    │   │   │   └── ……
    │   │   └── ……
    │   └── ……
    │
    └── zhilian_intelligence_vault/  
        └── ……                                     ← 同上结构  
```
