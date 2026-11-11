from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent

class InteractionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        cls.manual = (ROOT / '职业咨询操作手册.md').read_text(encoding='utf-8')
        cls.tests = json.loads((ROOT / 'tests' / 'interaction_cases.json').read_text(encoding='utf-8'))

    def test_required_rule_sections(self):
        self.assertIn('### 交互执行契约', self.skill)
        self.assertIn('### 1.3.2 交互执行契约', self.manual)
        self.assertIn('按需提问', self.skill)
        self.assertIn('开放式', self.manual)
        self.assertIn('停止追问', self.skill)
        self.assertIn('先交付最小价值', self.manual)

    def test_scenarios_cover_observed_failures(self):
        ids = {x['id'] for x in self.tests['cases']}
        self.assertEqual(ids, {f'INT-{i:02d}' for i in range(1, 11)})
        for case in self.tests['cases']:
            with self.subTest(case=case['id']):
                for key in ('title','origin','severity','context','prompt','expected','fail_if','notes'):
                    self.assertIn(key,case)
                    self.assertTrue(case[key])
                self.assertGreaterEqual(len(case['expected']),2)
                self.assertGreaterEqual(len(case['fail_if']),2)
                self.assertIn(case['severity'],('high','medium','low'))

    def test_no_mandatory_platform_tool_name(self):
        # The generic Skill must not depend on a platform-specific question API.
        self.assertNotIn('ask_question', self.skill)
        self.assertNotIn('ask_user_question', self.skill)
        self.assertIn('工具不可用', self.skill)

    def test_manual_and_skill_crosslink_to_cases(self):
        self.assertIn('tests/INTERACTION_REGRESSION.md', self.skill)
        self.assertIn('tests/INTERACTION_REGRESSION.md', self.manual)
        self.assertTrue((ROOT / 'tests' / 'INTERACTION_REGRESSION.md').exists())

if __name__ == '__main__':
    unittest.main()
