#!/usr/bin/env python3
"""
check_setup.py

Run this FIRST, before setup.sh, whenever this is being set up on a new
Grafana Cloud stack / Jira site, or whenever something in the pipeline is
failing and it's unclear which half (Grafana/gcx or Jira) is the problem.

Checks both halves independently and reports exactly what's missing,
rather than letting a downstream script fail with a confusing error two
layers removed from the actual cause. Read-only throughout -- never
creates, modifies, or deletes anything.

Usage:
    source envvars   # or set JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN/JIRA_PROJECT_KEY yourself
    python3 check_setup.py
"""

import json
import os
import shutil
import subprocess
import sys

import requests

OK = "  OK  "
FAIL = "FAILED"

REQUIRED_PLUGINS = [
    "grafana-jira-datasource",       # Enterprise plugin, needs Cloud Pro/Advanced or Enterprise license
    "grafana-graphviz-panel",        # Enterprise plugin, same licensing requirement
    "grafana-testdata-datasource",   # built-in, should always be present
]

problems = []


def report(ok, label, detail="", blocking=True):
    tag = OK if ok else FAIL
    print(f"[{tag}] {label}" + (f" -- {detail}" if detail else ""))
    if not ok and blocking:
        problems.append(label)


def section(title):
    print(f"\n--- {title} ---")


# ---------------------------------------------------------------------------
# Grafana / gcx side
# ---------------------------------------------------------------------------

def gcx_json(*args):
    proc = subprocess.run(["gcx", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        return None, (proc.stderr.strip() or proc.stdout.strip())
    lines = proc.stdout.strip().splitlines()
    if lines and lines[0].startswith('{"class":"hint"'):
        lines = lines[1:]
    try:
        return (json.loads("\n".join(lines)) if lines else {}), None
    except json.JSONDecodeError:
        return None, f"could not parse gcx output: {proc.stdout[:200]}"


def check_grafana():
    section("Grafana / gcx")

    if not shutil.which("gcx"):
        report(False, "gcx is installed", "not found on PATH -- see https://github.com/grafana/gcx (or your org's install docs)")
        return
    report(True, "gcx is installed")

    proc = subprocess.run(["gcx", "config", "current-context"], capture_output=True, text=True)
    context = proc.stdout.strip()
    if proc.returncode != 0 or not context:
        report(False, "gcx is logged in", "run 'gcx login' against the target stack")
        return
    report(True, "gcx is logged in", f"context: {context}")

    health, err = gcx_json("api", "/api/health", "-o", "json")
    if health is None:
        report(False, "target Grafana stack is reachable", err)
        return
    report(True, "target Grafana stack is reachable")

    plugins, err = gcx_json("api", "/api/plugins", "-o", "json")
    if plugins is None:
        report(False, "could not list installed plugins", err)
        return
    by_id = {p["id"]: p for p in plugins}
    for plugin_id in REQUIRED_PLUGINS:
        p = by_id.get(plugin_id)
        if not p:
            report(False, f"plugin installed: {plugin_id}",
                   "not installed -- Enterprise plugins need a Cloud Pro/Advanced plan or Enterprise license")
        elif not p.get("enabled"):
            report(False, f"plugin installed: {plugin_id}", "installed but not enabled")
        else:
            report(True, f"plugin installed: {plugin_id}", f"v{p['info']['version']}")


# ---------------------------------------------------------------------------
# Jira side
# ---------------------------------------------------------------------------

def check_jira():
    section("Jira")

    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    project_key = os.environ.get("JIRA_PROJECT_KEY", "")

    missing = [n for n, v in [("JIRA_BASE_URL", base_url), ("JIRA_EMAIL", email),
                               ("JIRA_API_TOKEN", token), ("JIRA_PROJECT_KEY", project_key)] if not v]
    if missing:
        report(False, "required env vars set", f"missing: {', '.join(missing)} -- source envvars first")
        return
    report(True, "required env vars set")

    auth = (email, token)

    resp = requests.get(f"{base_url}/rest/api/3/myself", auth=auth)
    if resp.status_code == 401:
        report(False, "Jira authentication works", "401 Unauthorized -- check JIRA_EMAIL/JIRA_API_TOKEN, or the "
                                                     "token may have been revoked")
        return
    if resp.status_code != 200:
        report(False, "Jira authentication works", f"HTTP {resp.status_code}: {resp.text[:200]}")
        return
    me = resp.json()
    report(True, "Jira authentication works", f"as {me.get('displayName')} <{me.get('emailAddress')}>")

    resp = requests.get(f"{base_url}/rest/api/3/project/{project_key}", auth=auth)
    if resp.status_code != 200:
        report(False, f"project {project_key!r} resolves",
               f"HTTP {resp.status_code} -- check JIRA_PROJECT_KEY, or the token's account may not have access")
        return
    proj = resp.json()
    is_team_managed = proj.get("style") == "next-gen"
    report(True, f"project {project_key!r} resolves", f"{proj.get('name')} ({proj.get('style')})")
    if not is_team_managed:
        print("         NOTE: this isn't a team-managed (\"next-gen\") project -- jira.py was built and tested "
              "against one; a company-managed project may behave differently (e.g. classic screens/schemes "
              "instead of the per-issue \"+ Add field\" flow).")

    resp = requests.get(f"{base_url}/rest/agile/1.0/board", auth=auth, params={"projectKeyOrId": project_key})
    boards = resp.json().get("values", []) if resp.status_code == 200 else []
    if not boards:
        report(False, "project has a Scrum/Kanban board",
               "no board found -- jira.py's sprint logic needs one (a Scrum-template team-managed project "
               "creates this automatically)")
    else:
        report(True, "project has a board", f"{boards[0]['name']} (id {boards[0]['id']})")

    # GET /rest/api/3/field is unreliable for this check -- confirmed live
    # it can fail to list a field that is genuinely attached and working on
    # ANOTHER project on this same site (not just an unattached-fields gap).
    # Custom fields are also allocated per SITE, not per project, so even a
    # clean answer here doesn't guarantee THIS project has them attached --
    # it only rules out "doesn't exist anywhere yet". Kept non-blocking
    # either way: create_jira_fields.py (next step) always re-verifies and
    # tells the SE exactly what to attach for this specific project,
    # regardless of what this check finds.
    resp = requests.get(f"{base_url}/rest/api/3/field", auth=auth)
    existing_names = {f["name"] for f in resp.json()} if resp.status_code == 200 else set()
    required_fields = ["Pillar", "RAG Status", "Narrative", "Delivery Phase", "Start Date", "Blocked By"]
    missing_fields = [f for f in required_fields if f not in existing_names]
    if missing_fields:
        report(False, "required custom fields exist", f"missing (or not attached here yet): "
               f"{', '.join(missing_fields)} -- create_jira_fields.py (run next by setup.sh) will create/"
               "verify them", blocking=False)
    else:
        report(True, "required custom fields exist", f"{len(required_fields)}/{len(required_fields)}")


def main():
    check_grafana()
    check_jira()

    print()
    if problems:
        print(f"=== {len(problems)} problem(s) found -- fix these before running setup.sh ===")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    else:
        print("=== All checks passed. Safe to run ./setup.sh ===")


if __name__ == "__main__":
    main()
