"""
Resume to PDF Converter for resume-tailor Skill
Converts tailored Markdown resumes to polished, professional PDF resumes using Headless Chrome/Edge.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
import markdown

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  @page {{
    size: A4 portrait;
    margin: 12mm 15mm 12mm 15mm;
  }}
  *, *::before, *::after {{
    box-sizing: border-box;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "WenQuanYi Micro Hei", sans-serif;
    color: #1e293b;
    background-color: #ffffff;
    line-height: 1.5;
    font-size: 13px;
    margin: 0;
    padding: 0;
    -webkit-font-smoothing: antialiased;
  }}

  /* Header Styling */
  h1 {{
    font-size: 20px;
    font-weight: 700;
    color: #0f172a;
    margin: 0 0 6px 0;
    letter-spacing: 0.5px;
    text-align: center;
  }}
  
  /* Contact Bar */
  p:first-of-type {{
    text-align: center;
    color: #475569;
    font-size: 12px;
    margin: 0 0 10px 0;
  }}
  
  hr {{
    border: none;
    border-top: 1.5px solid #cbd5e1;
    margin: 8px 0 12px 0;
  }}

  /* Section Titles (H2) */
  h2 {{
    font-size: 14px;
    font-weight: 700;
    color: #0f172a;
    margin: 12px 0 6px 0;
    padding-bottom: 3px;
    border-bottom: 2px solid #2563eb;
    letter-spacing: 0.5px;
  }}

  /* Subheadings (Company / Project - H3) */
  h3 {{
    font-size: 13.5px;
    font-weight: 600;
    color: #1e293b;
    margin: 8px 0 2px 0;
  }}

  em {{
    font-style: normal;
    color: #64748b;
    font-size: 12px;
    font-weight: 500;
  }}

  /* Lists and Bullet Points */
  ul {{
    margin: 3px 0 6px 0;
    padding-left: 18px;
  }}
  li {{
    margin-bottom: 3.5px;
    color: #334155;
    text-align: justify;
  }}
  li strong {{
    color: #0f172a;
    font-weight: 600;
  }}

  /* Text inside paragraphs */
  p {{
    margin: 3px 0 5px 0;
    text-align: justify;
  }}

  /* Tables if present */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0;
    font-size: 12px;
  }}
  th, td {{
    border: 1px solid #e2e8f0;
    padding: 5px 8px;
    text-align: left;
  }}
  th {{
    background-color: #f8fafc;
    font-weight: 600;
    color: #0f172a;
  }}

  /* Code blocks & tags */
  code {{
    background-color: #f1f5f9;
    color: #0f172a;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 11.5px;
    font-family: Consolas, Monaco, "Courier New", monospace;
  }}

  /* Avoid awkward page break splits */
  h2, h3 {{
    break-after: avoid;
    page-break-after: avoid;
  }}

  .block {{
    break-inside: avoid;
    page-break-inside: avoid;
  }}

  @media print {{
    body {{
      background: none;
    }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""

def find_browser_executable() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("Neither Google Chrome nor Microsoft Edge was found on this system.")


def convert_md_to_html(md_text: str) -> str:
    title_match = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "个人简历"

    html_body = markdown.markdown(
        md_text,
        extensions=["extra", "tables", "sane_lists", "nl2br"]
    )
    
    return HTML_TEMPLATE.format(title=title, body=html_body)


def export_pdf(input_md_path: str, output_pdf_path: str = None) -> str:
    input_path = Path(input_md_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input Markdown file not found: {input_path}")

    if not output_pdf_path:
        output_path = input_path.with_suffix(".pdf")
    else:
        output_path = Path(output_pdf_path).resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(input_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    html_content = convert_md_to_html(md_content)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".html", delete=False) as tmp_file:
        tmp_file.write(html_content)
        tmp_html_path = tmp_file.name

    browser_bin = find_browser_executable()
    
    try:
        cmd = [
            browser_bin,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            f"--print-to-pdf={str(output_path)}",
            tmp_html_path
        ]
        
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        
        if output_path.exists() and output_path.stat().st_size > 0:
            return str(output_path)
        else:
            raise RuntimeError("PDF creation failed: output file is empty or not created.")
    finally:
        if os.path.exists(tmp_html_path):
            try:
                os.remove(tmp_html_path)
            except OSError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export Markdown Resume to PDF")
    parser.add_argument("input", help="Path to input Markdown resume file")
    parser.add_argument("-o", "--output", help="Path to output PDF file (optional)", default=None)
    
    args = parser.parse_args()
    try:
        pdf_file = export_pdf(args.input, args.output)
        print(f"SUCCESS_PDF: {pdf_file}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
