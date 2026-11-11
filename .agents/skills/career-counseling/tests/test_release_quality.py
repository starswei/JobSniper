from pathlib import Path
import csv, json, re, unittest
ROOT=Path(__file__).resolve().parent.parent
S=(ROOT/'SKILL.md').read_text(encoding='utf-8')
M=(ROOT/'职业咨询操作手册.md').read_text(encoding='utf-8')
R=(ROOT/'README.md').read_text(encoding='utf-8')

class ReleaseQualityTests(unittest.TestCase):
    def test_privacy_rule_and_plainly_synthetic_case(self):
        self.assertIn('不属于常规接案采集项', M)
        self.assertIn('本人主动提及',M)
        self.assertIn('完全虚构',M)
        self.assertNotIn('长期噩梦',M)
        self.assertNotIn('噩梦惊醒',M)

    def test_no_old_edition_traces_or_platform_brand(self):
        text='\n'.join((ROOT/x).read_text(encoding='utf-8') for x in [
          'SKILL.md','职业咨询操作手册.md','README.md','tests/INTERACTION_REGRESSION.md',
          'tests/interaction_cases.json','tests/behavior_cases.json'])
        for disallowed in ['承袭'+'原手册','某特定平台事故来源','origin: private']:
            self.assertNotIn(disallowed,text)
        self.assertNotIn('2026 年 11 月 10 日',''.join(M.split('### 9.6')[1:]))

    def test_verification_log_covers_all_external_manual_urls(self):
        with (ROOT/'references/verification_log_2026-11-11.csv').open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        urls=set(re.findall(r'\]\((https?://[^)]+)\)',M))
        log_urls={row['url'] for row in rows}
        self.assertEqual(urls, log_urls)
        self.assertEqual(len(rows),len(log_urls))
        for r in rows:
            self.assertEqual(r['checked_on'],'2026-11-11')
            self.assertEqual(r['historical_verification'],'not_documented')
            self.assertEqual(r['current_applicability'],'not_assessed')
            self.assertTrue(r['fields_observed'])

    def test_method_and_case_three_examples_retained(self):
        self.assertIn('### 3.17',M)
        self.assertIn('### 3.18',M)
        self.assertIn('**例 A',M)
        self.assertIn('**例 B',M)
        self.assertIn('**例 C',M)
        self.assertIn('3.19',S)
        self.assertIn('3.20',S)

    def test_independent_skill_and_optional_integration(self):
        self.assertIn('任何特定工具',S)
        self.assertIn('independent',M)
        self.assertIn('enhanced',M)
        self.assertIn('degraded',M)
        self.assertTrue((ROOT/'contracts/tool_interoperability.md').is_file())
        self.assertFalse((ROOT/'integrations').exists())

    def test_no_named_workbench_dependency_anywhere(self):
        for f in ROOT.rglob('*'):
            if f.is_file() and f.suffix.lower() in ('.md','.json','.py','.csv','.txt'):
                with self.subTest(f=f.relative_to(ROOT)):
                    content=f.read_text(encoding='utf-8-sig')
                    forbidden=['Career'+' Agent','career'+'-agent','career'+'_'+'agent']
                    for token in forbidden:
                        self.assertNotIn(token,content)

    def test_release_references_new_contracts(self):
        for name in ['capability_manifest.schema.json','execution_state.schema.json']:
            self.assertTrue((ROOT/'contracts'/name).is_file())
            self.assertIn(name,S)
        self.assertIn('tests/BEHAVIOR_EVALUATION.md',R)

if __name__=='__main__': unittest.main()
