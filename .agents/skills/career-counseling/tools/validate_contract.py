"""Validate a career-counseling case snapshot.

Checks JSON Schema *and* a few cross-record decision gates. This tool does not
contact websites, assess truth, verify consent, or determine career suitability.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from datetime import date

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts" / "career_case.schema.json").read_text(encoding="utf-8"))


def validate_case(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    validator = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    schema_errors = sorted(validator.iter_errors(record), key=lambda error: (str(list(error.absolute_path)), error.message))
    for err in schema_errors:
        location = ".".join(str(p) for p in err.absolute_path) or "root"
        errors.append(f"SCHEMA {location}: {err.message}")
    if schema_errors:
        return errors

    all_records = {}
    for group, key in (("evidence", "evidence_id"), ("claims", "claim_id"),
                       ("job_requirements", "requirement_id"),
                       ("capability_observations", "observation_id"),
                       ("recommendations", "recommendation_id")):
        for item in record[group]:
            item_id = item[key]
            if item_id in all_records:
                errors.append(f"DUPLICATE ID {item_id}: present in {all_records[item_id]} and {group}")
            else:
                all_records[item_id] = group

    sources = {e["evidence_id"]: e for e in record["evidence"]}
    claims = {c["claim_id"]: c for c in record["claims"]}
    synthetic_only = record["synthetic_only"]
    as_of = date.fromisoformat(record["scope"]["as_of_date"])

    for ev in record["evidence"]:
        eid = ev["evidence_id"]
        if date.fromisoformat(ev["retrieved_on"]) > as_of:
            errors.append(f"{eid}: retrieved_on cannot be after scope.as_of_date")
        if ev.get("published_on") and ev["published_on"] > ev["retrieved_on"]:
            errors.append(f"{eid}: published_on cannot be after retrieved_on")
        if synthetic_only and (not ev["synthetic"] or ev["source_type"] != "synthetic"):
            errors.append(f"{eid}: synthetic_only case must contain only synthetic evidence")
        if ev["synthetic"] and ev["review_stage"] == "substantive_reviewed":
            errors.append(f"{eid}: synthetic source cannot be marked substantive_reviewed")
        if not ev["synthetic"] and ev["source_type"] == "synthetic":
            errors.append(f"{eid}: non-synthetic evidence cannot use synthetic source_type")
        if ev["source_type"] not in ("user_material", "synthetic"):
            url = ev["source_url"]
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                errors.append(f"{eid}: public external evidence requires an http(s) source_url")

    for claim in record["claims"]:
        cid = claim["claim_id"]
        for eid in claim["evidence_ids"] + claim["counterevidence_ids"]:
            if eid not in sources:
                errors.append(f"{cid}: unknown evidence ID {eid}")
        if claim["claim_type"] == "forecast_scenario":
            if claim["review_status"] == "verified":
                errors.append(f"{cid}: forecasts are scenarios, never verified future facts")
            if not claim.get("scenario_assumptions"):
                errors.append(f"{cid}: forecast_scenario requires scenario_assumptions")
        if claim["review_status"] == "verified":
            if synthetic_only:
                errors.append(f"{cid}: synthetic case cannot contain verified real-world claims")
            reviewed = [sources[eid] for eid in claim["evidence_ids"] if eid in sources
                        and sources[eid]["review_stage"] == "substantive_reviewed"
                        and not sources[eid]["synthetic"]]
            if not reviewed:
                errors.append(f"{cid}: verified claim requires substantive_reviewed non-synthetic evidence")
            if claim["claim_type"] in ("market_trend", "causal_inference"):
                upstreams = {e["upstream_id"] for e in reviewed}
                if len(upstreams) < 2:
                    errors.append(f"{cid}: market trend or causal inference needs >=2 distinct reviewed upstream sources; human methodology review remains necessary")

    for req in record["job_requirements"]:
        if req["evidence_id"] not in sources:
            errors.append(f"{req['requirement_id']}: unknown evidence ID {req['evidence_id']}")
        if req["requirement_type"] == "hard_gate" and req["gate_status"] == "confirmed":
            ev = sources.get(req["evidence_id"])
            if not ev or ev["synthetic"] or ev["review_stage"] != "substantive_reviewed":
                errors.append(f"{req['requirement_id']}: confirmed hard gate requires substantive_reviewed real evidence")

    for obs in record["capability_observations"]:
        oid = obs["observation_id"]
        for eid in obs["evidence_ids"]:
            if eid not in sources:
                errors.append(f"{oid}: unknown evidence ID {eid}")
        if obs["assessment_stage"] in ("unassessed", "self_report") and obs["level"] is not None:
            errors.append(f"{oid}: unassessed/self_report cannot be promoted to a numeric assessed level")
        if obs["assessment_stage"] in ("work_sample_reviewed", "independently_assessed") and obs["level"] is None:
            errors.append(f"{oid}: assessed skill observation requires a level")
        if obs["assessment_stage"] == "independently_assessed":
            supporting = [sources[eid] for eid in obs["evidence_ids"] if eid in sources]
            if not supporting or not any(not e["synthetic"] and e["review_stage"] == "substantive_reviewed" for e in supporting):
                errors.append(f"{oid}: independently_assessed requires reviewed, non-synthetic evidence")

    for rec in record["recommendations"]:
        rid = rec["recommendation_id"]
        used_ids = set(rec["claim_ids"])
        for cid in rec["claim_ids"] + rec["critical_claim_ids"]:
            if cid not in claims:
                errors.append(f"{rid}: unknown claim ID {cid}")
        if not set(rec["critical_claim_ids"]).issubset(used_ids):
            errors.append(f"{rid}: critical_claim_ids must be within claim_ids")
        for cid in used_ids:
            if cid in claims and claims[cid]["critical_to_decision"] and cid not in rec["critical_claim_ids"]:
                errors.append(f"{rid}: critical claim {cid} omitted from critical_claim_ids")
        if date.fromisoformat(rec["review_on"]) < as_of:
            errors.append(f"{rid}: review_on cannot precede case as_of_date")
        if rec["status"] == "provisional":
            if rec["requires_high_cost_action"] or not rec["reversible"]:
                errors.append(f"{rid}: provisional recommendation must be low-cost and reversible")
        if rec["status"] == "ready_for_client_decision":
            if synthetic_only:
                errors.append(f"{rid}: synthetic case cannot publish ready_for_client_decision advice")
            if not rec["critical_claim_ids"]:
                errors.append(f"{rid}: ready recommendation requires at least one critical claim")
            if rec["hard_gate_status"] != "cleared":
                errors.append(f"{rid}: hard gate not cleared")
            if rec["personal_constraints_status"] != "confirmed" or not rec["preferences_confirmed"]:
                errors.append(f"{rid}: personal constraints/preferences must be confirmed")
            if not rec["counterevidence_reviewed"]:
                errors.append(f"{rid}: counterevidence review is required")
            for cid in rec["critical_claim_ids"]:
                if cid in claims and claims[cid]["review_status"] != "verified":
                    errors.append(f"{rid}: critical claim {cid} is not verified; recommendation cannot be ready")
            for cid in rec["claim_ids"]:
                if cid in claims and any(
                    eid in sources and sources[eid]["synthetic"]
                    for eid in claims[cid]["evidence_ids"]
                ):
                    errors.append(f"{rid}: ready recommendation cannot depend on synthetic evidence, even as a noncritical claim")
        if rec["status"] == "high_cost_blocked" and not rec["requires_high_cost_action"]:
            errors.append(f"{rid}: high_cost_blocked must identify a high-cost action")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_json", type=Path, help="Path to a case snapshot JSON file")
    args = parser.parse_args()
    try:
        record = json.loads(args.case_json.read_text(encoding="utf-8"))
        errors = validate_case(record)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"INVALID: {exc}")
        return 2
    if errors:
        print(f"INVALID: {len(errors)} error(s)")
        for msg in errors:
            print(f" - {msg}")
        return 1
    print("VALID: structural and cross-reference checks passed; external claims are NOT fact-checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
