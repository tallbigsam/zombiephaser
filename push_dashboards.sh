#!/bin/bash
# push_dashboards.sh
#
# Pushes every dashboard manifest in dashboards/*.json via the classic
# /api/dashboards/db endpoint (NOT `gcx dashboards create`, which defaults to
# the dashboard.grafana.app/v2 resource API and silently drops a legacy
# `panels` array on write -- confirmed this session). Each manifest carries
# a fixed uid and "overwrite": true, so re-running this is idempotent: it
# updates dashboards in place rather than creating duplicates.
#
# Run `python3 build_dashboards.py` first to regenerate all manifests from
# source. azure-devops-mock.json's *content* (the mock data model)
# originated from a Grafana Assistant prompt, and payments-kanban.json's
# panel layout originated as a hand-built dashboard, but both are now
# generated (from `dashboards/_payments_kanban_template.json.tmpl` for the
# latter) like everything else -- there is nothing hand-maintained outside
# this repo. The .tmpl file is deliberately not matched by the *.json glob
# below -- it holds unsubstituted placeholders, not a pushable dashboard.
#
# Usage: ./push_dashboards.sh

set -euo pipefail
cd "$(dirname "$0")"

for f in dashboards/*.json; do
  echo "--- pushing $f ---"
  gcx api /api/dashboards/db -d "@$f" -o json
done
