---
name: resume-matcher
description: 基于 srbhr/Resume-Matcher 理念的本地 ATS 简历与 JD 语义匹配及诊断引擎，自动比对简历文本与岗位 JD，输出关键词命中率、缺失技能清单与优化建议报告
argument-hint: <简历路径> <岗位JD文件/URL/文本> [--output <报告输出路径>]
---

# /resume-matcher (基于 srbhr/Resume-Matcher)

模拟现代招聘系统（ATS - Applicant Tracking System）的机器初筛机制，对指定的候选人简历与目标岗位 JD 进行全景词法与语义比对，精准诊断简历对 JD 的覆盖程度、识别关键缺失技术词汇，并输出针对性的一键优化建议。

## 一、 设计理念

- **机器初筛破局（Beat the ATS）**：HR 往往在系统中根据关键字过滤简历。通过本地自动化诊断，确保目标 JD 要求的核心硬技能、算法、框架与协议以最高密度出现在简历的关键区域。
- **纯本地私密分析**：无需上传简历至任何第三方网站，全部在本地执行，保护个人隐私安全。

---

## 二、 执行流程 (Pipeline)

```text
候选人简历 (.md/txt) + 目标岗位 JD (文件/URL/文本)
                     ↓
调用本地匹配诊断引擎 (scripts/matcher.py)
                     ↓
1. 双端关键词提取 (技术栈、工具链、算法名词、数据指标与业务词)
                     ↓
2. 语义与字面求交 (计算关键词覆盖率及 ATS 得分 0-100%)
                     ↓
3. 缺失关键项识别 (定位 JD 高度强调但在简历中漏写的技术点)
                     ↓
4. 输出多维诊断报告 (分段优化建议：技能前置、项目子弹条润色、大小写规范)
```

---

## 三、 本地执行指令

```bash
D:\Projects\repo\JobSniper\venv\Scripts\python.exe .gemini/skills/resume-matcher/scripts/matcher.py <简历路径> <岗位JD路径或文本> [-o <报告输出路径>]
```

---

## 四、 输出规范

在对话中向用户呈现：
1. **ATS 综合契合度得分**（S/A/B/C 四级评级）；
2. **核心关键词命中盘点（Matched Keywords）**（绿色高亮清单）；
3. **关键缺失词清单（Missing Keywords）**（待补齐或待强化项）；
4. **针对该 JD 的立即可操作修改建议**（指导用户或引导 `resume-tailor` 进行针对性回填）。
