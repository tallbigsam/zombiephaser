#!/usr/bin/env python3
"""
seed_tpmo_jira_dataset.py

Pushes a small, deliberately-consistent synthetic dataset into a Jira Cloud
project, built to mirror the "TPMO1 – Grafana Use Case & Rationale for
Transformation Portfolio Reporting" source doc.

Covers, directly:
  - MT Status Reporting Dashboard   -> RAG + Narrative fields
  - Cross-Pillar Dependency Dashboard -> Pillar field + "Blocks" issue links
  - Transformation Delivery Roadmap  -> Start Date, Due Date, Delivery Phase
  - Delivery Metrics Dashboard       -> Sprint-level Story/Bug issues with
                                         Story Points, mixed statuses, and a
                                         closed sprint (throughput/velocity)

Does NOT touch Azure DevOps (out of scope for this script).

--------------------------------------------------------------------------
MANUAL SETUP (do this once, in the Jira UI, before running the script)
--------------------------------------------------------------------------
1. Create a Jira Software project, template = Scrum, note its project KEY
   (e.g. "TPD"). Scrum gives you sprints/boards for free for the Delivery
   Metrics use case.

2. Create these custom fields (Project settings > Fields, or global
   Field configuration) with EXACTLY these names:
     - "Pillar"          -> Select List (single choice)
                            options: Payments Modernisation, Core Banking
                            Migration, Digital Channels, Risk & Compliance
     - "RAG Status"      -> Select List (single choice)
                            options: Green, Amber, Red
     - "Narrative"        -> Paragraph / multi-line text field
     - "Delivery Phase"  -> Select List (single choice)
                            options: Discovery, Build, Test, Deploy, Live
     - "Start Date"      -> Date Picker
     - "Blocked By"      -> Short text (single line)
                            plain-text blocker issue key (e.g. "TPMO1-1"),
                            populated at creation time as a workaround for
                            the native issuelinks field coming back as an
                            unparsed JSON blob in the Jira datasource plugin

   Make sure each field is added to the Create/Edit screens for the
   project (otherwise the API can still usually set the value, but it's
   safest to add them so you can also see/edit them by hand later).

   Due date is Jira's built-in `duedate` field — no need to create it.

3. Generate a fresh API token at
   https://id.atlassian.com/manage-profile/security/api-tokens
   (do this AFTER revoking any token that has ever been pasted into a
   chat window).

4. Export these as environment variables in your own shell — never paste
   them into a chat session:
     export JIRA_BASE_URL="https://<your-site>.atlassian.net"
     export JIRA_EMAIL="you@example.com"
     export JIRA_API_TOKEN="<your new token>"
     export JIRA_PROJECT_KEY="TPD"

5. Sanity-check first:
     python3 seed_tpmo_jira_dataset.py --dry-run
   then, once the printed plan looks right:
     python3 seed_tpmo_jira_dataset.py

Requires: pip install requests
--------------------------------------------------------------------------
"""

import os
import sys
import time
import json
import requests
from datetime import date, timedelta

BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
EMAIL = os.environ.get("JIRA_EMAIL", "")
TOKEN = os.environ.get("JIRA_API_TOKEN", "")
PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "")
DRY_RUN = "--dry-run" in sys.argv

AUTH = (EMAIL, TOKEN)
HEADERS = {"Content-Type": "application/json"}

TODAY = date.today()


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_config():
    if DRY_RUN:
        return
    missing = [n for n, v in [
        ("JIRA_BASE_URL", BASE_URL), ("JIRA_EMAIL", EMAIL),
        ("JIRA_API_TOKEN", TOKEN), ("JIRA_PROJECT_KEY", PROJECT_KEY),
    ] if not v]
    if missing:
        die(f"Missing env vars: {', '.join(missing)}. See the setup checklist at the top of this file.")


def preflight_checks():
    """Fail fast, before creating anything, rather than partway through a
    69-issue run. Rerunning this against a project that already has
    issues would silently create a full duplicate set (the caller --
    setup.sh -- is also supposed to guard this, but that guard had its
    own bug once already, so this is a second, independent line of
    defense). Leftover sprints from a prior run don't need a check here:
    ensure_sprints() only ever reuses "future"-state sprints and creates
    fresh ones otherwise, so an old closed/active sprint is never touched."""
    if DRY_RUN:
        return
    existing = api("GET", "/rest/api/3/search/jql",
                    params={"jql": f"project = {PROJECT_KEY}", "maxResults": 1})
    if existing.get("issues"):
        die(f"Project {PROJECT_KEY} already has issues. Refusing to reseed on top of existing data -- "
            f"delete them first if you want a clean run.")


def api(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    if DRY_RUN:
        print(f"[dry-run] {method} {path} :: {json.dumps(kwargs.get('json', {}))[:200]}")
        return {"key": "DRY-0", "id": "0"}
    resp = requests.request(method, url, auth=AUTH, headers=HEADERS, **kwargs)
    if resp.status_code >= 300:
        die(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
    time.sleep(0.3)  # be polite to the API-token burst rate limit
    return resp.json() if resp.text else {}


# Maps each field name to the env var create_jira_fields.py exports for it
# (setup.sh sources that script's output before running this one). Prefer
# these over the by-name lookup below: Jira allows multiple custom fields
# with the identical name on one site (confirmed live -- an old orphaned
# field from a previous demo run sat right next to a freshly-created one,
# both named "Blocked By"), so a name -> id lookup is fundamentally
# ambiguous whenever a site has been used for this demo before. Trusting
# the exact id create_jira_fields.py already resolved avoids re-guessing.
FIELD_ENV_VARS = {
    "Pillar": "JIRA_FIELD_PILLAR_ID", "RAG Status": "JIRA_FIELD_RAG_ID",
    "Narrative": "JIRA_FIELD_NARRATIVE_ID",
    "Delivery Phase": "JIRA_FIELD_PHASE_ID", "Start Date": "JIRA_FIELD_START_DATE_ID",
    "Blocked By": "JIRA_FIELD_BLOCKED_BY_ID", "Story point estimate": "JIRA_FIELD_POINTS_ID",
}


def discover_field_ids():
    """Map our human field names to Jira's customfield_XXXXX ids."""
    if DRY_RUN:
        return {
            "Pillar": "customfield_10101", "RAG Status": "customfield_10102",
            "Narrative": "customfield_10103", "Delivery Phase": "customfield_10104",
            "Start Date": "customfield_10105", "Blocked By": "customfield_10106",
            "Story point estimate": "customfield_10016",
        }
    required = ["Pillar", "RAG Status", "Narrative", "Delivery Phase", "Start Date", "Blocked By",
                "Story point estimate"]
    from_env = {n: os.environ[FIELD_ENV_VARS[n]] for n in required if n in FIELD_ENV_VARS
                and FIELD_ENV_VARS[n] in os.environ}
    remaining = [n for n in required if n not in from_env]
    if remaining:
        print(f"WARNING: {remaining} not found in the environment (run this via setup.sh, which exports "
              f"them from create_jira_fields.py, rather than standalone) -- falling back to an ambiguous "
              f"by-name lookup that can silently pick a stale duplicate field. Verify these ids afterward "
              f"if this site has ever run this demo before.", file=sys.stderr)
        # GET /rest/api/3/field, NOT used here -- confirmed live it can fail
        # to show a field that is genuinely attached and working (this is
        # not just the "unattached fields are hidden" gap noted elsewhere;
        # it failed even for an attached one), so it's not just ambiguous
        # for duplicates, it's unreliable outright for team-managed fields.
        # field/search doesn't have that gap.
        name_to_id = {}
        for n in remaining:
            page = api("GET", "/rest/api/3/field/search", params={"query": n})
            match = next((f for f in page["values"] if f["name"] == n), None)
            if match:
                name_to_id[n] = match["id"]
        missing = [n for n in remaining if n not in name_to_id]
        if missing:
            die(f"Custom fields not found in Jira: {missing}. Create them first (see setup checklist).")
        from_env.update({n: name_to_id[n] for n in remaining})
    return from_env


def discover_board_id():
    if DRY_RUN:
        return 67
    boards = api("GET", "/rest/agile/1.0/board", params={"projectKeyOrId": PROJECT_KEY})["values"]
    if not boards:
        die(f"No Scrum/Kanban board found for project {PROJECT_KEY}.")
    return boards[0]["id"]


def ensure_sprints(board_id, needed=2):
    """Return `needed` (id, name) sprint pairs on this board that are safe
    to reuse -- i.e. still in "future" state. Sprints left over from a
    prior run in "active"/"closed" state are never reused: Jira flatly
    rejects moving new issues into an already-closed sprint (hit this
    live), and reusing an active one would inherit unrelated history.
    New sprints are created instead, numbered past whatever already
    exists so names never collide. `name` is needed later: Jira's sprint
    PUT requires it on every update, even when only state/dates change."""
    if DRY_RUN:
        return [(i, f"{PROJECT_KEY} Sprint {i}") for i in range(1, needed + 1)]
    all_sprints = sorted(api("GET", f"/rest/agile/1.0/board/{board_id}/sprint")["values"],
                          key=lambda s: s["id"])
    usable = [s for s in all_sprints if s["state"] == "future"]
    next_n = len(all_sprints) + 1
    while len(usable) < needed:
        name = f"{PROJECT_KEY} Sprint {next_n}"
        next_n += 1
        usable.append(api("POST", "/rest/agile/1.0/sprint", json={"name": name, "originBoardId": board_id}))
    return [(s["id"], s["name"]) for s in usable[:needed]]


def adf(text):
    """Wrap plain text as an Atlassian Document Format paragraph (needed for
    description/paragraph-type fields on the v3 API)."""
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    ]}


# --------------------------------------------------------------------------
# The dataset: 25 initiatives, 4 milestones, 10 dependency edges across 10
# storylines, plus 40 sprint-level stories/bugs split across a closed sprint
# and a currently-active one -- sized to feel like a real portfolio rather
# than a minimal proof of concept.
#
# Consistency rule enforced below (and asserted before anything is sent):
#   - if blocker.status == "Done": the blocked issue's RAG/narrative must
#     NOT frame it as still gated by that blocker.
#   - if blocker.status != "Done" and blocker is overdue: the blocked issue
#     SHOULD show Amber/Red with a narrative naming the blocker.
# --------------------------------------------------------------------------

def d(days_offset):
    return (TODAY + timedelta(days=days_offset)).isoformat()


def dt(days_offset):
    """Like d(), but as a full ISO-8601 datetime -- the Agile sprint API
    rejects a bare date (e.g. "2026-09-07") for startDate/endDate/
    completeDate with "You must specify a start date for the sprint",
    silently treating it as missing rather than as a parse error."""
    return d(days_offset) + "T00:00:00.000Z"


INITIATIVES = [
    # id, pillar, summary, status, rag, narrative, start, due, phase
    dict(id="INIT-1", pillar="Payments Modernisation",
         summary="Faster Payments Gateway Upgrade", status="In Progress", rag="Red",
         narrative="Slipped due to vendor certification delays; revised target under review.",
         start=d(-90), due=d(-10), phase="Build"),
    dict(id="INIT-2", pillar="Core Banking Migration",
         summary="Ledger Reconciliation Service", status="Blocked", rag="Red",
         narrative="Cannot begin integration testing until Faster Payments Gateway Upgrade completes; delivery at risk.",
         start=d(-30), due=d(30), phase="Build"),

    dict(id="INIT-3", pillar="Digital Channels",
         summary="Mobile Identity Verification", status="Done", rag="Green",
         narrative="Delivered on schedule; live in production.",
         start=d(-120), due=d(-30), phase="Live"),
    dict(id="INIT-4", pillar="Risk & Compliance",
         summary="Enhanced KYC Controls", status="In Progress", rag="Green",
         narrative="Unblocked following Mobile Identity Verification go-live; on track.",
         start=d(-25), due=d(45), phase="Build"),

    dict(id="INIT-5", pillar="Core Banking Migration",
         summary="Account Data Migration Wave 1", status="Done", rag="Green",
         narrative="Completed ahead of schedule.",
         start=d(-100), due=d(-20), phase="Live"),
    dict(id="INIT-6", pillar="Digital Channels",
         summary="Customer Portal Cutover", status="In Progress", rag="Amber",
         narrative="Released to proceed following Account Data Migration Wave 1 completion; ramping up testing.",
         start=d(-15), due=d(40), phase="Test"),

    dict(id="INIT-7", pillar="Risk & Compliance",
         summary="Regulatory Reporting Redesign", status="In Progress", rag="Amber",
         narrative="On track; design milestone approaching.",
         start=d(-40), due=d(60), phase="Discovery"),
    dict(id="INIT-8", pillar="Payments Modernisation",
         summary="Cross-Border Reporting Feed", status="In Progress", rag="Amber",
         narrative="Dependent on Regulatory Reporting Redesign milestone; monitoring closely.",
         start=d(-10), due=d(70), phase="Discovery"),

    # standalone, no dependencies
    dict(id="INIT-9", pillar="Core Banking Migration",
         summary="Branch System Decommission", status="Done", rag="Green",
         narrative="Completed; systems decommissioned as planned.",
         start=d(-150), due=d(-45), phase="Live"),
    dict(id="INIT-10", pillar="Digital Channels",
         summary="Chatbot Self-Service Expansion", status="In Progress", rag="Green",
         narrative="On track for scheduled release.",
         start=d(-20), due=d(35), phase="Build"),
    dict(id="INIT-11", pillar="Risk & Compliance",
         summary="Fraud Model Retraining", status="In Progress", rag="Amber",
         narrative="Data quality issues in training set; remediation underway, not dependency-related.",
         start=d(-15), due=d(25), phase="Build"),
    dict(id="INIT-12", pillar="Payments Modernisation",
         summary="ISO20022 Message Mapping", status="To Do", rag="Green",
         narrative="Not yet started; scheduled to begin next quarter.",
         start=d(20), due=d(100), phase="Discovery"),

    dict(id="INIT-13", pillar="Payments Modernisation",
         summary="Real-Time Payments Fraud Screening", status="In Progress", rag="Red",
         narrative="Vendor SDK integration slipping; blocking downstream roll-out.",
         start=d(-60), due=d(-5), phase="Build"),
    dict(id="INIT-14", pillar="Risk & Compliance",
         summary="Transaction Monitoring Threshold Recalibration", status="Blocked", rag="Red",
         narrative="Cannot proceed until Real-Time Payments Fraud Screening delivers updated risk scores; escalated to steering.",
         start=d(-20), due=d(50), phase="Build"),

    dict(id="INIT-15", pillar="Core Banking Migration",
         summary="General Ledger Chart of Accounts Rebuild", status="Done", rag="Green",
         narrative="Completed and validated in production.",
         start=d(-140), due=d(-40), phase="Live"),
    dict(id="INIT-16", pillar="Digital Channels",
         summary="Statement Redesign for Mobile App", status="In Progress", rag="Green",
         narrative="Proceeding cleanly now that the new chart of accounts is live.",
         start=d(-10), due=d(50), phase="Build"),

    dict(id="INIT-17", pillar="Risk & Compliance",
         summary="Third-Party Risk Assessment Framework", status="In Progress", rag="Amber",
         narrative="Framework design progressing; on track for sign-off next month.",
         start=d(-35), due=d(40), phase="Discovery"),
    dict(id="INIT-18", pillar="Payments Modernisation",
         summary="Vendor Payment Gateway Onboarding", status="In Progress", rag="Amber",
         narrative="Sequenced behind the Third-Party Risk Assessment Framework; monitoring for slippage.",
         start=d(-5), due=d(65), phase="Discovery"),

    dict(id="INIT-19", pillar="Digital Channels",
         summary="Biometric Login Rollout", status="Done", rag="Green",
         narrative="Live across all retail channels.",
         start=d(-110), due=d(-25), phase="Live"),
    dict(id="INIT-20", pillar="Core Banking Migration",
         summary="Legacy Account Closure Automation", status="In Progress", rag="Green",
         narrative="Unblocked following Biometric Login Rollout completion; building automation now.",
         start=d(-8), due=d(55), phase="Build"),
    dict(id="INIT-21", pillar="Core Banking Migration",
         summary="Legacy Account Closure Full Rollout", status="To Do", rag="Amber",
         narrative="Waiting on the pilot go-live milestone before full rollout begins.",
         start=d(15), due=d(90), phase="Discovery"),

    dict(id="INIT-22", pillar="Payments Modernisation",
         summary="SWIFT gpi Tracker Integration", status="In Progress", rag="Red",
         narrative="Integration testing delayed by correspondent bank availability; now overdue.",
         start=d(-70), due=d(-15), phase="Test"),
    dict(id="INIT-23", pillar="Payments Modernisation",
         summary="Cross-Border Payment Status Notifications", status="Blocked", rag="Red",
         narrative="Cannot notify customers of payment status until SWIFT gpi Tracker Integration completes; delivery at risk.",
         start=d(-20), due=d(40), phase="Build"),

    dict(id="INIT-24", pillar="Digital Channels",
         summary="Accessibility Compliance Uplift (WCAG 2.2)", status="In Progress", rag="Amber",
         narrative="Remediation in progress across priority journeys.",
         start=d(-25), due=d(35), phase="Build"),
    dict(id="INIT-25", pillar="Risk & Compliance",
         summary="Operational Resilience Scenario Testing", status="To Do", rag="Green",
         narrative="Scoping complete; testing scheduled for next quarter.",
         start=d(25), due=d(110), phase="Discovery"),
]

MILESTONES = [
    dict(id="MS-1", parent="INIT-7", summary="Milestone: Regulatory Reporting - Design Sign-off",
         due=d(21)),
    dict(id="MS-2", parent="INIT-20", summary="Milestone: Legacy Account Closure - Pilot Go-Live",
         due=d(14)),
    dict(id="MS-3", parent="INIT-17", summary="Milestone: Third-Party Risk Framework Sign-off",
         due=d(35)),
    dict(id="MS-4", parent="INIT-24", summary="Milestone: WCAG 2.2 Uplift - Priority Journeys Complete",
         due=d(30)),
]

# (blocker_id, blocked_id) -- "blocker blocks blocked"
DEPENDENCIES = [
    ("INIT-1", "INIT-2"),    # storyline 2: overdue blocker -> real bottleneck
    ("INIT-3", "INIT-4"),    # storyline 1: done blocker -> clean, unblocked
    ("INIT-5", "INIT-6"),    # storyline 3: recently-done blocker -> just released
    ("MS-1", "INIT-8"),      # storyline 4: upcoming milestone dependency
    ("INIT-13", "INIT-14"),  # storyline 5: overdue blocker -> real bottleneck (cross-pillar)
    ("INIT-15", "INIT-16"),  # storyline 6: done blocker -> clean, unblocked (cross-pillar)
    ("INIT-17", "INIT-18"),  # storyline 7: on-track blocker, sequenced but not at-risk
    ("INIT-19", "INIT-20"),  # storyline 8: done blocker -> clean, unblocked (cross-pillar)
    ("MS-2", "INIT-21"),     # storyline 9: upcoming milestone dependency
    ("INIT-22", "INIT-23"),  # storyline 10: overdue blocker -> real bottleneck
]

# blocked_id -> blocker_id, used to populate the plain-text "Blocked By" field
# at issue-creation time. Setting a new custom field via a later PUT gets
# rejected on team-managed projects ("not on the appropriate screen") until
# it's added to the issue type's layout via the Jira UI, but issue creation
# isn't screen-restricted the same way, so we set it inline on create instead.
BLOCKER_OF = {blocked: blocker for blocker, blocked in DEPENDENCIES}

SPRINT_ISSUES = [
    # parent, type, summary, status, story points, sprint ("closed"/"active")
    # -- status/points/sprint give the Delivery Metrics dashboard's
    # throughput/velocity/lead-time panels both a completed sprint and a
    # live one to report on, instead of a flat "everything is To Do".

    # -- closed sprint: mostly done, a couple of realistic spillovers --
    dict(parent="INIT-1", type="Story", summary="Implement 3DS step-up for high-value transfers",
         status="Done", points=5, sprint="closed"),
    dict(parent="INIT-1", type="Bug", summary="Certification sandbox returns stale token",
         status="Done", points=2, sprint="closed"),
    dict(parent="INIT-2", type="Story", summary="Reconciliation exception queue UI",
         status="Done", points=3, sprint="closed"),
    dict(parent="INIT-2", type="Bug", summary="Duplicate postings on retry",
         status="Done", points=2, sprint="closed"),
    dict(parent="INIT-4", type="Story", summary="KYC document upload validation rules",
         status="Done", points=3, sprint="closed"),
    dict(parent="INIT-4", type="Story", summary="Risk scoring rule engine v1",
         status="Done", points=5, sprint="closed"),
    dict(parent="INIT-6", type="Story", summary="Customer portal SSO cutover",
         status="Done", points=3, sprint="closed"),
    dict(parent="INIT-6", type="Bug", summary="Session timeout on cutover path",
         status="Done", points=1, sprint="closed"),
    dict(parent="INIT-7", type="Story", summary="Regulatory report template v2",
         status="Done", points=5, sprint="closed"),
    dict(parent="INIT-8", type="Story", summary="Cross-border feed schema mapping",
         status="Done", points=3, sprint="closed"),
    dict(parent="INIT-10", type="Story", summary="Chatbot intent model v2",
         status="Done", points=8, sprint="closed"),
    dict(parent="INIT-11", type="Story", summary="Fraud model feature store cleanup",
         status="Done", points=3, sprint="closed"),
    dict(parent="INIT-13", type="Story", summary="Fraud SDK sandbox integration",
         status="Done", points=5, sprint="closed"),
    dict(parent="INIT-13", type="Bug", summary="SDK callback race condition",
         status="In Progress", points=3, sprint="closed"),
    dict(parent="INIT-14", type="Story", summary="Threshold recalibration test plan",
         status="Done", points=2, sprint="closed"),
    dict(parent="INIT-15", type="Story", summary="Chart of accounts migration validation",
         status="Done", points=5, sprint="closed"),
    dict(parent="INIT-17", type="Story", summary="Third-party risk questionnaire automation",
         status="Done", points=3, sprint="closed"),
    dict(parent="INIT-19", type="Bug", summary="Biometric fallback flow edge case",
         status="In Progress", points=2, sprint="closed"),
    dict(parent="INIT-22", type="Story", summary="SWIFT gpi status polling job",
         status="Done", points=5, sprint="closed"),
    dict(parent="INIT-24", type="Story", summary="Screen reader labels for statements",
         status="Done", points=2, sprint="closed"),

    # -- active sprint: mid-sprint mix of done/in progress/to do --
    dict(parent="INIT-1", type="Story", summary="Vendor certification test harness",
         status="In Progress", points=3, sprint="active"),
    dict(parent="INIT-2", type="Story", summary="Automated ledger break detection",
         status="In Progress", points=5, sprint="active"),
    dict(parent="INIT-4", type="Story", summary="KYC risk scoring rule engine v2",
         status="To Do", points=5, sprint="active"),
    dict(parent="INIT-6", type="Story", summary="Portal cutover rollback plan",
         status="To Do", points=2, sprint="active"),
    dict(parent="INIT-7", type="Bug", summary="Report template v2 rounding error",
         status="In Progress", points=2, sprint="active"),
    dict(parent="INIT-8", type="Story", summary="Cross-border feed monitoring dashboard",
         status="To Do", points=3, sprint="active"),
    dict(parent="INIT-10", type="Story", summary="Escalation-to-human handoff flow",
         status="In Progress", points=5, sprint="active"),
    dict(parent="INIT-10", type="Bug", summary="Session context lost on channel switch",
         status="To Do", points=1, sprint="active"),
    dict(parent="INIT-11", type="Story", summary="Fraud model retraining pipeline v2",
         status="In Progress", points=8, sprint="active"),
    dict(parent="INIT-13", type="Story", summary="Fraud SDK production rollout plan",
         status="To Do", points=3, sprint="active"),
    dict(parent="INIT-14", type="Story", summary="Threshold recalibration sign-off pack",
         status="In Progress", points=3, sprint="active"),
    dict(parent="INIT-16", type="Story", summary="Mobile statement redesign - iOS",
         status="In Progress", points=5, sprint="active"),
    dict(parent="INIT-16", type="Story", summary="Mobile statement redesign - Android",
         status="To Do", points=5, sprint="active"),
    dict(parent="INIT-18", type="Story", summary="Vendor gateway sandbox credentials",
         status="Done", points=1, sprint="active"),
    dict(parent="INIT-18", type="Bug", summary="Gateway webhook signature mismatch",
         status="In Progress", points=2, sprint="active"),
    dict(parent="INIT-20", type="Story", summary="Legacy account closure eligibility rules",
         status="In Progress", points=5, sprint="active"),
    dict(parent="INIT-21", type="Story", summary="Full rollout comms plan",
         status="To Do", points=2, sprint="active"),
    dict(parent="INIT-22", type="Bug", summary="SWIFT polling job memory leak",
         status="In Progress", points=3, sprint="active"),
    dict(parent="INIT-24", type="Story", summary="Colour contrast remediation - card details screen",
         status="Done", points=2, sprint="active"),
    dict(parent="INIT-25", type="Story", summary="Resilience scenario test scripts",
         status="To Do", points=3, sprint="active"),
]


def validate_consistency():
    by_id = {i["id"]: i for i in INITIATIVES}
    by_id.update({m["id"]: {"status": "Milestone", "due": m["due"]} for m in MILESTONES})
    problems = []

    for ms in MILESTONES:
        if ms.get("parent") and ms["parent"] not in by_id:
            problems.append(f"Milestone {ms['id']} references unknown parent {ms['parent']!r}.")
    for item in SPRINT_ISSUES:
        if item["parent"] not in by_id:
            problems.append(f"Sprint issue {item['summary']!r} references unknown parent {item['parent']!r}.")

    for blocker_id, blocked_id in DEPENDENCIES:
        if blocker_id not in by_id or blocked_id not in by_id:
            problems.append(f"Dependency {blocker_id!r} -> {blocked_id!r} references an unknown id.")
            continue
        blocker = by_id[blocker_id]
        blocked = by_id[blocked_id]
        if blocker["status"] == "Done" and blocked["status"] in ("Blocked",):
            problems.append(f"{blocked_id} is status=Blocked but its blocker {blocker_id} is Done — contradiction.")
        if blocker["status"] == "Done" and "blocked by" in (blocked.get("narrative") or "").lower():
            problems.append(f"{blocked_id} narrative still references being blocked, but {blocker_id} is Done.")
        overdue = blocker.get("due") and blocker["due"] < TODAY.isoformat() and blocker["status"] != "Done"
        if overdue and blocked.get("rag") == "Green":
            problems.append(f"{blocked_id} is Green but its blocker {blocker_id} is overdue and not Done — should be Amber/Red.")
    if problems:
        die("Consistency check failed:\n  - " + "\n  - ".join(problems))
    print(f"Consistency check passed: {len(DEPENDENCIES)} dependency edges, no contradictions.")


def create_issue(fields_payload):
    body = {"fields": fields_payload}
    result = api("POST", "/rest/api/3/issue", json=body)
    return result["key"]


def transition_issue(key, target_status_name):
    if DRY_RUN:
        print(f"[dry-run] transition {key} -> {target_status_name}")
        return
    transitions = api("GET", f"/rest/api/3/issue/{key}/transitions")["transitions"]
    match = next((t for t in transitions if t["name"].lower() == target_status_name.lower()
                  or t["to"]["name"].lower() == target_status_name.lower()), None)
    if not match:
        print(f"  (warning) no transition to '{target_status_name}' found for {key}, leaving as-is")
        return
    api("POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": match["id"]}})


def link_issues(blocker_key, blocked_key):
    api("POST", "/rest/api/3/issueLink", json={
        "type": {"name": "Blocks"},
        "inwardIssue": {"key": blocked_key},
        "outwardIssue": {"key": blocker_key},
    })


def _move_into_sprint(sprint_id, keys):
    print(f"Moving {len(keys)} issues into sprint {sprint_id}...")
    if DRY_RUN:
        print(f"[dry-run] POST /rest/agile/1.0/sprint/{sprint_id}/issue :: {keys}")
    else:
        api("POST", f"/rest/agile/1.0/sprint/{sprint_id}/issue", json={"issues": keys})


def setup_sprint_metrics(closed_keys, closed_statuses, active_keys, active_statuses):
    """Move sprint-level issues into two sprints -- one closed in the past,
    one active now -- and transition each issue, so the Delivery Metrics
    dashboard has both a completed sprint (velocity/throughput) and a live
    one (burndown/in-flight work) to report on, not an empty backlog."""
    board_id = discover_board_id()
    (closed_id, closed_name), (active_id, active_name) = ensure_sprints(board_id, needed=2)

    _move_into_sprint(closed_id, closed_keys)
    _move_into_sprint(active_id, active_keys)

    # Jira's sprint PUT requires "name" on every update, even when only
    # state/dates are changing -- omitting it 400s with "Sprint name is
    # required" (hit this live; the id alone isn't enough).
    print(f"Starting and closing sprint {closed_id} (past)...")
    api("PUT", f"/rest/agile/1.0/sprint/{closed_id}", json={
        "name": closed_name, "state": "active", "startDate": dt(-14), "endDate": dt(-1),
    })
    # The closing PUT must re-affirm startDate/endDate -- Jira rejects a
    # closed-state PUT that carries only completeDate with "You must specify
    # a start date for the sprint", even though the sprint already has one.
    api("PUT", f"/rest/agile/1.0/sprint/{closed_id}", json={
        "name": closed_name, "state": "closed",
        "startDate": dt(-14), "endDate": dt(-1), "completeDate": dt(-1),
    })

    print(f"Starting sprint {active_id} (current, left active)...")
    api("PUT", f"/rest/agile/1.0/sprint/{active_id}", json={
        "name": active_name, "state": "active", "startDate": dt(-6), "endDate": dt(8),
    })

    for key, status in zip(closed_keys, closed_statuses):
        transition_issue(key, status)
    for key, status in zip(active_keys, active_statuses):
        transition_issue(key, status)


def main():
    check_config()
    preflight_checks()
    validate_consistency()
    fids = discover_field_ids()

    key_map = {}
    milestones_by_parent = {}
    for ms in MILESTONES:
        milestones_by_parent.setdefault(ms.get("parent"), []).append(ms)

    print(f"\nCreating {len(INITIATIVES)} initiatives...")
    for init in INITIATIVES:
        fields = {
            "project": {"key": PROJECT_KEY},
            "issuetype": {"name": "Epic"},
            "summary": init["summary"],
            fids["Pillar"]: {"value": init["pillar"]},
            fids["RAG Status"]: {"value": init["rag"]},
            fids["Narrative"]: adf(init["narrative"]),
            fids["Delivery Phase"]: {"value": init["phase"]},
            fids["Start Date"]: init["start"],
            "duedate": init["due"],
        }
        blocker_id = BLOCKER_OF.get(init["id"])
        if blocker_id:
            fields[fids["Blocked By"]] = key_map[blocker_id]
        key = create_issue(fields)
        key_map[init["id"]] = key
        transition_issue(key, init["status"])
        suffix = f"  [Blocked By: {key_map[blocker_id]}]" if blocker_id else ""
        print(f"  {init['id']} -> {key} ({init['status']}, {init['rag']}, {init['pillar']}){suffix}")

        # Create any milestone(s) parented to this initiative now, while its
        # key is fresh -- INIT-8's "Blocked By" needs MS-1's key, and MS-1
        # needs INIT-7's key, so milestones must land between the two.
        for ms in milestones_by_parent.get(init["id"], []):
            ms_fields = {
                "project": {"key": PROJECT_KEY},
                "issuetype": {"name": "Task"},
                "summary": ms["summary"],
                "duedate": ms["due"],
                "parent": {"key": key},
            }
            ms_key = create_issue(ms_fields)
            key_map[ms["id"]] = ms_key
            print(f"  {ms['id']} -> {ms_key} (milestone, parent {init['id']})")

    print(f"\nCreating {len(DEPENDENCIES)} dependency links...")
    for blocker_id, blocked_id in DEPENDENCIES:
        link_issues(key_map[blocker_id], key_map[blocked_id])
        print(f"  {key_map[blocker_id]} blocks {key_map[blocked_id]}")

    print(f"\nCreating {len(SPRINT_ISSUES)} sprint-level stories/bugs...")
    closed_keys, closed_statuses = [], []
    active_keys, active_statuses = [], []
    for item in SPRINT_ISSUES:
        fields = {
            "project": {"key": PROJECT_KEY},
            "issuetype": {"name": item["type"]},
            "summary": item["summary"],
            "parent": {"key": key_map[item["parent"]]},
            fids["Story point estimate"]: item["points"],
        }
        key = create_issue(fields)
        print(f"  {item['parent']} -> {key} ({item['type']}: {item['summary']}, "
              f"{item['points']}pt, {item['sprint']} sprint)")
        if item["sprint"] == "closed":
            closed_keys.append(key)
            closed_statuses.append(item["status"])
        else:
            active_keys.append(key)
            active_statuses.append(item["status"])

    setup_sprint_metrics(closed_keys, closed_statuses, active_keys, active_statuses)

    print("\nDone." if not DRY_RUN else "\nDry run complete — nothing was sent to Jira.")


if __name__ == "__main__":
    main()
