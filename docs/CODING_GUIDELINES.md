# 文件组织规范
1. storage_layer 文件夹用于存放招聘信息文件和用户画像文件
2. storage_layer 文件夹分为 personas 和 positions 共两个子文件夹
3. personas 文件夹用于存储用户画像文档
4. positions 文件夹用于存储招聘信息，按平台分成若干个子文件夹（如，boss_intelligence_vault，zhilian_intelligence_vault）
5. boss_intelligence_vault 文件夹用于存放 BOSS 直聘平台的招聘信息
6. zhilian_intelligence_vault 文件夹用于存放智联招聘平台的招聘信息
7. 每一个平台文件夹采用自然嵌套（树形聚合）的结构组织，通过层层递进的目录来表达行业、职能、职业分类，各层级将自己的索引文档存放于当前目录下
8. 平台根目录用于存放该平台的行业索引表，称为平台文档。
9. 平台根目录下的子文件夹按“行业”划分，行业目录下存放该行业的职能索引表，称为行业文档
10. 行业目录下的子文件夹按“职能”划分，职能目录下存放该职能的职业索引表，称为职能文档
11. 职能目录下的子文件夹按“职业”划分，职业目录下存放该职业的岗位概要索引表，称为职业文档
12. 职业目录下存放具体的岗位详情文件，称为岗位文档或岗位详情页。


# 文件命名规范
1. `_行业索引表_[平台名称].md`，如`_行业索引表_智联招聘.md`
2. `_职能索引表_[行业名称].md`，如`_职能索引表_产品.md`
3. `_职业索引表_[职能名称].md`，如`_职业索引表_教务管理.md`
4. `_岗位索引表_[职业名称].md`，如`_岗位索引表_课程设计.md`
5. `[公司名称]_[岗位名称].md`，此处的岗位名称为具体的招聘信息中的岗位名称，如`昂立教育_教研经理.md`
6. `{平台}_keyword_discovery_{timestamp}.md`，平台关键词发现产物，直接存放于 `positions/` 根目录（属于发现产物，不是平台索引表）
7. `raw/` 子目录：归档时保留的原始 HTML 与 manifest JSON 放入所属职业目录下的 `raw/`
8. `company/` 子目录：BOSS 公司信息产物归档至所属职业目录下的 `company/`，其原始文件进一步下沉至 `company/raw/`


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


示例：
storage_layer/  
├── personas/  
│   └── 用户画像.md  
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
