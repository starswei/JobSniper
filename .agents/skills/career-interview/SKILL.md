---
name: career-interview
description: 基于 vignzpie/resume-agent-skills 深度访谈架构，通过多轮技术与业务深挖互动，提炼日常工作中被忽略的技术难点、系统架构瓶颈与量化指标，自动增量固化至事实底稿 (master_profile.md)
argument-hint: [项目名 或 经历阶段 或 技术领域] [--depth <quick|deep|comprehensive>]
---

# /career-interview (基于 vignzpie/resume-agent-skills)

通过系统化、结构化的深度技术提问，协助候选人挖掘日常工作与项目中被低估或忽略的技术难点、攻坚细节、选型权衡与量化成果，并将访谈结论即时、增量地固化到本地真实事实底稿（`storage_layer/personas/master_profile.md` 与 `current_user.json`）中，形成不可磨灭的个人职业事实库。

## 一、 设计理念

- **经历资产滚雪球（Compounding Profile）**：每一次面试复盘或技术访谈的回答，都会自动归档沉淀为事实，随着使用时间的增加，事实库越来越丰富详实。
- **杜绝空泛，深挖细节**：拒绝“熟练掌握”、“精通”等虚词，必须通过具体场景、定位手段、性能参数与业务结果来佐证技能。

---

## 二、 交互流程 (Interactive Workflow)

```text
触发指令 (/career-interview [目标项目或阶段])
                 ↓
1. 读取现有事实底稿 (master_profile.md & current_user.json)
                 ↓
2. 识别信息薄弱项 (定位指标缺失、技术细节模糊或缺乏对比的经历)
                 ↓
3. 结构化交互提问 (每次抛出 1-2 个精准追问，涵盖架构选型/攻坚/量化/长期资产)
                 ↓
4. 候选人回答与追溯澄清
                 ↓
5. 自动增量固化 (实时更新 master_profile.md 与 current_user.json)
                 ↓
6. 输出 STAR 重构片段供确认
```

---

## 三、 提问深度档位 (Depth Levels)

- **`quick`（极速提炼模式，3-5 分钟）**：聚焦当前项目的核心量化数据与关键技术动词，用于即时补齐简历缺漏项；
- **`deep`（深度挖掘模式，10-15 分钟，默认）**：围绕单一重点项目展开四维递进提问（架构选型 $\rightarrow$ 攻坚瓶颈 $\rightarrow$ 量化指标 $\rightarrow$ 业务资产）；
- **`comprehensive`（全方位盘点模式，20-30 分钟）**：全景扫描近 3 年的所有公司履历与个人作品，彻底重构个人能力画像。

---

## 四、 自动沉淀规范

每次访谈结束后，Agent 必须自动执行：
1. **更新 Markdown 事实底稿**：在 `storage_layer/personas/master_profile.md` 的对应项目或经历下追加 `【深度访谈增量沉淀】` 小节；
2. **同步更新用户画像 JSON**：在 `storage_layer/personas/current_user.json` 中更新对应的技能置信度分数及 evidence 字段；
3. **输出复盘总结卡片**：向候选人反馈本次访谈挖掘出的 3 个核心技术亮点与可直接用于面试回答的 STAR 话术。
