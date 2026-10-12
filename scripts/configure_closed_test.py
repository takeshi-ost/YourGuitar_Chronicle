"""Update only the staging participant policy and optional verified image.

Dry-run by default. The private policy file is a JSON object with one key:
YGC_CLOSED_TEST_PARTICIPANTS, whose value is a JSON-encoded list of Google UIDs.
Never print that value. Preserve all other service settings and Secret refs.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/src'))
from ygc.cloud_participants import participant_subjects

PROJECT='your-guitar-chronicle-staging'
SERVICE='ygc-staging-accounts'
REGION='asia-northeast1'
KEY='YGC_CLOSED_TEST_PARTICIPANTS'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-project',required=True,choices=[PROJECT])
    parser.add_argument('--policy-file',required=True,type=Path)
    parser.add_argument('--gcloud',default='gcloud')
    parser.add_argument('--image')
    parser.add_argument('--revision-suffix')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:
        policy=json.loads(args.policy_file.read_text())
        if not isinstance(policy,dict) or set(policy)!={KEY} or not isinstance(policy[KEY],str):
            raise ValueError()
        os.environ[KEY]=policy[KEY]
        subjects=participant_subjects()
        image_prefix=REGION+'-docker.pkg.dev/'+PROJECT+'/ygc-staging/account-api@sha256:'
        if args.image and not re.fullmatch(re.escape(image_prefix)+'[0-9a-f]{64}',args.image):raise ValueError()
        if args.revision_suffix and not re.fullmatch('[a-z][a-z0-9-]{0,40}',args.revision_suffix):raise ValueError()
    except (ValueError,OSError,TypeError):
        raise SystemExit('Invalid private participant policy or deployment selection.') from None

    def cloud(parts):
        result=subprocess.run([args.gcloud,*parts,'--project='+PROJECT],capture_output=True,text=True)
        if result.returncode:raise SystemExit('Staging configuration operation failed; inspect GCP operation status before retrying.')
        return result.stdout
    service=json.loads(cloud(['run','services','describe',SERVICE,'--region='+REGION,'--format=json']))
    old=service['spec']['template']['spec']['containers'][0]
    old_value=next((e.get('value') for e in old.get('env',[]) if e['name']==KEY),None)
    previous=json.loads(old_value) if old_value is not None else None
    print(json.dumps({'project':PROJECT,'service':SERVICE,'apply':args.apply,
        'previous_participant_count':len(previous) if previous is not None else None,
        'participant_count':len(subjects),'image_change':bool(args.image and args.image!=old['image'])}))
    if not args.apply:return
    delimiter='ygc'+uuid.uuid4().hex
    parts=['run','services','update',SERVICE,'--region='+REGION,
        '--update-env-vars=^'+delimiter+'^'+KEY+'='+policy[KEY],'--quiet']
    if args.image:parts.append('--image='+args.image)
    if args.revision_suffix:parts.append('--revision-suffix='+args.revision_suffix)
    cloud(parts)
    after=json.loads(cloud(['run','services','describe',SERVICE,'--region='+REGION,'--format=json']))
    before_spec=service['spec']['template']['spec']
    after_spec=after['spec']['template']['spec']
    def without_policy(spec):
        result=json.loads(json.dumps(spec));c=result['containers'][0]
        c['env']=[e for e in c.get('env',[]) if e['name']!=KEY];c.pop('image',None)
        return result
    if without_policy(before_spec)!=without_policy(after_spec):
        raise SystemExit('Unexpected service configuration difference; inspect before any further change.')
    c=after_spec['containers'][0]
    applied=next((e.get('value') for e in c.get('env',[]) if e['name']==KEY),None)
    status=after['status'];revision=status['latestReadyRevisionName']
    if (applied!=policy[KEY] or args.image and c['image']!=args.image
            or not any(t.get('revisionName')==revision and t.get('percent')==100 for t in status.get('traffic',[]))):
        raise SystemExit('Participant configuration or ready revision traffic is not confirmed.')
    print(json.dumps({'status':'ok','revision':revision,'participant_count':len(subjects),
        'traffic_percent':100,'other_template_settings_unchanged':True}))


if __name__=='__main__':main()
