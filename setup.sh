#!/bin/bash
# setup.sh
#
# One-command bootstrap for the whole TPMO1 Jira + Grafana DORA-vis demo:
# custom fields -> seed data -> Jira datasource + folder -> dashboards.
# Safe to re-run -- every step is idempotent EXCEPT Jira issue seeding,
# which this script deliberately does not touch if the project already
# has data (see step 2): we don't delete/recreate Jira issues automatically
# under any circumstances, on principle, regardless of what this script
# could technically do.
#
# Prerequisites (see README.md for the full list):
#   - JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY set
#     (source your own envvars file before running this)
#   - `gcx` installed and logged in (`gcx login`) against the target stack
#   - Target Grafana Cloud stack has these plugins installed & enabled:
#     grafana-jira-datasource, grafana-graphviz-panel (both Enterprise
#     plugins -- need Cloud Pro/Advanced or Enterprise), plus the built-in
#     grafana-testdata-datasource (always present)
#   - The target Jira project already exists (team-managed, Scrum template
#     -- Scrum gives you the board this script's dependency-sprint logic
#     needs) -- this script does not create the project itself
#
# Usage: ./setup.sh

set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/5: checking prerequisites ==="
python3 check_setup.py

echo
echo "=== 2/5: Jira custom fields ==="
# NOTE: assign to a variable first, then eval that variable, rather than
# `eval "$(python3 create_jira_fields.py)"` directly -- with `set -e`, a
# command substitution that's an argument to another command (eval here)
# does NOT propagate the inner command's exit code, so a real failure in
# create_jira_fields.py would silently produce empty exports and let this
# script carry on instead of stopping. Assigning to a plain variable does
# propagate correctly.
FIELD_EXPORTS=$(python3 create_jira_fields.py)
eval "$FIELD_EXPORTS"
echo "JIRA_FIELD_PILLAR_ID=$JIRA_FIELD_PILLAR_ID"
echo "JIRA_FIELD_RAG_ID=$JIRA_FIELD_RAG_ID"
echo "JIRA_FIELD_NARRATIVE_ID=$JIRA_FIELD_NARRATIVE_ID"
echo "JIRA_FIELD_PHASE_ID=$JIRA_FIELD_PHASE_ID"
echo "JIRA_FIELD_START_DATE_ID=$JIRA_FIELD_START_DATE_ID"
echo "JIRA_FIELD_BLOCKED_BY_ID=$JIRA_FIELD_BLOCKED_BY_ID"
echo "JIRA_FIELD_POINTS_ID=$JIRA_FIELD_POINTS_ID"
export JIRA_FIELD_PILLAR_ID JIRA_FIELD_RAG_ID JIRA_FIELD_NARRATIVE_ID JIRA_FIELD_PHASE_ID \
       JIRA_FIELD_START_DATE_ID JIRA_FIELD_BLOCKED_BY_ID JIRA_FIELD_POINTS_ID

echo
echo "=== 3/5: Jira seed data ==="
# NOTE: the modern /rest/api/3/search/jql endpoint does NOT return a "total"
# field (that was the deprecated /rest/api/3/search endpoint) -- checking
# for one here always silently read as 0/missing regardless of how many
# issues actually existed, defeating this whole guard. Check whether the
# `issues` list is non-empty instead.
HAS_ISSUES=$(curl -s -G -u "$JIRA_EMAIL:$JIRA_API_TOKEN" "$JIRA_BASE_URL/rest/api/3/search/jql" \
  --data-urlencode "jql=project=$JIRA_PROJECT_KEY" --data-urlencode "maxResults=1" \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('issues', [])))")
if [ "$HAS_ISSUES" != "0" ]; then
  echo "Project $JIRA_PROJECT_KEY already has issues -- skipping seed."
  echo "(This script never deletes/reseeds Jira data automatically. If you want a clean"
  echo " reseed, delete the project's issues yourself first, then rerun this script.)"
else
  echo "Project $JIRA_PROJECT_KEY is empty -- seeding..."
  python3 jira.py
fi

echo
echo "=== 4/5: Grafana datasource + folder ==="
eval "$(python3 setup_grafana.py)"
echo "GRAFANA_FOLDER_UID=$GRAFANA_FOLDER_UID"
echo "JIRA_DATASOURCE_UID=$JIRA_DATASOURCE_UID"
echo "TESTDATA_DATASOURCE_UID=$TESTDATA_DATASOURCE_UID"
export GRAFANA_FOLDER_UID JIRA_DATASOURCE_UID TESTDATA_DATASOURCE_UID

echo
echo "=== 5/5: build + push dashboards ==="
python3 build_dashboards.py
./push_dashboards.sh

echo
echo "=== Done ==="
echo "Folder: $(gcx api "/api/folders/$GRAFANA_FOLDER_UID" -o json 2>/dev/null | tail -n +2 | python3 -c "import json,sys; print(json.load(sys.stdin)['url'])" 2>/dev/null || echo "/dashboards/f/$GRAFANA_FOLDER_UID")"
