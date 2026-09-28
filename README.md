# TPMO1 Jira + Grafana DORA-vis demo

A disposable, repeatable asset: seeds a realistic Jira portfolio dataset and
builds a folder of Grafana dashboards on top of it (RAG/status reporting,
cross-pillar dependency tracking, delivery metrics, a mock Azure DevOps/DORA
dashboard, and a Jira+DORA correlation view). Built so a new SE can stand
this up against their own Jira site and Grafana Cloud stack from one command,
without redoing the exploratory work that went into building it.

## What you get

Seven dashboards in a "TPMO1 Transformation Portfolio" folder:

| Dashboard | What it shows |
|---|---|
| MT Status Reporting | RAG/status overview, escalations, upcoming milestones |
| Cross-Pillar Dependency | Live dependency tracking via a plain-text `Blocked By` field (see below for why not native Jira issue links) |
| Delivery Metrics | Sprint velocity, lead/cycle time, work-item/defect counts |
| Azure DevOps Engineering Metrics (Mock) | Engineering delivery + DORA metrics, via Grafana's built-in TestData source (no real Azure DevOps connection) |
| Portfolio & Engineering Health by Pillar | Real Jira data next to the mock DORA data, correlated by pillar |
| Transformation Roadmap (Partial) | Deliberately minimal — matches the source requirements doc's own "partial" verdict on this use case |
| Payments Platforms' KANBAN | Steering-committee card view (To-Do/In Delivery/Done), colour-coded by pillar — also carries a `Jira project` dashboard variable so a viewer can point it at a different project on the same site without regenerating anything |

## Prerequisites

1. **A Jira Cloud site and project** you can administer, with:
   - The project already created (**team-managed, Scrum template** — Scrum
     gives you the board `jira.py`'s sprint logic needs; this asset does not
     create the project itself)
   - An API token for your account ([manage here](https://id.atlassian.com/manage-profile/security/api-tokens))
2. **A Grafana Cloud stack** with these plugins installed and enabled:
   - `grafana-jira-datasource` (Enterprise — needs Cloud Pro/Advanced or Enterprise)
   - `grafana-graphviz-panel` (Enterprise — same licensing requirement)
   - `grafana-testdata-datasource` (built-in, always present)
3. **`gcx`** installed and logged in against the target stack (`gcx login`)

**One Jira project per Grafana stack at a time.** The dashboard uids, folder,
and datasource name are all fixed constants, not derived from
`JIRA_PROJECT_KEY` -- so running this a second time for a *different* Jira
project on the *same* Grafana stack overwrites the first project's live
dashboards and datasource credentials in place (confirmed live: this is
exactly what happened switching this demo from one test project to
another). Fine for the intended use -- each SE on their own personal
Grafana Cloud stack -- but don't point two different active projects at one
shared stack expecting them to coexist.

## Quick start

```bash
# 1. Set your Jira credentials (copy envvars.example if one exists, or just export directly)
export JIRA_BASE_URL="https://your-site.atlassian.net"
export JIRA_EMAIL="you@example.com"
export JIRA_API_TOKEN="your-api-token"        # never commit this
export JIRA_PROJECT_KEY="YOURKEY"

# 2. Check both halves are actually wired up before running anything else
python3 check_setup.py

# 3. Run everything
./setup.sh
```

`check_setup.py` is the debug tool: run it any time something's failing and
you're not sure whether the problem is on the Grafana/gcx side or the Jira
side — it checks both independently and tells you exactly what's missing,
rather than letting a downstream script fail two layers removed from the
real cause.

## What `setup.sh` actually does

One command, five idempotent steps:

1. **`check_setup.py`** — verifies gcx login, required plugins, Jira auth,
   project/board existence. Missing custom fields are reported but don't
   block the run (step 2 creates them).
2. **`create_jira_fields.py`** — creates the 6 custom fields `jira.py`
   depends on (Pillar, RAG Status, Narrative, Delivery Phase, Start Date,
   Blocked By), including select-list options. Skips any that already exist.
3. **`jira.py`** — seeds the dataset (25 Epics, 4 milestones, 10 dependency
   edges, 40 sprint issues across a closed + an active sprint). **Refuses to
   run if the project already has issues** — this never auto-deletes or
   reseeds on top of existing data, on principle. If you want a clean
   reseed, delete the project's issues yourself first (see Troubleshooting).
4. **`setup_grafana.py`** — finds-or-creates the Jira datasource and the
   dashboard folder, and discovers the stack's TestData datasource uid.
5. **`build_dashboards.py` + `push_dashboards.sh`** — generates and pushes
   all 7 dashboard JSON manifests.

Every step except Jira seeding is safe to rerun any number of times.

## The one step that genuinely can't be automated

Jira Cloud has no public API for attaching a newly-created custom field to
a **team-managed** project's issue-type layout — confirmed empirically, not
assumed. `create_jira_fields.py` creates the fields themselves (including
select options), but the first time you seed a *brand new* project, you'll
likely need to do this once per field:

1. Open any Epic in the project.
2. Click **"+ Add field"** in the details panel.
3. Search for and add: Pillar, RAG Status, Narrative, Delivery Phase, Start
   Date, Blocked By.

`create_jira_fields.py` tells you exactly which fields (if any) still need
this after it runs. If `jira.py` fails with `"...not on the appropriate
screen..."`, this is why.

## Cross-Pillar Dependency's Assistant panel

That dashboard deliberately does **not** ship a pre-built dependency graph.
The top panel explains why and gives the exact prompt to hand Grafana
Assistant to generate one live — Grafana inferring the graph structure from
the `Dependencies by pillar` table's own data is the actual point being
demonstrated, not a canned diagram. Worth walking a new SE through doing
this themselves once.

## Payments Platforms' KANBAN's template file

Unlike the other six dashboards, this one started as a hand-built (not
generated) dashboard, so it's kept as a JSON template with placeholder
tokens (`dashboards/_payments_kanban_template.json.tmpl`) rather than
rebuilt as `panel_base()` calls -- that preserves its exact hand-tuned
layout untouched while still substituting the three things that make it
portable: project key, datasource uid, and the Pillar field id.
`build_dashboards.py`'s `build_payments_kanban()` does the substitution and
writes the result to `dashboards/payments-kanban.json`, same as every other
dashboard here. It also carries a live `Jira project` dashboard variable
(defaulting to whichever project it was generated for) so a viewer can
retarget it at a *different* project on the *same* Jira site without
rerunning anything -- that variable can't help across sites, though, since
a fresh site allocates entirely new field ids for every custom field
(confirmed live: this dashboard silently broke, showing zero rows in its
Kanban tables, the first time it was pointed at a second demo project on a
different site, purely from stale hardcoded ids left over from the first
one) -- hence still needing the real, generation-time substitution for the
part a variable can't reach.

## Repeatable workflows

- **Rerun after changing `build_dashboards.py`**: `python3 build_dashboards.py && ./push_dashboards.sh`
  (or push a single dashboard: `gcx api /api/dashboards/db -d @dashboards/<name>.json`)
- **Point this at a different stack/site**: `setup_grafana.py` exports
  `GRAFANA_FOLDER_UID`/`JIRA_DATASOURCE_UID`/`TESTDATA_DATASOURCE_UID`, and
  `create_jira_fields.py` exports `JIRA_FIELD_*_ID` for every custom field --
  `build_dashboards.py` reads all of these from the environment (falling
  back to this demo's own first-run values if unset), so nothing is
  hardcoded to one specific stack, Jira site, or set of field ids. Field ids
  in particular are NOT portable across projects/spaces even on the same
  site -- Jira allocates a fresh `customfield_XXXXX` every time
  `create_jira_fields.py` creates a field, never reusing one, even for an
  identically-named field in a different project. Confirmed live: rerunning
  this whole pipeline against a second, brand-new space produced 6 entirely
  different field ids from the first run.
- **Reusing this datasource for a different Jira account/token**:
  `setup_grafana.py` always re-pushes the current environment's credentials
  onto the existing "Jira (TPMO1 demo)" datasource, even if one already
  exists. This matters because the datasource is found-by-name and reused
  across runs -- without refreshing it, a second SE running this against
  their own Jira site/token would silently keep querying with whoever set
  it up first. Confirmed live: every dashboard query returned a clean but
  empty result (HTTP 200, zero rows) with a stale token -- the mismatch
  only became visible via the datasource's own health check reporting 401,
  not via any dashboard-level error.
- **Full clean reseed**: delete the project's issues yourself (never done
  automatically — see below), then rerun `./setup.sh`.

## Troubleshooting

Run `python3 check_setup.py` first, always — it's read-only and will tell
you which half is broken before you waste time debugging the wrong script.

**"Project already has issues" but you want a clean reseed:**
```bash
source envvars
python3 -c "
import requests, os
base = os.environ['JIRA_BASE_URL'].rstrip('/')
auth = (os.environ['JIRA_EMAIL'], os.environ['JIRA_API_TOKEN'])
token = None
keys = []
while True:
    params = {'jql': f\"project={os.environ['JIRA_PROJECT_KEY']}\", 'fields': 'key', 'maxResults': 100}
    if token: params['nextPageToken'] = token
    r = requests.get(f'{base}/rest/api/3/search/jql', auth=auth, params=params).json()
    keys.extend(i['key'] for i in r['issues'])
    if r.get('isLast', True): break
    token = r.get('nextPageToken')
print(len(keys), 'issues found — review before deleting')
"
# Review the count, then delete for real (rate-limited to avoid 429s):
python3 -c "
import requests, os, time
base = os.environ['JIRA_BASE_URL'].rstrip('/')
auth = (os.environ['JIRA_EMAIL'], os.environ['JIRA_API_TOKEN'])
token = None
while True:
    params = {'jql': f\"project={os.environ['JIRA_PROJECT_KEY']}\", 'fields': 'key', 'maxResults': 100}
    if token: params['nextPageToken'] = token
    r = requests.get(f'{base}/rest/api/3/search/jql', auth=auth, params=params).json()
    for i in r['issues']:
        dr = requests.delete(f\"{base}/rest/api/3/issue/{i['key']}\", auth=auth, params={'deleteSubtasks': 'true'})
        print(i['key'], dr.status_code)
        time.sleep(0.3)
    if r.get('isLast', True): break
    token = r.get('nextPageToken')
"
```
This is deliberately not wrapped in a script in this repo — deleting Jira
data should always be something you consciously run yourself, never a side
effect of another command.

**Sprint errors ("must specify a sprint which has not been completed")**:
shouldn't happen — `jira.py`'s `ensure_sprints()` only ever reuses
`future`-state sprints and creates new ones otherwise, specifically to avoid
this. If you see it anyway, something's calling the Agile API outside that
function; check for local edits.

**Dashboards don't match `dashboards/*.json`**: someone edited a dashboard
directly in the Grafana UI. Rerun `./push_dashboards.sh` to overwrite the
live version with the generated one (source of truth is always the JSON in
this repo, not whatever's live).

**A dashboard column is blank even though the row count looks right (e.g.
`Blocked By` shows no values but the row count matches)**: check for a
second custom field with the same name on the Jira site --
`GET /rest/api/3/field/search?query=<field name>` (unfiltered, unlike plain
`GET /rest/api/3/field`, which only shows fields already on a screen and
will hide this) will list every match. This happens because Jira allows
multiple custom fields with an identical name, and neither the field
picker in the UI nor a JQL clause on that field name can tell them apart by
sight -- confirmed live, twice, on this exact repo: once when
`create_jira_fields.py`'s own duplicate-detection used the screen-filtered
endpoint (fixed -- it now uses `field/search`), and once when a human
picked the wrong one of two identically-named entries in the UI's own field
picker while attaching a field by hand. If you hit this, delete whichever
field is the stale duplicate (`DELETE /rest/api/3/field/{id}`, async --
poll the `Location` header's task URL) and re-attach/re-populate the
survivor. Related: if a JQL clause looks like `"Field Name[Short text]"`
(a bracketed type suffix), that syntax exists specifically to disambiguate
between same-named fields -- it only works while the ambiguity exists, and
breaks (matches nothing) once you're down to a single field with that name
again. Drop the suffix once there's only one.
