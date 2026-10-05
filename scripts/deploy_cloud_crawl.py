#!/usr/bin/env python3
"""Configure a private staging Crawl Job after tests/CI/build and user secret setup.

Never reads a secret value, creates a credential or starts a Crawl. The default
Job checks database connectivity only. Explicit probes perform read-only Reverb
requests. Run the Web deployment separately after this setup succeeds.
"""
import argparse
import json
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True);parser.add_argument('--region',required=True);parser.add_argument('--image',required=True)
    parser.add_argument('--reverb-secret-version',default='1');args=parser.parse_args()
    # This rollout helper deliberately cannot target production/arbitrary resources.
    project=args.project;region=args.region
    if project!='your-guitar-chronicle-staging' or region!='asia-northeast1' or not args.image.startswith('asia-northeast1-docker.pkg.dev/'+project+'/ygc-staging/account-api@sha256:') or not args.reverb_secret_version.isdigit():parser.error('Explicit staging immutable image and secret version required.')
    def cli(*parts):
        result=subprocess.run(['gcloud',*parts,'--project='+project],capture_output=True,text=True)
        if result.returncode:raise RuntimeError('GCP setup failed: '+' '.join(parts[:3]))
        return result.stdout.strip()
    def exists(*parts):
        result=subprocess.run(['gcloud',*parts,'--project='+project,'--format=value(name)'],capture_output=True,text=True)
        if result.returncode==0:return True
        if 'NOT_FOUND' in result.stderr or 'not found' in result.stderr:return False
        raise RuntimeError('Resource status unavailable.')
    # Missing user-supplied credential stops all IAM/resource mutations.
    if cli('secrets','versions','describe',args.reverb_secret_version,'--secret=ygc-staging-reverb-token','--format=value(state)')!='ENABLED':raise RuntimeError('Reverb secret version must be enabled.')
    role=json.loads(cli('iam','roles','describe','ygcBackupJobRunner','--format=json(includedPermissions)'))
    if set(role['includedPermissions'])!={'run.jobs.run','run.jobs.runWithOverrides','run.executions.get'}:raise RuntimeError('Existing runner role differs; refusing overwrite.')
    sa='ygc-staging-crawl@'+project+'.iam.gserviceaccount.com'
    if not exists('iam','service-accounts','describe',sa):cli('iam','service-accounts','create','ygc-staging-crawl','--display-name=YGC staging Reverb Crawl','--format=value(email)')
    cli('projects','add-iam-policy-binding',project,'--member=serviceAccount:'+sa,'--role=roles/cloudsql.client','--condition=None','--quiet','--format=value(version)')
    for secret in ('ygc-staging-db-password','ygc-staging-reverb-token'):
        cli('secrets','add-iam-policy-binding',secret,'--member=serviceAccount:'+sa,'--role=roles/secretmanager.secretAccessor','--quiet','--format=value(version)')
    cli('storage','buckets','add-iam-policy-binding','gs://'+project+'-content','--member=serviceAccount:'+sa,'--role=roles/storage.objectUser','--quiet','--format=value(version)')
    job='ygc-staging-reverb-crawl';operation='update' if exists('run','jobs','describe',job,'--region='+region) else 'create'
    cli('run','jobs',operation,job,'--region='+region,'--image='+args.image,'--service-account='+sa,'--command=python','--args=-m,ygc.cloud_crawl_job,--confirm-project='+project+',--check-only','--set-cloudsql-instances='+project+':'+region+':ygc-staging-db','--set-env-vars=YGC_GCP_PROJECT_ID='+project+',YGC_PLATFORM_TARGET=gcp,YGC_MEDIA_BACKEND=gcs,YGC_DATABASE_BACKEND=postgres,YGC_CONTENT_BUCKET='+project+'-content,YGC_ACCOUNTS_BUCKET='+project+'-accounts,YGC_POSTGRES_HOST=/cloudsql/'+project+':'+region+':ygc-staging-db,YGC_POSTGRES_USER=ygc_app,YGC_POSTGRES_PREFIX=ygc_','--set-secrets=YGC_POSTGRES_PASSWORD=ygc-staging-db-password:1,REVERB_API_TOKEN=ygc-staging-reverb-token:'+args.reverb_secret_version,'--tasks=1','--parallelism=1','--max-retries=0','--task-timeout=900s','--cpu=1','--memory=512Mi','--quiet','--format=value(metadata.name)')
    for member,role in [('ygc-staging-app','projects/'+project+'/roles/ygcBackupJobRunner'),('ygc-staging-scheduler','projects/'+project+'/roles/ygcBackupJobRunner')]:
        cli('run','jobs','add-iam-policy-binding',job,'--region='+region,'--member=serviceAccount:'+member+'@'+project+'.iam.gserviceaccount.com','--role='+role,'--quiet','--format=value(version)')
    name='ygc-staging-reverb-crawl';operation='update' if exists('scheduler','jobs','describe',name,'--location='+region) else 'create'
    cli('scheduler','jobs',operation,'http',name,'--location='+region,'--schedule=0 * * * *','--time-zone=Asia/Tokyo','--uri=https://run.googleapis.com/v2/projects/'+project+'/locations/'+region+'/jobs/'+job+':run','--http-method=POST','--oauth-service-account-email=ygc-staging-scheduler@'+project+'.iam.gserviceaccount.com','--message-body={"overrides":{"containerOverrides":[{"args":["-m","ygc.cloud_crawl_job","--confirm-project='+project+'","--scheduled"]}]}}','--headers=Content-Type=application/json','--attempt-deadline=30s','--max-retry-attempts=0','--quiet','--format=value(name)')
    print('Private Crawl Job configured; default checks only. Existing Auto Crawl and service mode remain unchanged.')


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Crawl setup stopped. Verify the enabled user-supplied secret and resource permissions; no secret value was read or printed.') from None
