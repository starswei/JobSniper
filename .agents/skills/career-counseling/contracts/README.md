# 职业咨询结构化数据契约（v1.0.0）

这份 JSON Schema 与校验脚本是 **职业咨询操作手册的可选工程配件**，对应手册的模板 C、O、P、Q。它不替代手册，也不依赖任何具体模型厂商或 Agent 编排框架。

## 一、对象关系

`scope → evidence → claims → recommendations` 是最小的推理链；`job_requirements` 引用具体来源，`capability_observations` 记录任务相关的能力证据。引用均以稳定 ID 表示，真实市场结论不得由未核对或虚构资料自动升级。

| 对象 | 功能 | 重要字段 |
| --- | --- | --- |
| `scope` | 本次地区、截止日、候选路径与决策问题 | `region`、`as_of_date`、`decision_by` |
| `evidence` | 来源条目，记录直接原文或记录材料 | `source_url`、`upstream_id`、`review_stage`、`synthetic` |
| `claims` | 可审计命题，分开事实、趋势、因果与情景 | `claim_type`、`review_status`、`critical_to_decision`、`evidence_ids` |
| `job_requirements` | 岗位门槛、核心要求与加分项 | `requirement_type`、`gate_status`、`evidence_id` |
| `capability_observations` | 自述与测评隔离，保留观测日期 | `assessment_stage`、`level`、`evidence_ids` |
| `recommendations` | 暂定/可供选择/高成本阻断，留存理由与复盘条件 | `status`、`critical_claim_ids`、`hard_gate_status`、`review_on` |

## 二、不可跨越的状态门槛

1. **来源层**：`unreviewed → text_matched → substantive_reviewed` 是逐级深入的工作状态。`text_matched` 只证明所引用文字与材料匹配；不能因此宣称材料的推断真实。对同一个来源若后续发现错误，应保留审查记录并降级，不允许静默覆盖历史版本。
2. **命题层**：`unverified / partial / verified / conflicted` 由独立审查决定；它们**不是**简单的线性状态机。预测情景不可标 `verified`；趋势/因果要审查不同上游资料与方法。不具备充分事实支持时保持 `partial` 或 `unverified`。
3. **建议层**：`provisional` 限定低成本、可逆的验证行动；`ready_for_client_decision` 要求决定性命题已审查、硬门槛已清除、个人偏好与约束已确认、反证已评估；`high_cost_blocked` 显式阻止当前不可逆投入。发布状态允许**随市场/个人条件变化回退**，不是永久评级。建议由本人最后选择。
4. **能力层**：`unassessed` / `self_report` 不能被自动转换成已测评的 0—4 分。只有基于真实工作样本或独立测评的记录才能填写数值等级；0 表示按具体任务测评后未达到 1 级，而不是未知。
5. **演示隔离**：`synthetic_only=true` 的案例不得包含已核验的现实命题，也不得发布 `ready_for_client_decision`；虚构岗位只演示数据流，不是市场事实。

## 三、校验范围及不可验证事项

JSON Schema 负责字段类型、格式和结构；`tools/validate_contract.py` 额外检查跨记录 ID、数据时间、来源状态、趋势的上游依赖、能力等级与建议发布阻断等。

**校验成功 ≠ 信息真实 ≠ 客户授权已经取得 ≠ 职业建议有效。** 校验器不会打开网址、不会验证招聘是否仍开放、不会确认同一上游来源真的彼此独立，也不会用模型解释因果。外部事实依然需要手册 3.5.1/3.5.2 和模板 Q 的人工或经授权工具审查。身份、资金及私人材料请在有访问控制的本地环境处理，勿直接放入公开示例或版本仓库。

## 四、在项目根目录运行

```powershell
python -m pip install -r requirements.txt
python tools/validate_contract.py examples/synthetic_case.json
python -m unittest discover -s tests -v
```

通过的演示应显示 `VALID`，并明确提示未核验外部事实。真实数据使用同样结构，但请勿把演示来源、URL、验证状态照搬过去。

## 五、可选执行与能力契约（v1.0.0）

- `capability_manifest.schema.json`：能力**声明**，不是实际接入和调用成功的证据。
- `execution_state.schema.json`：当前执行动作与失败/降级的最小快照，不是统一数据库。
- `tools/validate_runtime.py`：检查两个契约的字段与确定性放行门槛。

运行：

```sh
python tools/validate_runtime.py manifest examples/synthetic_capability_manifest.json
python tools/validate_runtime.py state examples/synthetic_execution_state.json
```

`ready_for_client_decision` 的关键前提与个人约束必须同时满足；`high_cost_blocked` 可用于资格/现金未核实的高成本选择；`provisional` 只能涉及低成本可撤回动作。**这些自动检查是必要但不充分条件**，不能独立决定职业适合性或许可外部操作。独立运行、可选工具增强与失败降级规则见 `contracts/tool_interoperability.md`。
