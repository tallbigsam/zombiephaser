#!/usr/bin/env python3
"""
build_dashboards.py

Generates the 4 TPMO1 demo dashboard JSON manifests (classic Grafana
dashboard schema, pushed via `gcx api /api/dashboards/db`, NOT the newer
dashboard.grafana.app/v2 resource API -- v2 silently drops a legacy `panels`
array on write, keeping only `title`; the classic /api/dashboards/db endpoint
round-trips it correctly, confirmed live this session).

Key data-shape findings baked into this generator (discovered by probing
/api/ds/query directly against the grafana-jira-datasource this session):
  - key, summary, duedate/created/updated/statuscategorychangedate,
    Start Date, Blocked By, Story point estimate all come back clean
    (plain string/number/epoch-ms).
  - status, Pillar, RAG Status, Delivery Phase, issuelinks all come back as
    Go `map[...]` stringified reprs, NOT JSON -- not directly displayable.
    Filtering by them via JQL still works fine (JQL runs server-side against
    real Jira, unaffected by the plugin's display serialization). For
    DISPLAY, regex value-mappings keyed on a stable substring (statusCategory
    .key for status; the trailing `value:X]` for our select-list fields)
    clean them up without needing a transformation Grafana doesn't have.
  - Narrative (ADF text field) is *also* messy and, unlike the fields above,
    there's no finite vocabulary to map -- every value is free text. No
    stock Grafana transformation does regex-capture value replacement, so
    Narrative is dropped from every panel rather than shown raw.
  - Sprint (customfield_10020) is likewise messy; sprint scoping is done via
    JQL (`sprint = "TPMO1 Sprint 1"`) instead of ever selecting/displaying it.

IMPORTANT: transformation options (groupBy fields, filterByValue fieldName,
organize renameByName, joinByField byField) and field-config override
matchers (byName) all key off the RAW field name the datasource emits
(e.g. "customfield_10258", "status", "key") -- NOT the human label the
query's field descriptor sets as displayName (e.g. "RAG Status"). Confirmed
live: using the label instead of the raw name causes groupBy/overrides to
silently no-op.

Writes JSON files to dashboards/*.json.
"""

import json
import os

# Overridable via env vars so this script is portable to a fresh stack --
# setup.sh exports these after creating (or finding) the datasource/folder.
# The defaults are this demo's own known-good values, kept for convenience
# when rerunning against this same stack without re-sourcing setup output.
DS = {"type": "grafana-jira-datasource", "uid": os.environ.get("JIRA_DATASOURCE_UID", "cfyxuzvcc1iioe")}
FOLDER_UID = os.environ.get("GRAFANA_FOLDER_UID", "bfyy21ok7bgn4d")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards")

# The Jira project this run's dashboards should query. Every custom field id
# below is ALSO run-specific -- Jira allocates a fresh customfield_XXXXX id
# every time create_jira_fields.py creates a field, they are never reused
# across projects/spaces even when the field name is identical. setup.sh's
# create_jira_fields.py step exports these after creating (or finding) each
# field, same portability reasoning as DS/FOLDER_UID above. The defaults are
# this demo's own first run, kept only for convenience when rerunning
# against that same original data without re-sourcing setup output.
PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "TPMO1")

# raw field names as emitted by the datasource (see module docstring)
RAW = {
    "key": "key", "summary": "summary", "status": "status",
    "pillar": os.environ.get("JIRA_FIELD_PILLAR_ID", "customfield_10257"),
    "rag": os.environ.get("JIRA_FIELD_RAG_ID", "customfield_10258"),
    "phase": os.environ.get("JIRA_FIELD_PHASE_ID", "customfield_10260"),
    "start_date": os.environ.get("JIRA_FIELD_START_DATE_ID", "customfield_10261"),
    "due": "duedate", "updated": "updated",
    "blocked_by": os.environ.get("JIRA_FIELD_BLOCKED_BY_ID", "customfield_10263"),
    "points": os.environ.get("JIRA_FIELD_POINTS_ID", "customfield_10016"),
    "created": "created", "status_cat_changed": "statuscategorychangedate",
}

_next_id = [1]


def next_id():
    _next_id[0] += 1
    return _next_id[0]


def f(id_, label, type_="string", system=""):
    """A field descriptor for a query target -- the full shape matters,
    a stripped-down object silently drops the field entirely."""
    return {"custom": "", "id": id_, "items": "", "label": label,
            "system": system, "text": label, "type": type_, "value": id_}

F_KEY = f(RAW["key"], "Key")
F_SUMMARY = f(RAW["summary"], "Summary", system="summary")
F_STATUS = f(RAW["status"], "Status", system="status")
F_PILLAR = f(RAW["pillar"], "Pillar")
F_RAG = f(RAW["rag"], "RAG Status")
F_PHASE = f(RAW["phase"], "Delivery Phase")
F_START = f(RAW["start_date"], "Start Date", type_="date")
F_DUE = f(RAW["due"], "Due Date", type_="date", system="duedate")
F_UPDATED = f(RAW["updated"], "Updated", type_="date", system="updated")
F_BLOCKED_BY = f(RAW["blocked_by"], "Blocked By")
F_POINTS = f(RAW["points"], "Story point estimate", type_="number")
F_CREATED = f(RAW["created"], "Created", type_="date", system="created")
F_STATUS_CAT_CHANGED = f(RAW["status_cat_changed"], "Status Category Changed", type_="date",
                          system="statuscategorychangedate")


def target(ref_id, jql, fields, extra=None):
    t = {"refId": ref_id, "datasource": DS, "domain": "issues", "queryType": "",
         "jql": jql, "maxDataPoints": 200, "fields": fields}
    if extra:
        t.update(extra)
    return t


def regex_mappings(pairs):
    """pairs: list of (substring, display_text, color). Matches the Go
    map[...] repr's substring, since there's no way to fully parse it.
    Wrapped in .* on both sides -- Grafana's regex value mapping appears to
    require a full-string match, not a contains-style test."""
    return [
        {"type": "regex", "options": {"pattern": f".*{sub}.*",
         "result": {"text": text, "color": color, "index": i}}}
        for i, (sub, text, color) in enumerate(pairs)
    ]

RAG_MAPPINGS = regex_mappings([
    (r"value:Red\]", "Red", "red"),
    (r"value:Amber\]", "Amber", "orange"),
    (r"value:Green\]", "Green", "green"),
])
PILLAR_MAPPINGS = regex_mappings([
    (r"value:Payments Modernisation\]", "Payments Modernisation", "blue"),
    (r"value:Core Banking Migration\]", "Core Banking Migration", "purple"),
    (r"value:Digital Channels\]", "Digital Channels", "light-blue"),
    (r"value:Risk & Compliance\]", "Risk & Compliance", "dark-orange"),
])
PHASE_MAPPINGS = regex_mappings([
    (r"value:Discovery\]", "Discovery", "text"),
    (r"value:Build\]", "Build", "blue"),
    (r"value:Test\]", "Test", "orange"),
    (r"value:Deploy\]", "Deploy", "purple"),
    (r"value:Live\]", "Live", "green"),
])
STATUS_MAPPINGS = regex_mappings([
    (r"statusCategory\.key:new", "To Do", "blue-gray"),
    (r"statusCategory\.key:indeterminate", "In Progress", "yellow"),
    (r"statusCategory\.key:done", "Done", "green"),
])


# Bar gauge panels default to collapsing all rows in a frame down to one
# calculated value -- for a groupBy result (one row per category), we need
# every row shown as its own bar instead.
BARGAUGE_SHOW_ALL_ROWS = {
    "reduceOptions": {"values": True, "calcs": [], "fields": ""},
    "displayMode": "gradient", "orientation": "horizontal",
}
# "basic" (solid fill in the row's own threshold color) instead of "gradient"
# (always paints red-to-green across the whole bar regardless of the actual
# value) -- used where the threshold color itself needs to read unambiguously
# as good/bad at a glance.
BARGAUGE_SHOW_ALL_ROWS_BASIC = {
    "reduceOptions": {"values": True, "calcs": [], "fields": ""},
    "displayMode": "basic", "orientation": "horizontal",
}
PIECHART_SHOW_ALL_ROWS = {"reduceOptions": {"values": True, "calcs": [], "fields": ""}}


def field_override(raw_field_name, mappings):
    return {
        "matcher": {"id": "byName", "options": raw_field_name},
        "properties": [{"id": "mappings", "value": mappings}],
    }


def panel_base(title, panel_type, x, y, w, h, targets, transformations=None, overrides=None,
               extra_options=None, description="", datasource=None, defaults=None):
    p = {
        "id": next_id(),
        "type": panel_type,
        "title": title,
        "description": description,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": datasource or DS,
        "targets": targets,
        "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []},
        "options": extra_options or {},
    }
    if transformations:
        p["transformations"] = transformations
    return p


def thresholds(base_color, step_color, step_value):
    """A 2-step threshold: base_color below step_value, step_color at/above
    it. Use base_color=good/step_color=bad for lower-is-better metrics
    (change failure rate, MTTR, lead time), and the reverse for
    higher-is-better ones (build success rate, deploy frequency)."""
    return {"mode": "absolute", "steps": [
        {"color": base_color, "value": None},
        {"color": step_color, "value": step_value},
    ]}


def group_by(dimension_raw_names, calc_raw_name, calc="count", filter_refid=None):
    if isinstance(dimension_raw_names, str):
        dimension_raw_names = [dimension_raw_names]
    fields = {d: {"aggregations": [], "operation": "groupby"} for d in dimension_raw_names}
    fields[calc_raw_name] = {"aggregations": [calc], "operation": "aggregate"}
    t = {"id": "groupBy", "options": {"fields": fields}}
    if filter_refid:
        t["filter"] = {"id": "byRefId", "options": filter_refid}
    return t


def reduce_sum(raw_name=RAW["points"]):
    return {"id": "reduce", "options": {"reducers": ["sum"], "fields": {raw_name: True}}}


def text_panel(title, x, y, w, h, body):
    return {
        "id": next_id(), "type": "text", "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "options": {"mode": "markdown", "content": body},
    }


# TestData is a built-in datasource auto-provisioned per stack; its uid is
# stack-specific, not something we create -- setup.sh discovers it live via
# `gcx api /api/datasources` and exports it, same portability reasoning as
# DS/FOLDER_UID above.
TESTDATA_DS = {"type": "grafana-testdata-datasource", "uid": os.environ.get("TESTDATA_DATASOURCE_UID", "aep7ozkk1hjwga")}


def mock_bottleneck_panel(x, y, w, h):
    """A REAL panel (bar gauge), backed by Grafana's built-in TestData
    datasource's csv_content scenario -- not a live Jira query -- showing
    what 'Dependency bottleneck ranking' would look like if the live
    dataset had a real many-to-one bottleneck. It doesn't: every one of the
    10 live dependency edges is a distinct 1:1 blocker/dependent pair
    (verified live: 10 dependents, 10 distinct Blocked By values, every
    count = 1). Title/description make the fabrication unmistakable."""
    csv = (f"Blocked By,Dependents\n{PROJECT_KEY}-9001 (mock),4\n{PROJECT_KEY}-9002 (mock),3\n"
           f"{PROJECT_KEY}-9003 (mock),2\n")
    return panel_base(
        "⚠️ Example bottleneck -- MOCK DATA, NOT LIVE", "bargauge", x, y, w, h,
        [{"refId": "A", "datasource": TESTDATA_DS, "scenarioId": "csv_content", "csvContent": csv}],
        extra_options=BARGAUGE_SHOW_ALL_ROWS,
        datasource=TESTDATA_DS,
        description="This panel queries Grafana's built-in TestData datasource, not Jira -- it is "
                    "fabricated example data. The live dataset currently has no blocker cited by more than "
                    "one dependent (see 'Dependency bottleneck ranking' above, correctly showing real counts "
                    "of 1 for all 10 live edges). This illustrates what that panel would show once a real "
                    "many-to-one bottleneck exists in the Jira data.",
    )


def dashboard(uid, title, description, panels, tags):
    return {
        "dashboard": {
            "id": None, "uid": uid, "title": title, "description": description,
            "tags": tags, "timezone": "browser", "schemaVersion": 39,
            "time": {"from": "now-90d", "to": "now+30d"},
            "panels": panels,
        },
        "folderUid": FOLDER_UID,
        "overwrite": True,
    }


# ---------------------------------------------------------------------------
# Dashboard 1: MT Status Reporting
# ---------------------------------------------------------------------------

def build_mt_status():
    base_jql = f"project = {PROJECT_KEY} AND issuetype = Epic"
    panels = [
        panel_base(
            "Initiatives by RAG", "bargauge", 0, 0, 8, 8,
            [target("A", base_jql, [F_KEY, F_RAG])],
            transformations=[group_by(RAW["rag"], RAW["key"], "count")],
            overrides=[field_override(RAW["rag"], RAG_MAPPINGS)],
            extra_options=BARGAUGE_SHOW_ALL_ROWS,
            description="Count of Epics per RAG value.",
        ),
        panel_base(
            "Portfolio health overview", "table", 8, 0, 16, 8,
            [target("A", base_jql, [F_KEY, F_SUMMARY, F_PILLAR, F_RAG, F_PHASE, F_DUE])],
            overrides=[field_override(RAW["pillar"], PILLAR_MAPPINGS),
                       field_override(RAW["rag"], RAG_MAPPINGS),
                       field_override(RAW["phase"], PHASE_MAPPINGS)],
        ),
        panel_base(
            "Projects requiring escalation (RAG = Red)", "table", 0, 8, 12, 8,
            [target("A", base_jql + ' AND "RAG Status" = Red', [F_KEY, F_SUMMARY, F_PILLAR, F_DUE])],
            overrides=[field_override(RAW["pillar"], PILLAR_MAPPINGS)],
        ),
        panel_base(
            "Recently updated initiatives", "table", 12, 8, 12, 8,
            [target("A", base_jql + " ORDER BY updated DESC", [F_KEY, F_SUMMARY, F_PILLAR, F_RAG, F_UPDATED],
                    extra={"limit": 10})],
            overrides=[field_override(RAW["pillar"], PILLAR_MAPPINGS),
                       field_override(RAW["rag"], RAG_MAPPINGS)],
            description="Status text itself can't be displayed cleanly by this plugin version, so this uses "
                        "RAG + last-updated time as the 'what changed recently' signal instead.",
        ),
        panel_base(
            "Programmes approaching milestones (next 30 days)", "table", 0, 16, 24, 6,
            [target("A", f'project = {PROJECT_KEY} AND issuetype = Task AND duedate <= "30d" ORDER BY duedate ASC',
                    [F_KEY, F_SUMMARY, F_DUE])],
        ),
    ]
    return dashboard(
        "tpmo1-mt-status", "MT Status Reporting", "RAG/status overview for MT reporting -- Phase 1 use case.",
        panels, ["tpmo1", "mt-status"],
    )


# ---------------------------------------------------------------------------
# Dashboard 2: Cross-Pillar Dependency
# ---------------------------------------------------------------------------

# NOTE: no "[Short text]" type-suffix on "Blocked By" -- that JQL
# disambiguator is only needed when multiple fields share a name (it was
# in fact needed earlier THIS session, while an old orphaned duplicate
# "Blocked By" field briefly existed alongside the real one -- see
# create_jira_fields.py's docstring). With only one such field on the site,
# the suffixed form matches nothing at all; confirmed live.
DEPENDENTS_JQL = f'project = {PROJECT_KEY} AND issuetype = Epic AND "Blocked By" is not EMPTY'

# The exact prompt to hand Grafana Assistant to generate a live dependency
# graph panel for this dashboard -- deliberately NOT pre-built here. Letting
# Assistant build it live (rather than shipping a frozen DOT string) is the
# actual demo: Grafana inferring the graph structure from the data itself.
GRAPHVIZ_ASSISTANT_PROMPT = (
    "Using the Key, Blocked By, and Summary columns from the 'Dependencies by pillar' table on this "
    "dashboard, build me a Graphviz panel that shows how our Jira backlog epics depend on each other. "
    "Each epic should be its own node, labeled with its key and summary, with an arrow pointing from the "
    "blocker to the epic it's blocking. Colour the nodes by RAG status — red for at-risk, amber for "
    "caution, green for on-track — and use grey for anything without a RAG status, like milestones. "
    "Lay it out left-to-right so the chains are easy to follow, and add it to the top of this dashboard."
)


def build_dependency():
    dependents_jql = DEPENDENTS_JQL
    active_blockers_jql = f"project = {PROJECT_KEY} AND issuetype = Epic AND status != Done AND duedate < now()"

    # NOTE: a proper cross-frame join (organize/rename + joinByField, and the
    # legacy seriesToColumns id) was tried here and, after live testing
    # (screenshots via `gcx dashboards snapshot`), reliably failed to merge
    # the two queries in this Grafana version -- the rename step never
    # produced a raw field name the join could actually match on, no matter
    # which filter-scoping matcher id was used (byRefId, byFrameRefID).
    # Rather than ship a silently-broken "join" panel, this is two small,
    # independently-correct tables the viewer cross-references by eye: is a
    # "Blocked By" key in the dependents table also a "Key" in the active
    # blockers table below it? Same analytical answer, no fragile transform.
    overdue_panel = panel_base(
        "Currently active blockers (not done, overdue)", "table", 0, 16, 24, 6,
        [target("A", active_blockers_jql + " ORDER BY duedate ASC", [F_KEY, F_SUMMARY, F_DUE])],
        description="Cross-reference against the 'Blocked By' column above: any row here whose Key matches a "
                    "'Blocked By' value up there is a dependency with a genuinely active, overdue blocker.",
    )

    panels = [
        text_panel(
            "\U0001f4a1 Try this: generate a live dependency graph with Grafana Assistant", 0, 0, 24, 8,
            "Grafana can dynamically infer the \"blocked by\" relationships straight from the "
            "**Dependencies by pillar** table below and render them as a live Graphviz graph -- no "
            "hand-built DOT string required. Rather than ship a pre-built graph here, generate it "
            "yourself with Grafana Assistant using this exact prompt:\n\n"
            f"```\n{GRAPHVIZ_ASSISTANT_PROMPT}\n```",
        ),
        panel_base(
            "Dependencies by pillar", "table", 0, 8, 24, 8,
            [target("A", dependents_jql, [F_KEY, F_SUMMARY, F_PILLAR, F_BLOCKED_BY, F_RAG])],
            overrides=[field_override(RAW["pillar"], PILLAR_MAPPINGS), field_override(RAW["rag"], RAG_MAPPINGS)],
        ),
        overdue_panel,
        panel_base(
            "Amber/Red dependencies", "table", 0, 24, 12, 8,
            [target("A", dependents_jql + ' AND ("RAG Status" = Amber OR "RAG Status" = Red)',
                    [F_KEY, F_SUMMARY, F_PILLAR, F_RAG, F_BLOCKED_BY])],
            overrides=[field_override(RAW["pillar"], PILLAR_MAPPINGS), field_override(RAW["rag"], RAG_MAPPINGS)],
        ),
        panel_base(
            "Dependency bottleneck ranking", "bargauge", 12, 24, 12, 8,
            [target("A", dependents_jql, [F_KEY, F_BLOCKED_BY])],
            transformations=[group_by(RAW["blocked_by"], RAW["key"], "count")],
            extra_options=BARGAUGE_SHOW_ALL_ROWS,
            description="Which blocker key is cited by the most dependents.",
        ),
        mock_bottleneck_panel(0, 32, 24, 8),
    ]
    return dashboard(
        "tpmo1-dependency", "Cross-Pillar Dependency",
        "Dependency tracking via the plain-text Blocked By field -- Phase 1 use case.",
        panels, ["tpmo1", "dependency"],
    )


# ---------------------------------------------------------------------------
# Dashboard 3: Delivery Metrics
# ---------------------------------------------------------------------------

def build_delivery_metrics():
    sprint_issues_jql = f"project = {PROJECT_KEY} AND issuetype in (Story, Bug)"
    panels = [
        panel_base(
            "Work items by status", "piechart", 0, 0, 8, 8,
            [target("A", sprint_issues_jql, [F_KEY, F_STATUS])],
            transformations=[group_by(RAW["status"], RAW["key"], "count")],
            overrides=[field_override(RAW["status"], STATUS_MAPPINGS)],
            extra_options=PIECHART_SHOW_ALL_ROWS,
        ),
        panel_base(
            "Defects by status", "piechart", 8, 0, 8, 8,
            [target("A", sprint_issues_jql + " AND issuetype = Bug", [F_KEY, F_STATUS])],
            transformations=[group_by(RAW["status"], RAW["key"], "count")],
            overrides=[field_override(RAW["status"], STATUS_MAPPINGS)],
            extra_options=PIECHART_SHOW_ALL_ROWS,
        ),
        panel_base(
            "Average lead/cycle time (days, done items)", "stat", 16, 0, 8, 8,
            [target("A", sprint_issues_jql + " AND status = Done",
                    [F_KEY, F_CREATED, F_STATUS_CAT_CHANGED])],
            transformations=[
                {"id": "calculateField", "options": {
                    "mode": "reduceRow",
                    # "include" is required -- reduceRow mode does not
                    # default to "every numeric field in the row" when it's
                    # omitted, it defaults to none, silently producing no
                    # "Difference" field at all (confirmed live: the final
                    # stat panel showed "No data", not a ~0 value, because
                    # the "Days" field the last transform step reduces over
                    # never existed).
                    "reduce": {"reducer": "diff", "include": [RAW["created"], RAW["status_cat_changed"]]},
                    "alias": "Difference",
                }},
                {"id": "calculateField", "options": {
                    "mode": "binary", "alias": "Days",
                    "binary": {"left": "Difference", "operator": "/", "right": "86400000"},
                }},
                # The "reduce" transform has no field-selection option of
                # its own (a "fields" key under its options, in any shape,
                # either errors out or is silently ignored -- confirmed
                # live by isolating each step in a throwaway debug panel).
                # It just reduces every field it's given. So select down to
                # only "Days" first with filterFieldsByName, THEN reduce
                # with no field filter -- that combination is what actually
                # renders a value instead of "No data".
                {"id": "filterFieldsByName", "options": {"include": {"names": ["Days"]}}},
                {"id": "reduce", "options": {"reducers": ["mean"]}},
            ],
            description="Uses Created and Status Category Changed (both clean date fields) to compute days "
                        "in flight. Caveat: this seed dataset was created moments ago, so every issue's "
                        "Created/Status-Category-Changed are only seconds apart -- the mechanism is real, but "
                        "the number will read ~0 until this runs against issues with real history.",
        ),
        panel_base(
            "Sprint velocity: completed vs. estimated points", "bargauge", 0, 8, 24, 6,
            [
                # sprint in openSprints()/closedSprints(), NOT a literal
                # sprint name/number -- jira.py's ensure_sprints() only ever
                # reuses `future`-state sprints and creates new, higher-
                # numbered ones otherwise (on purpose, to never touch a
                # closed sprint), so the actual sprint name after any reseed
                # on the same board is NOT reliably "Sprint 1"/"Sprint 2".
                # Confirmed live: a second seed run on the same ZOM board
                # produced "Sprint 3"/"Sprint 4", silently breaking this
                # panel (empty bars, no error) until it was rewritten to
                # resolve the current closed/open sprint dynamically instead
                # of assuming a fixed number.
                target("A", f'project = {PROJECT_KEY} AND sprint in closedSprints()', [F_KEY, F_POINTS]),
                target("B", f'project = {PROJECT_KEY} AND sprint in closedSprints() AND status = Done',
                       [F_KEY, F_POINTS]),
                target("C", f'project = {PROJECT_KEY} AND sprint in openSprints()', [F_KEY, F_POINTS]),
                target("D", f'project = {PROJECT_KEY} AND sprint in openSprints() AND status = Done',
                       [F_KEY, F_POINTS]),
            ],
            transformations=[
                reduce_sum() | {"filter": {"id": "byRefId", "options": "A"}},
                reduce_sum() | {"filter": {"id": "byRefId", "options": "B"}},
                reduce_sum() | {"filter": {"id": "byRefId", "options": "C"}},
                reduce_sum() | {"filter": {"id": "byRefId", "options": "D"}},
            ],
            overrides=[
                {"matcher": {"id": "byFrameRefID", "options": "A"},
                 "properties": [{"id": "displayName", "value": "Closed sprint - estimated"}]},
                {"matcher": {"id": "byFrameRefID", "options": "B"},
                 "properties": [{"id": "displayName", "value": "Closed sprint - completed"}]},
                {"matcher": {"id": "byFrameRefID", "options": "C"},
                 "properties": [{"id": "displayName", "value": "Active sprint - estimated"}]},
                {"matcher": {"id": "byFrameRefID", "options": "D"},
                 "properties": [{"id": "displayName", "value": "Active sprint - completed so far"}]},
            ],
            description="4 JQL-scoped queries (sprint x done-or-not), each reduced to a single sum of Story "
                        "point estimate -- avoids ever needing to read the messy native Sprint field.",
        ),
        text_panel(
            "About this dashboard", 0, 14, 24, 3,
            "**Note:** all 40 sprint issues in this demo dataset were created moments ago as part of a seed "
            "script, so system `created`/`resolutiondate` timestamps are effectively identical across every "
            "issue. A true trend-analysis-over-time panel (issues created/resolved per week) and the lead/cycle "
            "time figure above have nothing meaningful to show yet with this seed data -- that's a data-recency "
            "limitation of the demo dataset, not a Jira/Grafana limitation, and mirrors the source doc's own "
            "point that reporting quality depends on real data maturity.",
        ),
    ]
    return dashboard(
        "tpmo1-delivery-metrics", "Delivery Metrics",
        "Work item counts, sprint velocity, lead/cycle time -- Phase 1 use case.",
        panels, ["tpmo1", "delivery-metrics"],
    )


# ---------------------------------------------------------------------------
# Dashboard 4: Transformation Roadmap (Partial)
# ---------------------------------------------------------------------------

def build_roadmap():
    panels = [
        text_panel(
            "About this dashboard", 0, 0, 24, 3,
            "**Partial view**, consistent with the source doc's own assessment: a full roadmap needs "
            "consistently-captured milestones and dependency sequencing across the whole portfolio. This is a "
            "sortable list, not a Gantt chart -- Grafana has no native Gantt panel, and forcing one would "
            "misrepresent how ready this use case actually is.",
        ),
        panel_base(
            "Initiative timeline (sorted by start date)", "table", 0, 3, 24, 10,
            [target("A", f'project = {PROJECT_KEY} AND issuetype = Epic ORDER BY "Start Date" ASC',
                    [F_KEY, F_SUMMARY, F_PILLAR, F_PHASE, F_START, F_DUE, F_RAG])],
            overrides=[field_override(RAW["pillar"], PILLAR_MAPPINGS),
                       field_override(RAW["phase"], PHASE_MAPPINGS),
                       field_override(RAW["rag"], RAG_MAPPINGS)],
        ),
        panel_base(
            "Upcoming milestones", "table", 0, 13, 24, 6,
            [target("A", f"project = {PROJECT_KEY} AND issuetype = Task ORDER BY duedate ASC",
                    [F_KEY, F_SUMMARY, F_DUE])],
        ),
    ]
    return dashboard(
        "tpmo1-roadmap", "Transformation Roadmap (Partial)",
        "Deliberately minimal -- matches the source doc's 'Partially, dependent on data availability' verdict.",
        panels, ["tpmo1", "roadmap"],
    )


# ---------------------------------------------------------------------------
# Dashboard 5: Azure DevOps Engineering Metrics (Mock)
#
# Content/data model came from Grafana Assistant (`gcx assistant prompt`),
# prompted with the real Azure DevOps plugin's query types/fields (Projects,
# Repositories, Pull Requests, Builds, Pipelines, Releases, Release
# Deployments) and the source doc's asks (engineering delivery
# visibility, pipeline monitoring, release readiness, DORA metrics). The
# Assistant CLI turned out to have no dashboard-write tool exposed, and its
# attempt to hand back full dashboard JSON got truncated mid-response, so
# the JSON itself is built here with the same proven TestData/bargauge
# pattern as the mock bottleneck panel -- but the mock data values, the 4
# project names (deliberately matching the Jira pillars for later
# correlation), and the deliberately-uneven health gradient are Assistant's.
# ---------------------------------------------------------------------------

ADO_MOCK_NOTICE = (
    "⚠️ **MOCK / ILLUSTRATIVE DATA — NOT A LIVE AZURE DEVOPS CONNECTION.**\n\n"
    "Every panel on this dashboard is generated by Grafana's built-in **TestData** datasource to "
    "fabricate realistic-looking Azure DevOps Projects, Repositories, Pull Requests, Builds, Build "
    "Definitions, Pipelines, Pipeline Runs, Releases, Release Definitions, and Release Deployments. "
    "Field names and value sets (Result: succeeded/failed/canceled/partiallySucceeded; Status: "
    "completed/inProgress; Operation Status; Source Branch; Last Attempt Only) mirror what the real "
    "Grafana Azure DevOps data source plugin returns, but **no organization is connected**.\n\n"
    "The 4 mock \"Projects\" — **Payments Modernisation**, **Core Banking Migration**, **Digital "
    "Channels**, **Risk & Compliance** — are named to match the 4 pillars on the companion "
    "Jira-based portfolio dashboards, for later correlation.\n\n"
    "DORA metrics (Deployment Frequency, Lead Time for Changes, Change Failure Rate, MTTR) are "
    "**derived/computed** from the mock build & release data below — the Azure DevOps plugin does "
    "not provide DORA metrics natively."
)

# Project, Repositories, Open PRs, Builds(30d), Build Success %, Active Pipelines,
# Releases(30d), Deploy Freq/wk, Change Failure %, MTTR (h), Lead Time (h), Health
ADO_MOCK_ROWS = [
    ("Payments Modernisation", 4, 3, 142, 96, 6, 24, 5.2, 4, 0.8, 4, "Healthy"),
    ("Core Banking Migration", 6, 7, 98, 86, 5, 13, 2.8, 12, 4.0, 18, "Stable"),
    ("Digital Channels", 5, 14, 76, 68, 4, 7, 1.5, 22, 14.0, 72, "At Risk"),
    ("Risk & Compliance", 3, 21, 41, 45, 2, 3, 0.6, 38, 48.0, 144, "Critical"),
]
ADO_MOCK_HEALTH_COLORS = {"Healthy": "green", "Stable": "blue", "At Risk": "orange", "Critical": "red"}


def _ado_csv(*col_indices, header=None):
    cols = header or ["Project"] + [str(i) for i in col_indices]
    lines = [",".join(cols)]
    for row in ADO_MOCK_ROWS:
        lines.append(",".join(str(row[i]) for i in (0, *col_indices)))
    return "\n".join(lines) + "\n"


def _ado_testdata_panel(title, panel_type, x, y, w, h, csv_content, extra_options=None, description="",
                          overrides=None, defaults=None):
    return panel_base(
        title, panel_type, x, y, w, h,
        [{"refId": "A", "datasource": TESTDATA_DS, "scenarioId": "csv_content", "csvContent": csv_content}],
        extra_options=extra_options, description=description, datasource=TESTDATA_DS, overrides=overrides,
        defaults=defaults,
    )


def build_azure_devops_mock():
    overview_csv = _ado_csv(1, 2, 3, 4, 5, 6, header=[
        "Project", "Repositories", "Open Pull Requests", "Builds (Last 30d)",
        "Build Success Rate %", "Active Pipelines", "Releases (Last 30d)",
    ])
    health_mappings = [
        {"type": "value", "options": {h: {"text": h, "color": c, "index": i}}}
        for i, (h, c) in enumerate(ADO_MOCK_HEALTH_COLORS.items())
    ]

    panels = [
        text_panel("MOCK DATA NOTICE", 0, 0, 24, 6, ADO_MOCK_NOTICE),
        _ado_testdata_panel(
            "Projects & Delivery Overview (Mock)", "table", 0, 6, 24, 8, overview_csv,
            description="Engineering delivery visibility + release readiness at a glance, per mock project. "
                        "Mock/illustrative -- see notice panel above.",
        ),
        _ado_testdata_panel(
            "Build success rate % (mock) -- pipeline monitoring", "bargauge", 0, 14, 12, 7,
            _ado_csv(4, header=["Project", "Build Success Rate %"]),
            extra_options=BARGAUGE_SHOW_ALL_ROWS_BASIC,
            defaults={"thresholds": thresholds("red", "green", 70)},  # higher = better
        ),
        _ado_testdata_panel(
            "Deployment frequency, per week (mock) -- DORA", "bargauge", 12, 14, 12, 7,
            _ado_csv(7, header=["Project", "Deploy Frequency"]),
            extra_options=BARGAUGE_SHOW_ALL_ROWS_BASIC,
            defaults={"thresholds": thresholds("red", "green", 2)},  # higher = better
        ),
        _ado_testdata_panel(
            "Change failure rate % (mock) -- DORA", "bargauge", 0, 21, 8, 7,
            _ado_csv(8, header=["Project", "Change Failure Rate"]),
            extra_options=BARGAUGE_SHOW_ALL_ROWS_BASIC,
            defaults={"thresholds": thresholds("green", "red", 15)},  # lower = better
        ),
        _ado_testdata_panel(
            "MTTR, hours (mock) -- DORA", "bargauge", 8, 21, 8, 7,
            _ado_csv(9, header=["Project", "MTTR"]),
            extra_options=BARGAUGE_SHOW_ALL_ROWS_BASIC,
            defaults={"thresholds": thresholds("green", "red", 10)},  # lower = better
        ),
        _ado_testdata_panel(
            "Lead time for changes, hours (mock) -- DORA", "bargauge", 16, 21, 8, 7,
            _ado_csv(10, header=["Project", "Change Lead Hrs"]),
            extra_options=BARGAUGE_SHOW_ALL_ROWS_BASIC,
            defaults={"thresholds": thresholds("green", "red", 24)},  # lower = better
            description="Approximated consistently with the other health-tier signals above -- not a figure "
                        "Assistant computed directly, since real build-to-deploy timestamps don't exist here.",
        ),
        _ado_testdata_panel(
            "Overall health rating (mock)", "table", 0, 28, 24, 6,
            _ado_csv(11, header=["Project", "Health"]),
            overrides=[field_override("Health", health_mappings)],
        ),
    ]
    return dashboard(
        "tpmo1-ado-mock", "Azure DevOps Engineering Metrics (Mock)",
        "Mock engineering delivery + DORA metrics, built from a Grafana Assistant-generated data model -- "
        "Phase 2 use case. Not a live Azure DevOps connection.",
        panels, ["tpmo1", "mock", "azure-devops", "dora", "illustrative"],
    )


# ---------------------------------------------------------------------------
# Dashboard 6: Portfolio & Engineering Health by Pillar
#
# The "one dashboard regardless of source" ambition the TPMO1 doc names
# directly, made real: real Jira portfolio data (RAG by pillar) and mock
# Azure DevOps engineering/DORA data (dashboard 5's data, by the same 4
# pillar names) side by side, keyed on Pillar -- the one dimension both
# sides share. No cross-datasource transform/join (that class of thing
# proved unreliable earlier this session even within a single datasource);
# the viewer cross-references by eye, same pattern as the dependency
# dashboard's "currently active blockers" panel.
# ---------------------------------------------------------------------------

def build_correlation():
    health_mappings = [
        {"type": "value", "options": {h: {"text": h, "color": c, "index": i}}}
        for i, (h, c) in enumerate(ADO_MOCK_HEALTH_COLORS.items())
    ]
    header = ["Project", "Build Success Rate %", "Deploy Frequency", "Change Failure Rate", "MTTR", "Health"]
    lines = [",".join(header)]
    for row in ADO_MOCK_ROWS:
        lines.append(",".join(str(v) for v in (row[0], row[4], row[7], row[8], row[9], row[11])))
    engineering_csv = "\n".join(lines) + "\n"

    panels = [
        text_panel(
            "About this dashboard", 0, 0, 24, 7,
            "This is the \"single dashboard regardless of source\" the TPMO1 doc asks about, made concrete: "
            "**real Jira portfolio data** (left/top table, live) next to **mock Azure DevOps engineering/DORA "
            "data** (right/bottom table, via TestData -- see the companion Azure DevOps Engineering Metrics "
            "(Mock) dashboard) -- correlated on the one dimension both sides share: **Pillar**.\n\n"
            "No cross-datasource join is used -- that class of transform proved unreliable even within a "
            "single datasource earlier in this build, so as with the Dependency dashboard, the viewer "
            "cross-references the two tables by eye: find a pillar in both and compare.\n\n"
            "**Caveat:** the mock engineering health tiers were generated independently of the live Jira RAG "
            "data (Assistant never saw it) -- any agreement or contradiction between the two tables below is "
            "coincidental, not engineered. That's still the right way to read this dashboard: it demonstrates "
            "the diagnostic *pattern* -- does a pillar's self-reported portfolio status agree with its "
            "engineering delivery signals, or reveal a blind spot -- not a real finding about this bank.",
        ),
        panel_base(
            "Portfolio RAG by pillar (Jira -- LIVE)", "table", 0, 7, 12, 13,
            [target("A", f"project = {PROJECT_KEY} AND issuetype = Epic", [F_PILLAR, F_RAG, F_KEY])],
            transformations=[group_by([RAW["pillar"], RAW["rag"]], RAW["key"], "count")],
            overrides=[field_override(RAW["pillar"], PILLAR_MAPPINGS), field_override(RAW["rag"], RAG_MAPPINGS)],
        ),
        _ado_testdata_panel(
            "Engineering & DORA health by pillar (Mock)", "table", 12, 7, 12, 13, engineering_csv,
            overrides=[field_override("Health", health_mappings)],
            description="Same mock data model as the Azure DevOps Engineering Metrics (Mock) dashboard, "
                        "condensed. Not live.",
        ),
        text_panel(
            "What to look for", 0, 20, 24, 8,
            "Reading the two tables above together, per pillar (using this dataset's actual live numbers "
            "at the time this was built):\n\n"
            "- **Payments Modernisation**: portfolio shows the *heaviest* Red flagging (4 Red Epics) of any "
            "pillar, yet its mock engineering data is the *healthiest* (96% build success, lowest change "
            "failure rate). Worth checking whether that Red status reflects a business/vendor dependency "
            "risk rather than a delivery/engineering one -- which matches this pillar's actual blocked Epic "
            "narrative (a vendor certification delay, not a broken pipeline).\n"
            "- **Digital Channels** and **Risk & Compliance**: portfolio shows few or no Red Epics, but mock "
            "engineering data rates them 'At Risk' / 'Critical' -- exactly the kind of blind spot a Jira-only "
            "view wouldn't surface, and the reason to look at both sources together.\n"
            "- **Core Banking Migration**: the one pillar where the two views broadly agree (mostly Green "
            "portfolio, 'Stable' engineering) -- a sanity-check case, not a risk case.",
        ),
    ]
    return dashboard(
        "tpmo1-correlation", "Portfolio & Engineering Health by Pillar",
        "Real Jira portfolio data + mock Azure DevOps/DORA data, correlated by pillar -- the 'single "
        "dashboard regardless of source' use case from the TPMO1 doc.",
        panels, ["tpmo1", "correlation", "dora", "mock"],
    )


# ---------------------------------------------------------------------------
# Dashboard 7: Payments Platforms' KANBAN
# ---------------------------------------------------------------------------

def build_payments_kanban():
    """Originally a one-off, hand-built dashboard (not generated by this
    script) that a steering-committee audience uses directly -- kept as a
    JSON template with placeholders rather than rebuilt as panel_base()
    calls, so its exact hand-tuned layout/styling survives untouched.
    Substitutes the same three things every other dashboard here reads from
    the environment: project key, datasource uid, and the Pillar field id
    (which -- like every custom field id in this repo -- is allocated fresh
    per Jira site and is NOT the same value twice, confirmed live when this
    dashboard broke migrating from one demo project to another before this
    templating existed).
    """
    # .json.tmpl, not .json -- so push_dashboards.sh's `dashboards/*.json`
    # glob doesn't try to push this template's raw placeholder tokens as if
    # it were itself a finished dashboard.
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards",
                                  "_payments_kanban_template.json.tmpl")
    with open(template_path) as fh:
        raw = fh.read()
    raw = raw.replace("__DS_UID__", DS["uid"])
    raw = raw.replace("__PILLAR_FIELD_ID__", RAW["pillar"])
    raw = raw.replace("__PROJECT_KEY__", PROJECT_KEY)
    db = json.loads(raw)
    db["id"] = None
    return {"dashboard": db, "folderUid": FOLDER_UID, "overwrite": True}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    builders = {
        "mt-status.json": build_mt_status,
        "cross-pillar-dependency.json": build_dependency,
        "delivery-metrics.json": build_delivery_metrics,
        "roadmap.json": build_roadmap,
        "azure-devops-mock.json": build_azure_devops_mock,
        "correlation.json": build_correlation,
        "payments-kanban.json": build_payments_kanban,
    }
    for filename, builder in builders.items():
        _next_id[0] = 1
        path = os.path.join(OUT_DIR, filename)
        with open(path, "w") as fh:
            json.dump(builder(), fh, indent=2)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
