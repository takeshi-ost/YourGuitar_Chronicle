"""Stdio bridge using short-lived Google OIDC credentials, never an SA key."""
import argparse
import json
import subprocess
import sys
import time
import httpx
from ygc.cloud_review_identity import validate_settings


class Bridge:
    def __init__(self,url,email,*,gcloud='gcloud',client=None):
        validate_settings(url,email,'123456789012345678901')
        self.url,self.email,self.gcloud=url,email,gcloud
        self.client=client or httpx.Client(timeout=30,follow_redirects=False,trust_env=False)
        self.token=None;self.until=0
    def close(self):self.token=None;self.client.close()
    def credential(self):
        if self.token and time.monotonic()<self.until:return self.token
        result=subprocess.run([self.gcloud,'auth','print-access-token'],capture_output=True,text=True,timeout=30)
        if result.returncode:raise PermissionError('Google login required.')
        access=result.stdout.strip()
        if not access:raise PermissionError('Google login required.')
        response=self.client.post('https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/'+self.email+':generateIdToken',headers={'Authorization':'Bearer '+access},json={'audience':self.url,'includeEmail':True})
        response.raise_for_status();token=response.json().get('token')
        if not isinstance(token,str) or not 0<len(token)<=16384:raise ValueError('Invalid review credential.')
        self.token,self.until=token,time.monotonic()+3000
        return token
    def send(self,message):
        response=self.client.post(self.url+'/api/review/mcp',headers={'Authorization':'Bearer '+self.credential()},json=message)
        if response.status_code==401:self.token=None;self.until=0
        response.raise_for_status()
        return None if response.status_code==202 else response.json()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--service-account',required=True);parser.add_argument('--gcloud',default='gcloud')
    args=parser.parse_args()
    try:bridge=Bridge(args.url,args.service_account,gcloud=args.gcloud)
    except ValueError:parser.error('Use an explicit Cloud Run URL and review service account.')
    try:
        for line in sys.stdin:
            message=None
            try:
                if len(line)>100000:raise ValueError('MCP request too large.')
                message=json.loads(line)
                if not isinstance(message,dict):raise ValueError('Invalid MCP request.')
                reply=bridge.send(message)
            except Exception:
                if isinstance(message,dict) and 'id' not in message:continue
                reply=dict(jsonrpc='2.0',id=message.get('id') if isinstance(message,dict) else None,error=dict(code=-32603,message='Review connection unavailable. Check Google login and OIDC permission.'))
            if reply is not None:print(json.dumps(reply,ensure_ascii=False),flush=True)
    finally:bridge.close()


if __name__=='__main__':main()
