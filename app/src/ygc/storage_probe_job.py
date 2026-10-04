"""IAM-only Cloud Storage write/read/delete check. Never served as an HTTP write API."""
import argparse
import json
import os
import sys
from ygc.cloud_storage import CloudStorage, StorageSettings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-project', required=True)
    args = parser.parse_args(argv)
    storage = None
    try:
        project = os.environ.get('YGC_GCP_PROJECT_ID', '')
        if args.confirm_project != project or os.environ.get('K_SERVICE') or os.environ.get('CLOUD_RUN_TASK_COUNT', '1') != '1':
            raise ValueError('Use a confirmed single-task Job.')
        storage = CloudStorage(StorageSettings.from_environment(project))
        print(json.dumps(storage.probe()))
        return 0
    except Exception:
        print(json.dumps({'status': 'failed'}), file=sys.stderr)
        return 1
    finally:
        if storage is not None:
            storage.close()


if __name__ == '__main__':
    raise SystemExit(main())
