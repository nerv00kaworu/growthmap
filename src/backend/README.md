# GrowthMap backend

This backend supports the local-first GrowthMap desktop workspace: project/tree data, governed Agent operations, local provider configuration, and development APIs. Production Personal activation is a separate licensing boundary; it does not receive desktop project databases.

## Development setup

```sh
cd src/backend
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.lock
DATABASE_URL='sqlite+aiosqlite:////absolute/path/to/growthmap.db' uvicorn main:app --host 127.0.0.1 --port 8100
```

Use an explicit local `DATABASE_URL` and back up an existing database before upgrades. Do not commit API keys. `requirements.lock` is the reviewed backend dependency lock; check the project metadata/environment rather than assuming a Python runtime version.

## Current behavior and boundaries

- Project SQLite data is local-first.
- Agent Access is a Windows-user/workspace-global master grant; individual operations still require explicit `project_id` and scoped intent. Revisions/CAS prevent stale canonical writes. SSE journal events are stale-state signals, not mutation truth or a cloud database.
- Proposal/review is the recommended mode for judgment-sensitive work. Direct collaboration needs explicit authorization.
- Agent grants do not authorize filesystem, shell, Git, deployment, credentials, payment, or general network access.
- Provider secret handling is local and must not expose secret values in API responses, logs, or documentation.

## Checks

CI uses Python 3.12, the reviewed dependency lock, a file-backed SQLite database for independent concurrent connections, and `pytest`. The R14–R24 deployment-contract modules require an external evidence bundle and run on their dedicated evidence-backed path; ordinary CI explicitly verifies and excludes only that bounded partition before running every other backend test.

```sh
python -m pip install -r requirements.lock -r packaging/requirements-test.txt
python -m compileall -q -x 'venv|__pycache__' .

export DATABASE_URL='sqlite+aiosqlite:///./ci-test.db'
ignores=""
for release in $(seq 14 24); do
  ignores="$ignores --ignore=tests/test_r${release}_deployment_contract.py"
done
python -m pytest -q $ignores
```

See [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) for the fail-closed partition checks; do not describe this as the external deployment-contract suite passing.
