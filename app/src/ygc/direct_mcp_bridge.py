"""Desktop stdio MCP bridge to the running local YGC experiment. No inference API."""
import argparse
import json
import os
import sys
from urllib.parse import urlsplit
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8000/api/experiments/direct/mcp')
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != '/api/experiments/direct/mcp'):
        parser.error('Use the local YGC MCP endpoint only')
    token = os.environ.get('YGC_EXPERIMENT_TOKEN', '')
    if not token or len(token) > 128 or not token.isascii() or not token.isprintable():
        parser.error('Set YGC_EXPERIMENT_TOKEN from the Browser Console experiment')
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False,
                      headers={'Authorization':'Bearer '+token, 'Accept':'application/json, text/event-stream'}) as client:
        for line in sys.stdin:
            message = None
            try:
                if len(line) > 100_000:
                    raise ValueError('Request too large')
                message = json.loads(line)
                response = client.post(args.url, json=message)
                response.raise_for_status()
                if response.status_code == 202:
                    continue
                reply = response.json()
            except (ValueError, httpx.HTTPError):
                if isinstance(message, dict) and 'id' not in message:
                    continue
                reply = {'jsonrpc':'2.0', 'id':message.get('id') if isinstance(message, dict) else None,
                         'error':{'code':-32603,'message':'Local YGC unavailable; check server and experiment token.'}}
            print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
