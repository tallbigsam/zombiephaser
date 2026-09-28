---
name: jira-space-setup
description: |
  Interactively walks a new SE through setting up the Atlassian/Jira side of
  this repo's Grafana + Jira DORA-vis demo -- creating a new Jira "Space"
  (Atlassian's UI rename of "Project" -- the REST API, JQL, and every
  script in this repo still say "project"), getting an API token, filling
  in .env, and clearing the one manual custom-field-attachment step --
  before running check_setup.py / setup.sh. Use this whenever someone is
  setting up this repo for the first time, asks how to create a Jira
  project or space for this demo, seems confused about "project" vs
  "space" terminology anywhere in Jira, or hits a "not on the appropriate
  screen" error from create_jira_fields.py or jira.py. Trigger this
  proactively for any new-SE onboarding request for this repo, even if
  they don't mention Jira, projects, or spaces by name -- getting the
  Jira side right is the actual blocker most people hit first.
---

# Jira Space setup for this repo

Walk the person through getting a fresh Jira site ready for this repo, one
step at a time. Ask where they already are in the process before dumping
the whole thing on them -- this skill exists specifically because the Jira
UI is easy to get lost in, so the point is to go slower than usual and
confirm each step actually landed, not to recite a checklist.

## Say this first, before anything else

Atlassian renamed Jira "Projects" to "Spaces" in the UI (verified live
against Atlassian's own current docs while building this repo -- not a
guess, and not this repo's own terminology drifting). Explain it in plain
terms, roughly:

> Jira's UI now calls what used to be a "Project" a "Space" -- you'll see
> "Spaces" in the sidebar, "Create space", "Space settings". Every script
> in this repo, and Jira's own REST API and JQL underneath, never got
> renamed -- they still say "project" everywhere (`project = TPMO1`,
> `JIRA_PROJECT_KEY`, `projectKeyOrId`). So when a script or error message
> says "project" and the screen in front of you says "space", they're the
> same thing. This mismatch is genuinely the most disorienting part of
> setting this up, not something you're missing.

Keep an ear out for this resurfacing through the rest of the walkthrough --
"I don't see a Projects menu" or "where's the project key" almost always
means they're looking for the old name. Reassure and point at the Space
equivalent rather than letting them search for something that isn't there
anymore.

## Say this too, before Step 4

Set this expectation before they run anything, not after they hit it as a
surprise: **this repo can create the custom fields it needs in your Jira
account automatically, but it cannot attach them to your specific space --
that one step is always manual.** This isn't a gap in the automation, it's
a real Jira Cloud platform limitation (confirmed empirically while building
this repo, on a team-managed space specifically): there is no public API
for attaching an existing custom field to a space's work-type layout, full
stop. `create_jira_fields.py` (run by `setup.sh`) handles everything it
can -- creating the fields, adding select-list options -- and then always
tells you exactly which fields still need that one click, every single
time you run it, even on a space you've set up before. That's deliberate,
not a bug: custom fields live at the Jira SITE level, not per-space, so if
you've ever run this demo against another space on the same site, the
fields already exist and get reused -- but "exists somewhere on this site"
is not the same as "attached to THIS space", and there's no reliable way
to check that distinction by API either (also confirmed empirically). So
expect this manual step on *every* space you set this up for, not just the
first one -- see Step 5 for exactly how to do it.

## Step 1: Create the space

Ask whether they already have a Jira Cloud site (something like
`https://their-company.atlassian.net`). If not, that's an atlassian.com
signup this skill doesn't cover -- point them there first.

Once they're logged into their site:

1. Hover over **Spaces** in the left sidebar, select **Create space**.
2. Pick a template -- **this choice matters**: use a **Scrum** template,
   not Kanban. The seed script (`jira.py`) creates real sprints and needs
   the board a Scrum template comes with; Kanban won't give it one, and
   the sprint logic will have nowhere to go.
3. Select **Use template**, give the space any name.
4. Choose **Team-managed**, not **Company-managed**, when asked. Every
   script here assumes team-managed -- it's also *why* the manual step in
   Step 5 below exists at all, since that's a team-managed-specific
   platform gap, not something company-managed spaces hit.
5. Select **Create**.

Jira generates a **space key** automatically (something like `GDT`) --
point this out explicitly, it's easy to miss and it's the value that goes
into `JIRA_PROJECT_KEY` in Step 3. They can rename it later via
Space settings > Details if they want something more memorable, but the
auto-generated one works fine as-is.

## Step 2: Get an API token

Send them to
https://id.atlassian.com/manage-profile/security/api-tokens to create a
token. Flag clearly: **the token is shown once, at creation** -- if they
click away before copying it, the only fix is revoking it and making a new
one. Any label is fine.

## Step 3: Fill in `.env`

This repo reads four env vars from a local `.env` file in the repo root
(already covered by `.gitignore`, so this is safe -- it won't get
committed). Confirm the file's current shape before assuming the format --
this repo uses `export VAR=value` lines so it can be `source`d directly:

```
export JIRA_BASE_URL=https://their-site.atlassian.net
export JIRA_EMAIL=their-account-email@example.com
export JIRA_API_TOKEN=<the token from Step 2>
export JIRA_PROJECT_KEY=<the space key from Step 1>
```

Help them create or edit that file directly. Don't have them paste the raw
token into chat if it's avoidable -- write it straight into the file.

## Step 4: Run the automated checks

Once the space exists, the token's made, and `.env` is filled in:

```bash
source .env
python3 check_setup.py
```

`check_setup.py` is read-only and checks the Grafana/gcx side and the Jira
side independently -- if something's wrong, it says exactly what, so don't
guess at failures, just read what it reports and fix that specific thing.

Once it passes clean, run:

```bash
./setup.sh
```

One command, five idempotent steps: custom fields, seed data, Grafana
datasource/folder, dashboards.

## Step 5: The manual click -- do this every time, not just the first

`create_jira_fields.py` (run automatically by `setup.sh`) creates the 6
custom fields this demo needs -- Pillar, RAG Status, Narrative, Delivery
Phase, Start Date, Blocked By -- via the API, select-list options included.
It then **always** prints all 6 fields as needing a manual attach-check --
not only the ones it just created. That's not leftover caution, it's
because "already exists" and "attached to your space" are genuinely
different things (see the callout above): a field created for someone
else's space on this same site will show as already existing and get
reused, but it still needs attaching here. Re-selecting an already-attached
field in the picker is a harmless no-op, so just work through the whole
list it prints rather than trying to guess which ones actually need it.

Use **Space settings** for this -- it's the only path that works before
`jira.py` has seeded anything, since a brand-new space has no issues yet to
open. Confirmed live: at this point in the walkthrough there is nothing to
click "+ Add field" on.

- **Via Space settings** (use this one right after `create_jira_fields.py`,
  before seeding): next to the space name in the sidebar, select
  **More actions (•••)**, then **Space settings**, then **Fields**, then
  **Add fields** -- search for the field by name and select it. Both lead
  to the same field picker either way, letting you search for an
  *existing* field rather than creating a new one -- that's the part to
  use here, since the field already exists from the API call.
- **Via a work item** (only usable once at least one issue exists -- e.g.
  after `jira.py` has run, or if this comes up again later for a field
  added after seeding): open any Epic, in the Details section select
  **Edit fields**, then search for the field by name in the panel that
  opens and select it.

If `jira.py` ever fails later with an error mentioning "not on the
appropriate screen", this is what's missing -- send them back here instead
of letting them assume something's actually broken.

## Wrapping up

Once `setup.sh` finishes clean, point them at `README.md` for what the
dashboards actually show. Worth mentioning: everything here is safe to
rerun except Jira seeding itself, which deliberately refuses to run twice
on top of existing data -- see the README's Troubleshooting section if they
ever want a genuinely clean reseed.
