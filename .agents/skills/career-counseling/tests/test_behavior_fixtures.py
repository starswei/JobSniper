from pathlib import Path
import json,unittest
ROOT=Path(__file__).resolve().parent.parent
DATA=json.loads((ROOT/'tests/behavior_cases.json').read_text(encoding='utf-8'))

class BehaviorFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.fixtures=DATA['cases']
    def test_eight_distinct_cases_not_claimed_run(self):
        self.assertEqual({c['id'] for c in self.fixtures},{f'E2E-{i:02d}' for i in range(1,9)})
        self.assertTrue(all(c['execution_status']=='untested' for c in self.fixtures))
    def test_each_scenario_has_independent_prompt_and_scoring(self):
        for c in self.fixtures:
            with self.subTest(case=c['id']):
                self.assertGreaterEqual(len(c['prompt']),80)
                self.assertNotEqual(c['prompt'],c['setup'])
                self.assertIn(c['execution_mode'],['single_turn','multi_turn','tool_fault_injection'])
                self.assertGreaterEqual(len(c['must_demonstrate']),3)
                self.assertGreaterEqual(len(c['fail_if']),3)
                self.assertEqual(len(c['score_dimensions']),5)
                self.assertTrue(c.get('oracle'))
    def test_new_cash_fixture_not_a_copy_of_manual_case(self):
        c=next(x for x in self.fixtures if x['id']=='E2E-04')
        v=c['oracle']; self.assertNotEqual(v['C'],24000)
        self.assertEqual(v['available_A0'],v['C']-v['B']-v['D_due']-v['K'])
        self.assertEqual(v['net_burn'],v['E']-v['I'])
        self.assertAlmostEqual(v['runway_months'],v['available_A0']/v['net_burn'])
        self.assertAlmostEqual(v['reply_rate'],v['replied']/v['matured'])
        self.assertAlmostEqual(v['interview_rate'],v['interviewed']/v['matured'])
        self.assertIn('W=21',c['prompt'])
    def test_other_oracles_are_concrete_and_consistent(self):
        c={x['id']:x for x in self.fixtures}
        self.assertEqual(c['E2E-02']['oracle']['hours_max'],8*12)
        self.assertIn('9,900',c['E2E-03']['prompt'])
        self.assertTrue(c['E2E-03']['oracle']['not_comparable'])
        a=c['E2E-06']['oracle']
        self.assertEqual(a['initial_A0'],65000-6000-2000-1000)
        self.assertEqual(a['updated_A0'],26000-6000-4000-1000)
        self.assertEqual(len(c['E2E-06']['follow_up_turns']),1)
        self.assertEqual(c['E2E-07']['oracle']['skill_delta_points'],83-55)
        self.assertGreater(c['E2E-08']['oracle']['training_fee'],c['E2E-08']['oracle']['liquid_cash'])
    def test_tool_fault_requires_real_injection_for_full_credit(self):
        c=next(x for x in self.fixtures if x['id']=='E2E-05')
        self.assertEqual(c['execution_mode'],'tool_fault_injection')
        self.assertEqual(c['tool_setup']['first_call_result'],'timeout')
        self.assertTrue(c['oracle']['real_execution_required_for_full_pass'])
        self.assertIn('真实', (ROOT/'tests/BEHAVIOR_EVALUATION.md').read_text(encoding='utf-8'))
    def test_public_tests_cannot_be_confused_with_holdout_or_live_run(self):
        self.assertIn('Public', DATA['scope'])
        self.assertIn('not a blinded holdout',DATA['scope'])
        text=json.dumps(DATA,ensure_ascii=False)
        self.assertNotIn('origin', text)
        for name in ['Open'+'Code','Anti'+'gravity']:
            self.assertNotIn(name,text)

if __name__=='__main__': unittest.main()
