#!/usr/bin/env python3
"""
create_jira_fields.py

Idempotently creates the 6 custom fields jira.py depends on (Pillar, RAG
Status, Narrative, Delivery Phase, Start Date, Blocked By), including the
select-list options for Pillar/RAG Status/Delivery Phase, via the standard
Jira Cloud REST API. Safe to re-run: skips any field that already exists
by name.

WHAT THIS DOES NOT AUTOMATE (a real Jira Cloud platform gap, not a
shortcut): on a team-managed project, a newly created custom field still
needs to be attached to an issue type's layout via the Jira UI ("+ Add
field" on an issue, or Project settings > Issue types > Fields) before it
can actually be set on an issue. There is no public REST API for this step
-- confirmed empirically (a field created via this exact API pattern, and
also one created via the UI, both hit "not on the appropriate screen" on
PUT/create until attached by hand). This script creates the fields and
prints which ones still need that one manual click; it does not pretend
to skip it.

Prints `export JIRA_FIELD_*_ID=customfield_XXXXX` lines to STDOUT for the
fields build_dashboards.py needs, plus Story point estimate (a field this
script doesn't create -- it's provisioned once per Jira site by the Scrum
template and shared across every team-managed Scrum project on that site,
confirmed live -- but still discovered dynamically rather than assumed).
Jira allocates every custom field id fresh per creation and never reuses
one across projects, even for an identically-named field, so these ids are
genuinely different on every new space -- setup.sh evals this script's
stdout, exactly like it already does for setup_grafana.py, so
build_dashboards.py always points at the ids that actually exist for
whichever project it's run against. All other output (status/progress) is
printed to STDERR so it doesn't get swept into that eval.

Uses the same env vars as jira.py (source envvars first).
"""

import os
import sys
import requests

BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
EMAIL = os.environ.get("JIRA_EMAIL", "")
TOKEN = os.environ.get("JIRA_API_TOKEN", "")
AUTH = (EMAIL, TOKEN)

FIELDS = [
    dict(name="Pillar", type="select",
         options=["Payments Modernisation", "Core Banking Migration", "Digital Channels", "Risk & Compliance"]),
    dict(name="RAG Status", type="select", options=["Green", "Amber", "Red"]),
    dict(name="Narrative", type="textarea"),
    dict(name="Delivery Phase", type="select",
         options=["Discovery", "Build", "Test", "Deploy", "Live"]),
    dict(name="Start Date", type="date"),
    dict(name="Blocked By", type="text",
         description="Plain-text blocker issue key (e.g. TPMO1-1) -- workaround for the native issuelinks "
                      "field coming back as an unparsed JSON blob in the Jira datasource plugin."),
]

JIRA_TYPE = {
    "select": "com.atlassian.jira.plugin.system.customfieldtypes:select",
    "textarea": "com.atlassian.jira.plugin.system.customfieldtypes:textarea",
    "date": "com.atlassian.jira.plugin.system.customfieldtypes:datepicker",
    "text": "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
}
JIRA_SEARCHER = {
    "select": "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
    "textarea": "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    "date": "com.atlassian.jira.plugin.system.customfieldtypes:daterange",
    "text": "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
}


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_config():
    missing = [n for n, v in [("JIRA_BASE_URL", BASE_URL), ("JIRA_EMAIL", EMAIL), ("JIRA_API_TOKEN", TOKEN)] if not v]
    if missing:
        die(f"Missing env vars: {', '.join(missing)}. Source envvars first.")


def api(method, path, **kwargs):
    resp = requests.request(method, f"{BASE_URL}{path}", auth=AUTH, headers={"Content-Type": "application/json"},
                             **kwargs)
    if resp.status_code >= 300:
        die(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
    return resp.json() if resp.text else {}


def get_existing_fields():
    """GET /rest/api/3/field only returns fields already attached to a
    screen (confirmed against Atlassian's own docs and live behaviour) --
    a field this script just created is NOT attached yet, so that endpoint
    would call it "missing" and this script would recreate it as a genuine
    duplicate on every rerun before the manual attach step happens. This is
    exactly how an old Blocked By field from an earlier test run got
    orphaned. Use the unfiltered field/search endpoint instead, which sees
    every field on the site whether or not it's on a screen."""
    fields = {}
    start_at = 0
    while True:
        page = api("GET", "/rest/api/3/field/search", params={"type": "custom", "startAt": start_at})
        for f in page["values"]:
            fields[f["name"]] = f
        if page.get("isLast", True):
            break
        start_at += len(page["values"])
    return fields


def find_field_id(name):
    page = api("GET", "/rest/api/3/field/search", params={"query": name})
    match = next((f for f in page["values"] if f["name"] == name), None)
    if not match:
        die(f"Field {name!r} not found on this Jira site.")
    return match["id"]


def create_field(spec):
    body = {
        "name": spec["name"],
        "type": JIRA_TYPE[spec["type"]],
        "searcherKey": JIRA_SEARCHER[spec["type"]],
    }
    if spec.get("description"):
        body["description"] = spec["description"]
    return api("POST", "/rest/api/3/field", json=body)


def add_select_options(field_id, options):
    contexts = api("GET", f"/rest/api/3/field/{field_id}/context")["values"]
    if not contexts:
        die(f"No context found for {field_id} right after creation -- unexpected.")
    context_id = contexts[0]["id"]
    api("POST", f"/rest/api/3/field/{field_id}/context/{context_id}/option",
        json={"options": [{"value": o} for o in options]})


# Maps each FIELDS spec name to the env var build_dashboards.py (or jira.py,
# for Narrative) reads it back from. Story point estimate isn't in FIELDS
# (this script doesn't create it -- see module docstring) but dashboards
# need its id too, so it's looked up the same way and exported alongside
# the fields this script does manage.
DASHBOARD_FIELD_ENV_VARS = {
    "Pillar": "JIRA_FIELD_PILLAR_ID",
    "RAG Status": "JIRA_FIELD_RAG_ID",
    "Narrative": "JIRA_FIELD_NARRATIVE_ID",
    "Delivery Phase": "JIRA_FIELD_PHASE_ID",
    "Start Date": "JIRA_FIELD_START_DATE_ID",
    "Blocked By": "JIRA_FIELD_BLOCKED_BY_ID",
}


def log(msg):
    print(msg, file=sys.stderr)


def main():
    check_config()
    existing = get_existing_fields()
    resolved = {}

    for spec in FIELDS:
        name = spec["name"]
        if name in existing:
            log(f"OK (already exists on this SITE): {name} -> {existing[name]['id']}")
            resolved[name] = existing[name]["id"]
            continue
        field = create_field(spec)
        field_id = field["id"]
        log(f"CREATED: {name} -> {field_id}")
        if spec["type"] == "select":
            add_select_options(field_id, spec["options"])
            log(f"  added options: {spec['options']}")
        resolved[name] = field_id

    # Custom fields are allocated per SITE, not per project -- confirmed
    # live: running this a second time for a second project on the same
    # site found every field "already existing" (created for the first
    # project), which is correct, but that says nothing about whether THIS
    # project has them attached. There's no reliable read-only API to check
    # per-project attachment for a team-managed project either -- confirmed
    # live, on this exact site: both GET /rest/api/3/field (which is meant
    # to reflect screen attachment) and GET .../field/{id}/association/project
    # (explicitly a project-association endpoint) failed to show a field
    # that was definitely already attached and working on another project.
    # So rather than guess, ALWAYS list every field here, whether just
    # created or found pre-existing -- if a field genuinely is already
    # attached to this exact project (e.g. a true rerun, not a new one),
    # re-selecting it in "Add fields" is a harmless no-op.
    log("\n--- Verify these are attached to THIS project (no Jira API for this) ---")
    log("Custom fields live at the site level, not per-project -- one already existing (created for a "
        "different project on this site) does NOT mean it's usable here yet. Go to Space settings > "
        "Fields > Add fields (or any issue's '+ Add field' once one exists) and search for each of these "
        "by name -- if it's already attached here, selecting it again is a harmless no-op:")
    for spec in FIELDS:
        name = spec["name"]
        log(f"  - {name} ({resolved[name]})")
    log("If jira.py fails with \"not on the appropriate screen\", this is what's missing.")

    resolved["Story point estimate"] = find_field_id("Story point estimate")

    for name, env_var in DASHBOARD_FIELD_ENV_VARS.items():
        print(f"export {env_var}={resolved[name]}")
    print(f"export JIRA_FIELD_POINTS_ID={resolved['Story point estimate']}")


if __name__ == "__main__":
    main()
