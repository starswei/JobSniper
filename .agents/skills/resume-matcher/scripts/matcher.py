"""
Resume-Matcher Core Engine (inspired by srbhr/Resume-Matcher)
Performs local ATS-style semantic matching, keyword extraction, and gap analysis
between a Candidate Resume and a Job Description (JD).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Built-in High-Impact Tech & Domain Keywords Taxonomy
# Uses lookaround assertions instead of \b so English words match even when adjacent to Chinese characters
W_START = r"(?<![a-zA-Z0-9])"
W_END = r"(?![a-zA-Z0-9])"

RAW_KEYWORDS = [
    # AI / LLM / Agent
    "LLM", "Agent", "Multi-Agent", "AI Agent", "FastMCP", "MCP", "RAG", "Memory", "Harness",
    "Context Engineering", "Prompt Engineering", "Vector DB", "Embedding", "LangChain",
    "LangGraph", "LlamaIndex", "PyTorch", "TensorFlow", "HuggingFace", "Transformer",
    "Fine-tuning", "FSRS", "TTS", "ASR", "Guardrails", "Evaluation", "Few-shot",
    
    # Programming & Frameworks
    "Python", "C++", "Java", "Go", "Golang", "Rust", "TypeScript", "JavaScript",
    "Vue", "React", "Node.js", "FastAPI", "Flask", "Django", "Spring Boot", "SQL",
    
    # Systems, Infrastructure & Architecture
    "Docker", "Kubernetes", "K8s", "Linux", "Git", "CI/CD", "Microservices",
    "Redis", "MySQL", "PostgreSQL", "MongoDB", "Milvus", "Chroma", "Qdrant",
    "Kafka", "RabbitMQ", "Serverless", "Asyncio", "High Concurrency", "Workflow"
]

COMMON_KEYWORD_PATTERNS = [
    f"{W_START}{re.escape(k)}{W_END}" for k in RAW_KEYWORDS
] + [
    # Chinese Tech & Domain Terms
    r"多智能体", r"工具调用", r"上下文工程", r"向量检索", r"混合召回", r"重排", r"知识库",
    r"数据中台", r"任务编排", r"自适应学习", r"间隔重复", r"题库搭建", r"信奥", r"信息学奥赛",
    r"CSP-J/S", r"NOI", r"全栈开发", r"大模型", r"微服务", r"高可用", r"高并发",
    r"性能优化", r"自动化测试", r"端到端", r"评测体系", r"链路追踪"
]


STOP_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "job", "work", "team",
    "inspire", "creativity", "enrich", "life", "pico", "html", "http", "https",
    "www", "zhipin", "com", "detail", "boss", "salary", "area", "status", "date"
}

def extract_keywords(text: str) -> set:
    # Strip frontmatter if present at the very beginning of the document
    clean_text = re.sub(r"^---[\s\S]*?---\s*", " ", text)
    # Strip URLs and URL encodings
    clean_text = re.sub(r"https?://\S+", " ", clean_text)
    clean_text = re.sub(r"%[0-9a-fA-F]{2}", " ", clean_text)
    
    found = set()
    for pat in COMMON_KEYWORD_PATTERNS:
        matches = re.findall(pat, clean_text, re.IGNORECASE)
        for m in matches:
            found.add(m.strip())
            
    # Extract recognized tech names
    tech_candidates = {
        "Python", "Java", "Go", "Golang", "Rust", "Vue", "React", "Node", "Docker",
        "Linux", "Git", "Prompt", "Workflow", "Framework", "Harness", "FastMCP",
        "LangChain", "PyTorch", "Kubernetes", "K8s", "MySQL", "Redis", "Kafka",
        "Serverless", "Asyncio", "OpenAI", "Claude", "Ollama", "DeepSeek", "API"
    }
    for tc in tech_candidates:
        if re.search(rf"\b{re.escape(tc)}\b", clean_text, re.IGNORECASE):
            found.add(tc)
            
    return found


def analyze_match(resume_text: str, jd_text: str) -> dict:
    jd_keywords = extract_keywords(jd_text)
    resume_keywords = extract_keywords(resume_text)
    
    # Normalized matching
    norm_resume = {k.lower(): k for k in resume_keywords}
    matched = []
    missing = []
    
    for k in sorted(jd_keywords, key=lambda x: x.lower()):
        if k.lower() in norm_resume or any(k.lower() in rk.lower() for rk in resume_keywords):
            matched.append(k)
        else:
            missing.append(k)
            
    total_jd = len(jd_keywords)
    matched_count = len(matched)
    
    match_score = round((matched_count / total_jd * 100), 1) if total_jd > 0 else 0.0
    
    return {
        "match_score": match_score,
        "total_jd_keywords_count": total_jd,
        "matched_count": matched_count,
        "missing_count": len(missing),
        "matched_keywords": matched,
        "missing_keywords": missing
    }


def generate_report(resume_path: str, jd_path: str, result: dict) -> str:
    score = result["match_score"]
    
    if score >= 85:
        level = "🟢 极高匹配 (S级 - 建议直接投递)"
    elif score >= 70:
        level = "🟡 良好匹配 (A级 - 微调后投递)"
    elif score >= 50:
        level = "🟠 中等匹配 (B级 - 需重点补充核心关键词)"
    else:
        level = "🔴 较低匹配 (C级 - 需按目标方向深度重构经历)"
        
    matched_tags = " ".join([f"`{k}`" for k in result["matched_keywords"][:25]])
    missing_tags = " ".join([f"`{k}`" for k in result["missing_keywords"][:25]])
    
    lines = [
        f"# ATS 简历与岗位 JD 匹配度诊断报告 (Resume-Matcher)",
        f"",
        f"- **简历文件**：`{os.path.basename(resume_path)}`",
        f"- **目标 JD**：`{os.path.basename(jd_path)}`",
        f"- **综合契合度得分**：**{score}%** ({level})",
        f"- **关键词覆盖统计**：目标 JD 提取关键词 **{result['total_jd_keywords_count']}** 个 | 简历已命中 **{result['matched_count']}** 个 | 待补齐 **{result['missing_count']}** 个",
        f"",
        f"---",
        f"",
        f"## 一、 核心关键词命中盘点 (Matched Keywords)",
        f"> 以下关键词已在您的简历中被清晰识别，能够顺利通过企业 ATS 系统的首轮机器筛选：",
        f"",
        f"{matched_tags if matched_tags else '*(暂无完全一致的关键词)*'}",
        f"",
        f"---",
        f"",
        f"## 二、 关键缺失词与强化清单 (Missing Keywords)",
        f"> 以下为目标 JD 强调但简历中未明确体现的技术/业务关键词：",
        f"",
        f"{missing_tags if missing_tags else '*(无明显缺失词，关键词覆盖极佳！)*'}",
        f"",
        f"---",
        f"",
        f"## 三、 逐段针对性优化建议 (Actionable Suggestions)",
        f"",
        f"1. **个人优势 / 技术栈前置**：",
        f"   - 建议在简历开头的【核心技能】栏中，将缺失列表中属于您掌握范围的关键词（如 {missing_tags.split()[:4] if missing_tags else '相关技术'}）直接补充列出；",
        f"2. **项目经历 STAR 子弹条植入**：",
        f"   - 检查最相关的重点项目，在 Action（核心行动）中将缺失的技术名词（如框架、协议或工程方法）替换模糊动词；",
        f"3. **ATS 机器过筛策略**：",
        f"   - 建议重点保留大小写规范（例如 `FastMCP` 而非 `fastmcp`，`RAG` 而非 `rag`），机器分词解析准确率更高。",
        f""
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Resume and JD Semantic Matcher")
    parser.add_argument("resume", help="Path to resume file (.md or text)")
    parser.add_argument("jd", help="Path to JD file or raw string")
    parser.add_argument("-o", "--output", help="Path to output markdown report", default=None)
    
    args = parser.parse_args()
    
    resume_path = Path(args.resume)
    if not resume_path.exists():
        print(f"Error: Resume file not found at {args.resume}", file=sys.stderr)
        sys.exit(1)
        
    with open(resume_path, "r", encoding="utf-8", errors="ignore") as f:
        resume_text = f.read()
        
    jd_path = Path(args.jd)
    if jd_path.exists():
        with open(jd_path, "r", encoding="utf-8", errors="ignore") as f:
            jd_text = f.read()
    else:
        # treat as raw text
        jd_text = args.jd
        
    result = analyze_match(resume_text, jd_text)
    report = generate_report(str(resume_path), str(args.jd), result)
    
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"REPORT_GENERATED: {out_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
