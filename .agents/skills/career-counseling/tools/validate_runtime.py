"""Validate optional capability and execution snapshots (structure + deterministic gates only).

Cannot check truth of public facts, permissions in external accounts, or actual Agent behavior.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

ROOT=Path(__file__).resolve().parent.parent
SCHEMAS={
 'manifest':json.loads((ROOT/'contracts/capability_manifest.schema.json').read_text(encoding='utf-8')),
 'state':json.loads((ROOT/'contracts/execution_state.schema.json').read_text(encoding='utf-8'))}

def validate_runtime(data, kind):
    if kind not in SCHEMAS: return ['unknown kind']
    errors=[]
    for issue in Draft202012Validator(SCHEMAS[kind],format_checker=FormatChecker()).iter_errors(data):
        path='.'.join(map(str,issue.absolute_path)) or 'root'
        errors.append(f'SCHEMA {path}: {issue.message}')
    if errors: return errors
    if kind=='manifest':
        names=[c['name'] for c in data['capabilities']]
        if len(names)!=len(set(names)):
            errors.append('duplicate capability name')
        for c in data['capabilities']:
            if c['availability']=='requires_authorization' and not c['requires_authorization']:
                errors.append(f"{c['name']}: auth-required availability demands requires_authorization=true")
        return errors
    # Cross-field fail-closed gates.
    release=data['recommendation_state']
    if data['synthetic'] and release=='ready_for_client_decision':
        errors.append('synthetic case cannot release final advice')
    if release=='provisional' and data.get('high_cost_action',False):
        errors.append('provisional cannot contain a high-cost action')
    if release=='ready_for_client_decision':
        checks=['critical_evidence_reviewed','counterevidence_reviewed','personal_constraints_confirmed','preferences_confirmed']
        for name in checks:
            if not data.get(name,False): errors.append(f'ready recommendation requires {name}')
        if data['hard_gate']!='cleared': errors.append('ready recommendation requires cleared hard gate')
    if data['hard_gate'] in ('blocked','unknown') and data.get('high_cost_action',False) and release!='high_cost_blocked':
        errors.append('unknown/blocked hard gate with high-cost action must be blocked')
    if data['action']=='ask_user' and data['personal_information'] not in ('missing_key_fact','unknown'):
        errors.append('ask_user requires an unresolved user-specific decision fact')
    if data['action']=='done' and data.get('research_stop_reason','none')=='none':
        errors.append('done requires a stop reason')
    event_ids=[event['event_id'] for event in data['events']]
    if len(set(event_ids))!=len(event_ids): errors.append('duplicate event IDs')
    if data['mode']=='enhanced' and not data.get('used_capabilities'):
        errors.append('enhanced mode requires at least one actually used capability')
    for e in data['events']:
        if e['outcome'] in ('failed','not_attempted','declined') and e.get('verification_level')=='substantive_reviewed':
            errors.append(f"{e['event_id']}: unsuccessful event cannot be substantive_reviewed")
    if data['mode']=='enhanced':
        completed={e.get('capability') for e in data['events'] if e['kind']=='tool_call' and e['outcome']=='succeeded'}
        for capability in data.get('used_capabilities',[]):
            if capability not in completed:
                errors.append(f"enhanced mode requires succeeded tool_call event for {capability}")
    return errors

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind',choices=('manifest','state'))
    p.add_argument('path',type=Path)
    args=p.parse_args()
    try: data=json.loads(args.path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as err:
        print('INVALID:',err); return 2
    errors=validate_runtime(data,args.kind)
    if errors:
        print('INVALID:',len(errors),'error(s)')
        for e in errors: print(' -',e)
        return 1
    print('VALID: runtime structure and deterministic gates only; no external facts or permissions verified.')
    return 0

if __name__=='__main__': raise SystemExit(main())
