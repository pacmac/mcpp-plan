# area-stats-server

## Gap

Viewing area progress requires an agent to call `plan_area_stats`, generate HTML,
and publish to Anthropic's artifact system. That takes minutes and requires Claude.

## Fix

A small stdlib HTTP server (`server.py`) that lives in the mcpp-plan package.
It calls `area_stats()` directly, renders HTML on each request, and serves it
on localhost. No external deps, no agent required. Sub-second response.

## Design

- `python3 server.py [--port 8080] [--host 127.0.0.1]`
- Single shared `plan.db` — all projects in the DB are available
- Project selector in the nav (dropdown or links) — one URL per project:
  `/?project=<name>` or `/?project_id=<id>`
- HTML rendered server-side from the same template used in the artifact
- Auto-refresh: `<meta http-equiv="refresh" content="30">` (optional, off by default)
- No auth — localhost only by default

## Endpoints

- `GET /` — redirect to first project, or show project list if no projects
- `GET /?project=<name>` — area stats for that project
- `GET /health` — `{"ok": true}` (for process managers)

## Files changing

- `server.py` — new file in package root

## Out of scope

- Task list views (area stats only for now)
- Auth
- Background refresh / websocket
