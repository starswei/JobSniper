from pathlib import Path
import copy, json, unittest, sys
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tools'))
from validate_runtime import validate_runtime

def load(path): return json.loads((ROOT/path).read_text(encoding='utf-8'))

class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest=load('examples/synthetic_capability_manifest.json')
        self.state=load('examples/synthetic_execution_state.json')

    def test_valid_synthetic_examples(self):
        self.assertEqual(validate_runtime(self.manifest,'manifest'),[])
        self.assertEqual(validate_runtime(self.state,'state'),[])

    def test_duplicate_capability_names_blocked(self):
        x=copy.deepcopy(self.manifest)
        x['capabilities'].append(copy.deepcopy(x['capabilities'][0]))
        x['capabilities'][-1]['limits']='同名但不同限制'
        self.assertIn('duplicate capability name', ' '.join(validate_runtime(x,'manifest')))

    def test_authorization_mode_consistency(self):
        x=copy.deepcopy(self.manifest)
        x['capabilities'][2]['requires_authorization']=False
        self.assertIn('auth-required', ' '.join(validate_runtime(x,'manifest')))

    def test_unexpected_capability_is_rejected(self):
        x=copy.deepcopy(self.manifest)
        x['capabilities'][0]['name']='automated_job_application'
        self.assertTrue(validate_runtime(x,'manifest'))

    def test_synthetic_cannot_release_ready(self):
        x=copy.deepcopy(self.state)
        x.update(recommendation_state='ready_for_client_decision',hard_gate='cleared',high_cost_action=False,
                 critical_evidence_reviewed=True,counterevidence_reviewed=True,
                 personal_constraints_confirmed=True,preferences_confirmed=True)
        self.assertIn('synthetic', ' '.join(validate_runtime(x,'state')))

    def test_high_cost_unknown_gate_is_blocked(self):
        x=copy.deepcopy(self.state); x['recommendation_state']='provisional'
        errs=' '.join(validate_runtime(x,'state'))
        self.assertIn('high-cost', errs)
        self.assertIn('hard gate', errs)

    def test_ready_requires_every_precondition(self):
        x=copy.deepcopy(self.state)
        x.update(synthetic=False,high_cost_action=False,hard_gate='cleared',recommendation_state='ready_for_client_decision')
        errs=' '.join(validate_runtime(x,'state'))
        for key in ['critical_evidence_reviewed','counterevidence_reviewed','personal_constraints_confirmed','preferences_confirmed']:
            self.assertIn(key,errs)

    def test_ask_user_must_have_missing_user_fact(self):
        x=copy.deepcopy(self.state)
        x.update(action='ask_user',personal_information='sufficient')
        self.assertIn('ask_user', ' '.join(validate_runtime(x,'state')))

    def test_done_requires_explicit_stop(self):
        x=copy.deepcopy(self.state)
        x.update(action='done',research_stop_reason='none')
        self.assertIn('stop reason', ' '.join(validate_runtime(x,'state')))

    def test_enhanced_requires_real_capability_use(self):
        x=copy.deepcopy(self.state)
        x.update(mode='enhanced',used_capabilities=[])
        self.assertIn('enhanced mode', ' '.join(validate_runtime(x,'state')))

    def test_duplicate_events_blocked(self):
        x=copy.deepcopy(self.state)
        x['events'].append(copy.deepcopy(x['events'][0]))
        self.assertIn('duplicate event IDs', ' '.join(validate_runtime(x,'state')))

    def test_invalid_event_and_future_tool_name_rejected(self):
        x=copy.deepcopy(self.state)
        x['events'][0]['kind']='fictional_ai_tool'
        self.assertTrue(validate_runtime(x,'state'))

    def test_failed_tool_cannot_mark_substantively_reviewed(self):
        x=copy.deepcopy(self.state)
        x['events'][0]['verification_level']='substantive_reviewed'
        self.assertIn('unsuccessful event', ' '.join(validate_runtime(x,'state')))

    def test_enhanced_requires_success_event_not_just_list(self):
        x=copy.deepcopy(self.state)
        x['mode']='enhanced'; x['used_capabilities']=['research']
        self.assertIn('succeeded tool_call', ' '.join(validate_runtime(x,'state')))
        x['events'].append({'event_id':'SYN-2','kind':'tool_call','outcome':'succeeded',
            'capability':'research','description':'合成示例中的工具调用，非现实动作',
            'timestamp':'2026-11-11T09:00:01Z','verification_level':'unverified'})
        self.assertEqual(validate_runtime(x,'state'),[])

if __name__=='__main__': unittest.main()
