# 职业咨询 SKILL v2.9.3

**定位**：可独立使用、可选接入工程工具的职业咨询专业执行规范。适用于成年求职者的职业分析、职业决策、求职期发展和持续复盘。其专业方法不依赖任何特定 Agent 平台、外部工作台、数据库或服务。可用工具通过通用能力接口提供可复核的研究、计算、状态及审计增强。

## 包含内容

| 路径 | 用途 |
| --- | --- |
| [`SKILL.md`](SKILL.md) | 简洁的触发路由、S1—S6、执行/停止、兼容和建议放行规范 |
| [`职业咨询操作手册.md`](职业咨询操作手册.md) | 独立完整的九章手册，包含 A—U 21 套模板与完全虚构案例 |
| [`contracts/career_case.schema.json`](contracts/career_case.schema.json) | 可选的证据—命题—建议数据契约 |
| [`contracts/capability_manifest.schema.json`](contracts/capability_manifest.schema.json) | 可选工具能力声明结构 |
| [`contracts/execution_state.schema.json`](contracts/execution_state.schema.json) | 可选最小执行快照与建议放行状态 |
| [`contracts/tool_interoperability.md`](contracts/tool_interoperability.md) | 工具能力发现、运行时证据、失败降级及通用互操作约定 |
| [`tools/validate_contract.py`](tools/validate_contract.py) | 职业个案数据与交叉引用门禁 |
| [`tools/validate_runtime.py`](tools/validate_runtime.py) | 能力声明、执行状态及部分确定性门禁 |
| [`tests/`](tests/) | 单元测试、10 个 `INT-xx` 交互回归场景、8 个 `E2E-xx` 行为验收场景 |
| [`references/`](references/) | 27 条外部来源的**本次真实访问/检索日志**（CSV + Markdown） |
| [`examples/`](examples/) | 仅用于演示的合成案例及工程契约快照 |

## 核心工作方式

- **三位一体**：外部环境 × 企业/真实 JD × 个人条件和愿景。
- **四维判断**：当前可进入性、求职期间可提升性、入职后成长性、风险可承担性。
- **决策驱动循环**：优先完成可做研究；仅询问阻断决策的私人事实；在必要时明确停止、恢复、暂定或阻断高成本行动。
- **三种运行模式**：`independent`、`enhanced`、`degraded`。任何特定工程服务**都不是前置条件**；工具声明存在也不等于已获授权或已执行成功。
- **三条反馈链**：独立能力考核、成熟招聘反馈、路径重评；不把没有面试直接归因于个人能力或培训成效。
- **证据三层门禁**：来源核对、命题审查、建议放行相互独立；不得以“网页可访问”直接推导职业建议有效。

## 安装与运行

将整个目录安装为可识别的 SKILL 目录，保持 `SKILL.md` 与手册在同一层级。只需阅读方法时可以打开 Markdown，**无需安装依赖**。下列测试只有在本地 Python 环境中需要。

PowerShell / bash 均可使用（在某些系统上把 `python` 换成 `python3`）：

```sh
python -m pip install -r requirements.txt
python tools/validate_contract.py examples/synthetic_case.json
python tools/validate_runtime.py manifest examples/synthetic_capability_manifest.json
python tools/validate_runtime.py state examples/synthetic_execution_state.json
python -m unittest discover -s tests -v
```

## 核验与验收边界

- [来源复核明细](references/verification_log_2026-11-11.md) 的日期是**本次**检索/读取日期；每条记录区分页面抓取副本、搜索结果、访问受限及未打开 PDF。不追认没有审计日志的历史“已核对”声明。**网页能打开不代表其因果研究正确或现在对个人适用。**
- 静态单测只验证数据结构、引用一致性及一部分可编码门槛，**不能验证就业市场事实、第三方权限、咨询适用性或实际 Agent 输出**。
- `tests/INTERACTION_REGRESSION.md` 与 `tests/BEHAVIOR_EVALUATION.md` 是**供实际 Agent 执行的验收说明**；初始状态均为未测试，不得声称已经在任何平台通过。
- 仅在本人明确授权、且符合适用规则时处理或保存可识别资料。虚构示例不得和真实客户资料混用，不保证特定录用、薪酬或转型结果。
