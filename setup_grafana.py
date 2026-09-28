#!/usr/bin/env python3
"""
setup_grafana.py

Idempotently ensures the Grafana-side prerequisites exist: the Jira
datasource, the TPMO1 dashboard folder, and discovers the stack's built-in
TestData datasource uid. Safe to re-run -- finds and reuses existing
resources by name rather than creating duplicates.

Prints `export VAR=value` lines to stdout for JIRA_DATASOURCE_UID,
GRAFANA_FOLDER_UID, and TESTDATA_DATASOURCE_UID. setup.sh sources this
script's output so build_dashboards.py picks up the right uids for
whichever stack it's run against.

Uses `gcx` (must already be logged in) rather than direct HTTP, since gcx
already carries this session's auth/context.

Uses the same Jira env vars as jira.py, for the datasource's own config.
"""

import json
import os
import subprocess
import sys

FOLDER_TITLE = "TPMO1 Transformation Portfolio"
DATASOURCE_NAME = "Jira (TPMO1 demo)"


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def gcx(*args, input_data=None):
    proc = subprocess.run(["gcx", *args], input=input_data, capture_output=True, text=True)
    if proc.returncode != 0:
        die(f"gcx {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    # gcx prints a one-line hint before the JSON payload on plain `api` calls
    lines = proc.stdout.strip().splitlines()
    if lines and lines[0].startswith("{\"class\":\"hint\""):
        lines = lines[1:]
    return json.loads("\n".join(lines)) if lines else {}


def find_folder():
    results = gcx("api", "/api/search?type=dash-folder", "-o", "json")
    return next((f for f in results if f.get("title") == FOLDER_TITLE), None)


def ensure_folder():
    existing = find_folder()
    if existing:
        print(f"# folder '{FOLDER_TITLE}' already exists", file=sys.stderr)
        return existing["uid"]
    created = gcx("api", "/api/folders", "-d", json.dumps({"title": FOLDER_TITLE}), "-o", "json")
    print(f"# created folder '{FOLDER_TITLE}'", file=sys.stderr)
    return created["uid"]


def find_datasource():
    results = gcx("api", "/api/datasources", "-o", "json")
    return next((d for d in results if d.get("name") == DATASOURCE_NAME), None)


def ensure_jira_datasource():
    missing = [v for v in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN") if not os.environ.get(v)]
    if missing:
        die(f"Missing env vars needed for the Jira datasource: {', '.join(missing)}. Source envvars first.")

    payload = {
        "name": DATASOURCE_NAME,
        "type": "grafana-jira-datasource",
        "access": "proxy",
        "basicAuth": False,
        "jsonData": {
            "url": os.environ["JIRA_BASE_URL"],
            "user": os.environ["JIRA_EMAIL"],
            "hosting": "cloud",
            "scopedToken": False,
        },
        "secureJsonData": {"token": os.environ["JIRA_API_TOKEN"]},
    }

    existing = find_datasource()
    if existing:
        # Reusing a datasource created by a PREVIOUS run (possibly a
        # different person's Jira account/token entirely -- this asset is
        # meant to be handed to a new SE with their own site and token each
        # time) without refreshing its credentials leaves it silently
        # authenticated as whoever set it up originally. Confirmed live:
        # this exact staleness produced clean HTTP 200s with empty data on
        # every query (not an error), only surfaced by the datasource's own
        # health check reporting 401. Always re-PUT the current env's
        # credentials onto it rather than trusting it's still valid.
        gcx("api", f"/api/datasources/uid/{existing['uid']}", "-X", "PUT", "-d", json.dumps(payload), "-o", "json")
        print(f"# datasource '{DATASOURCE_NAME}' already existed -- refreshed its credentials/url from "
              f"the current environment", file=sys.stderr)
        return existing["uid"]

    created = gcx("api", "/api/datasources", "-d", json.dumps(payload), "-o", "json")
    print(f"# created datasource '{DATASOURCE_NAME}'", file=sys.stderr)
    return created["datasource"]["uid"]


def find_testdata_datasource():
    results = gcx("api", "/api/datasources", "-o", "json")
    match = next((d for d in results if d.get("type") == "grafana-testdata-datasource"), None)
    if not match:
        die("No grafana-testdata-datasource found on this stack -- it's built-in and should always exist; "
            "check the stack is fully provisioned.")
    return match["uid"]


def main():
    folder_uid = ensure_folder()
    jira_ds_uid = ensure_jira_datasource()
    testdata_uid = find_testdata_datasource()

    print(f"export GRAFANA_FOLDER_UID={folder_uid}")
    print(f"export JIRA_DATASOURCE_UID={jira_ds_uid}")
    print(f"export TESTDATA_DATASOURCE_UID={testdata_uid}")


if __name__ == "__main__":
    main()
