from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.validate_contract import validate_case

SAMPLE = json.loads((ROOT / "examples" / "synthetic_case.json").read_text(encoding="utf-8"))


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.case = copy.deepcopy(SAMPLE)

    def assertInvalid(self, message_part: str):
        result = validate_case(self.case)
        self.assertTrue(any(message_part in error for error in result), result)

    def test_synthetic_example_passes(self):
        self.assertEqual(validate_case(self.case), [])

    def test_critical_claim_missing_is_rejected(self):
        self.case["recommendations"][0]["critical_claim_ids"] = []
        self.assertInvalid("omitted from critical_claim_ids")

    def test_unknown_source_is_rejected(self):
        self.case["claims"][0]["evidence_ids"].append("EV-MISSING")
        self.assertInvalid("unknown evidence ID")

    def test_same_id_in_different_groups_is_rejected(self):
        self.case["job_requirements"][0]["requirement_id"] = "EV-JD-001"
        self.assertInvalid("DUPLICATE ID")

    def test_synthetic_verified_claim_is_rejected(self):
        self.case["claims"][0]["review_status"] = "verified"
        self.assertInvalid("synthetic case cannot contain verified")

    def test_text_match_does_not_support_verified_claim(self):
        self.case["synthetic_only"] = False
        for ev in self.case["evidence"]:
            ev["synthetic"] = False
            ev["source_type"] = "company_job"
            ev["source_url"] = "https://example.org/fictional-illustration"
        self.case["claims"][0]["review_status"] = "verified"
        self.assertInvalid("requires substantive_reviewed")

    def test_provisional_cannot_require_irreversible_cost(self):
        self.case["recommendations"][0]["requires_high_cost_action"] = True
        self.assertInvalid("must be low-cost and reversible")

    def test_provisional_cannot_be_irreversible(self):
        self.case["recommendations"][0]["reversible"] = False
        self.assertInvalid("must be low-cost and reversible")

    def test_ready_advice_does_not_inherit_text_match(self):
        self.case["recommendations"][0]["status"] = "ready_for_client_decision"
        self.assertInvalid("synthetic case cannot publish ready")

    def test_unassessed_is_not_zero(self):
        self.case["capability_observations"][0]["assessment_stage"] = "unassessed"
        self.case["capability_observations"][0]["level"] = 0
        self.assertInvalid("cannot be promoted")

    def test_forecast_cannot_be_verified_as_future_fact(self):
        self.case["claims"][0]["claim_type"] = "forecast_scenario"
        self.case["claims"][0]["review_status"] = "verified"
        self.case["claims"][0]["scenario_assumptions"] = ["仅为预测"]
        self.assertInvalid("forecasts are scenarios")

    def test_forecast_needs_assumptions(self):
        self.case["claims"][0]["claim_type"] = "forecast_scenario"
        self.assertInvalid("requires scenario_assumptions")

    def test_retrieval_date_cannot_be_after_snapshot(self):
        self.case["evidence"][0]["retrieved_on"] = "2030-01-01"
        self.assertInvalid("cannot be after scope.as_of_date")

    def test_review_date_cannot_precede_snapshot(self):
        self.case["recommendations"][0]["review_on"] = "2020-01-01"
        self.assertInvalid("cannot precede case")

    def test_incomplete_advice_cannot_be_released_as_ready(self):
        self.case["synthetic_only"] = False
        for ev in self.case["evidence"]:
            ev["synthetic"] = False
            ev["source_type"] = "company_job"
            ev["source_url"] = "https://example.org/fictional-illustration"
        self.case["recommendations"][0]["status"] = "ready_for_client_decision"
        self.assertInvalid("hard gate not cleared")
        self.assertInvalid("personal constraints/preferences must be confirmed")
        self.assertInvalid("critical claim")

    def test_confirmed_hard_gate_requires_reviewed_real_evidence(self):
        req = self.case["job_requirements"][0]
        req["requirement_type"] = "hard_gate"
        req["gate_status"] = "confirmed"
        self.assertInvalid("confirmed hard gate requires")

    def test_trend_cannot_use_two_copies_of_one_upstream(self):
        self.case["synthetic_only"] = False
        sources = self.case["evidence"]
        for source in sources:
            source["synthetic"] = False
            source["source_type"] = "research"
            source["source_url"] = "https://example.org/test-fixture"
            source["review_stage"] = "substantive_reviewed"
            source["upstream_id"] = "SAME_ORIGINAL"
        claim = self.case["claims"][0]
        claim["claim_type"] = "market_trend"
        claim["review_status"] = "verified"
        claim["evidence_ids"] = ["EV-JD-001", "EV-SELF-001"]
        self.assertInvalid("needs >=2 distinct reviewed upstream sources")

    def test_ready_recommendation_cannot_include_synthetic_claim_even_noncritical(self):
        self.case["synthetic_only"] = False
        first = self.case["evidence"][0]
        first["synthetic"] = False
        first["source_type"] = "company_job"
        first["source_url"] = "https://example.org/test-fixture"
        first["review_stage"] = "substantive_reviewed"
        self.case["claims"][0]["review_status"] = "verified"
        rec = self.case["recommendations"][0]
        rec.update({"status": "ready_for_client_decision", "hard_gate_status": "cleared",
                    "personal_constraints_status": "confirmed", "preferences_confirmed": True,
                    "counterevidence_reviewed": True})
        self.assertInvalid("cannot depend on synthetic evidence")

    def test_invalid_date_rejected_by_schema(self):
        self.case["scope"]["as_of_date"] = "2026-25-99"
        self.assertInvalid("SCHEMA scope.as_of_date")


if __name__ == "__main__":
    unittest.main()
