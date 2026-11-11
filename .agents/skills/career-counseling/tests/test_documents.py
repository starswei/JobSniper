from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
SKILL = (ROOT / "SKILL.md").read_text(encoding="utf-8")
MANUAL = (ROOT / "职业咨询操作手册.md").read_text(encoding="utf-8")


class DocumentIntegrityTest(unittest.TestCase):
    def test_skill_frontmatter_and_links(self):
        self.assertTrue(SKILL.startswith("---\nname: career-counseling\n"))
        self.assertIn("](职业咨询操作手册.md)", SKILL)
        self.assertIn("](SKILL.md)", MANUAL)
        self.assertTrue((ROOT / "contracts" / "career_case.schema.json").is_file())

    def test_chapters_and_templates(self):
        chapters = re.findall(r'^## 第 (\d+) 章', MANUAL, re.M)
        self.assertEqual(chapters, list(map(str, range(1, 10))))
        templates = re.findall(r'^### 模板 ([A-Z])｜', MANUAL, re.M)
        self.assertEqual(templates, list("ABCDEFGHIJKLMNOPQRSTU"))

    def test_markdown_tables_are_rectangular(self):
        fence = False
        table_rows = []
        for line in MANUAL.splitlines() + [""]:
            if line.lstrip().startswith("```"):
                fence = not fence
            if not fence and line.startswith("|") and line.endswith("|"):
                n = len(re.split(r"(?<!\\)\|", line)) - 2
                table_rows.append(n)
            else:
                if table_rows:
                    self.assertEqual(len(set(table_rows)), 1, table_rows)
                    table_rows = []
        self.assertFalse(fence)

    def test_removed_wrong_cost_priority_and_kept_review_gates(self):
        self.assertNotIn("决策影响 × 不确定性 × 取证成本", MANUAL + SKILL)
        self.assertNotIn("按影响×不确定性×成本", MANUAL + SKILL)
        self.assertIn("### 3.5.2 三层审查闸门", MANUAL)
        self.assertIn("**建议层发布闸门", MANUAL)
        self.assertIn("### 2.2 用四个镜头看人", MANUAL)
        self.assertIn("四维判断：", MANUAL)
        self.assertIn("不是要求求职者一次性填写的问卷", MANUAL)


if __name__ == "__main__":
    unittest.main()
