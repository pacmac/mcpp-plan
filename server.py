#!/usr/bin/env python3
"""Local HTTP server for the mcpp-plan area stats view.

Usage:
    python3 server.py [--port 8080] [--host 127.0.0.1]
"""

import argparse
import importlib.util
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PKG_PATH = Path(__file__).resolve().parent


def _load_pkg():
    def _load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    _load("mcpp_plan", PKG_PATH / "__init__.py")
    db = _load("mcpp_plan.db", PKG_PATH / "db.py")
    _load("mcpp_plan.config", PKG_PATH / "config.py")
    ctx = _load("mcpp_plan.context", PKG_PATH / "context.py")
    return db, ctx


_db, _ctx = _load_pkg()


def _connect():
    conn = _db.connect(_db.default_db_path())
    _db.ensure_schema(conn)
    return conn


def _list_projects(conn):
    rows = conn.execute(
        "SELECT id, project_name FROM project ORDER BY project_name"
    ).fetchall()
    return [{"id": r["id"], "name": r["project_name"]} for r in rows]


def _get_project_by_name(conn, name):
    row = conn.execute(
        "SELECT id FROM project WHERE project_name = ?", (name,)
    ).fetchone()
    return row["id"] if row else None


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {
  --ground:#F6F7F9; --panel:#FFFFFF; --panel-2:#EEF0F4;
  --ink:#141922; --ink-2:#3D4653; --muted:#68717F; --hair:#D8DCE3; --hair-2:#E7EAEF;
  --accent:#33409B; --accent-soft:#E6E8F6;
  --proved:#1B6E45; --proved-soft:#E1F0E7;
  --open-col:#9A6410; --open-soft:#F7EEDD;
  --partial-col:#6B4FA0; --partial-soft:#EDE6F8;
  --inert:#8A93A3; --inert-soft:#ECEEF2;
  --unverified:#B03A2E; --unverified-soft:#F8E6E3;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0F1216; --panel:#171B21; --panel-2:#1E2430;
  --ink:#E8ECF2; --ink-2:#B0BAC9; --muted:#7C8492; --hair:#2A3040; --hair-2:#232A36;
  --accent:#96A2F0; --accent-soft:#1E2248;
  --proved:#63C795; --proved-soft:#0E2A1E;
  --open-col:#DDA850; --open-soft:#2A2010;
  --partial-col:#B99DE8; --partial-soft:#241A38;
  --inert:#7C8492; --inert-soft:#1A1E26;
  --unverified:#F08579; --unverified-soft:#2E130F;
}}
:root[data-theme="dark"]{
  --ground:#0F1216; --panel:#171B21; --panel-2:#1E2430;
  --ink:#E8ECF2; --ink-2:#B0BAC9; --muted:#7C8492; --hair:#2A3040; --hair-2:#232A36;
  --accent:#96A2F0; --accent-soft:#1E2248;
  --proved:#63C795; --proved-soft:#0E2A1E;
  --open-col:#DDA850; --open-soft:#2A2010;
  --partial-col:#B99DE8; --partial-soft:#241A38;
  --inert:#7C8492; --inert-soft:#1A1E26;
  --unverified:#F08579; --unverified-soft:#2E130F;
}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;font-family:'IBM Plex Sans',system-ui,sans-serif;font-size:14px;line-height:1.5;background:var(--ground);color:var(--ink)}
a{color:var(--accent);text-decoration:none}
/* nav */
.nav{background:var(--panel);border-bottom:1px solid var(--hair);padding:0 20px;display:flex;align-items:center;gap:16px;height:44px}
.nav-brand{font-weight:600;font-size:14px;color:var(--ink)}
.nav-sep{color:var(--hair);user-select:none}
.nav select{font-family:inherit;font-size:13px;background:var(--panel-2);color:var(--ink);border:1px solid var(--hair);border-radius:5px;padding:4px 8px;cursor:pointer}
.nav-right{margin-left:auto;font-size:11px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
/* shell */
.shell{max-width:960px;margin:0 auto;padding:24px 20px 48px}
/* masthead */
.masthead{margin-bottom:20px}
.masthead-top{display:flex;align-items:baseline;gap:10px;margin-bottom:4px}
.proj-name{font-size:20px;font-weight:600;letter-spacing:-0.3px}
.proj-label{font-size:11px;font-weight:500;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.proj-desc{color:var(--ink-2);font-size:13px;max-width:65ch;margin:0 0 8px}
.read-at{font-size:11px;color:var(--muted);font-family:'IBM Plex Mono',monospace}
/* figures */
.figures{display:flex;gap:1px;background:var(--hair);border:1px solid var(--hair);border-radius:8px;overflow:hidden;margin-bottom:24px}
.fig{flex:1;background:var(--panel);padding:14px 16px}
.fig-val{font-size:28px;font-weight:600;line-height:1;font-variant-numeric:tabular-nums;font-family:'IBM Plex Mono',monospace;color:var(--ink)}
.fig-val.c-proved{color:var(--proved)} .fig-val.c-open{color:var(--open-col)} .fig-val.c-accent{color:var(--accent)}
.fig-label{font-size:11px;font-weight:500;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:2px}
/* section head */
.section-head{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 8px}
/* table */
.areas-wrap{border:1px solid var(--hair);border-radius:8px;overflow:hidden;margin-bottom:24px;overflow-x:auto}
table{width:100%;border-collapse:collapse;background:var(--panel)}
thead th{background:var(--panel-2);padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);text-align:left;white-space:nowrap;border-bottom:1px solid var(--hair)}
thead th:first-child{padding-left:0}
tbody tr{border-bottom:1px solid var(--hair-2)}
tbody tr:last-child{border-bottom:none}
tbody td{padding:10px 12px;vertical-align:top;font-size:13px}
.stripe-cell{width:3px;padding:0!important;min-width:3px}
.stripe{width:3px;height:100%;min-height:40px}
.stripe.signed-off{background:var(--proved)} .stripe.partial{background:var(--partial-col)}
.stripe.open{background:var(--unverified)} .stripe.not-started{background:var(--inert)}
.area-name{font-weight:600;color:var(--ink)}
.area-class{display:inline-block;font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);background:var(--panel-2);border:1px solid var(--hair);border-radius:3px;padding:1px 5px;margin-left:6px;vertical-align:middle}
.area-desc{color:var(--ink-2);font-size:12px;margin-top:2px}
.pill{display:inline-flex;align-items:center;font-size:11px;font-weight:500;border-radius:100px;padding:2px 8px;white-space:nowrap}
.pill.signed-off{background:var(--proved-soft);color:var(--proved)}
.pill.partial{background:var(--partial-soft);color:var(--partial-col)}
.pill.open{background:var(--unverified-soft);color:var(--unverified)}
.pill.not-started{background:var(--inert-soft);color:var(--inert)}
.tasks-col{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--ink-2);white-space:nowrap;font-variant-numeric:tabular-nums}
.tasks-col .dn{color:var(--proved);font-weight:500}
.deps-col{font-size:11px;color:var(--muted);max-width:200px}
.dep-tag{display:inline-block;font-size:10px;font-family:'IBM Plex Mono',monospace;padding:1px 5px;border-radius:3px;margin:1px 2px 1px 0;border:1px solid currentColor}
.dep-tag.blocked{color:var(--unverified)} .dep-tag.clear{color:var(--proved)}
/* empty */
.empty-state{padding:40px 20px;text-align:center;color:var(--muted);font-size:13px;background:var(--panel)}
/* panels */
.panels{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:600px){.panels{grid-template-columns:1fr}.figures{flex-direction:column;gap:0}}
.panel{background:var(--panel);border:1px solid var(--hair);border-radius:8px;overflow:hidden}
.panel-head{padding:10px 14px;background:var(--panel-2);border-bottom:1px solid var(--hair);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.panel-head .count{float:right;font-family:'IBM Plex Mono',monospace;color:var(--ink-2);font-weight:500}
.panel-row{display:flex;align-items:center;gap:8px;padding:6px 14px;font-size:13px}
.dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.dot.startable{background:var(--proved)} .dot.ns{background:var(--inert)}
.area-n{font-weight:500;color:var(--ink)}
.area-d{color:var(--muted);font-size:12px;margin-left:auto;font-family:'IBM Plex Mono',monospace}
.panel-empty{padding:20px 14px;color:var(--muted);font-size:12px;text-align:center}
/* no-project */
.no-proj{padding:60px 20px;text-align:center;color:var(--muted)}
.no-proj h2{color:var(--ink);margin:0 0 8px}
</style>
</head>
<body>
<nav class="nav">
  <span class="nav-brand">mcpp-plan</span>
  <span class="nav-sep">/</span>
  <select id="proj-select" onchange="location.href='/?project='+encodeURIComponent(this.value)"></select>
  <span class="nav-right" id="nav-ts"></span>
</nav>

<div class="shell" id="shell"></div>

<script>
const DATA = __DATA__;
const PROJECTS = __PROJECTS__;

function state(a){
  if(a.open===0&&a.complete>0) return 'signed-off';
  if(a.open>0&&a.complete>0) return 'partial';
  if(a.open>0) return 'open';
  return 'not-started';
}
function stateLabel(s){return{'signed-off':'Signed off','partial':'Partial','open':'Open','not-started':'Not started'}[s];}
function descFirst(md){return(md||'').split('\n')[0].replace(/[`*_]/g,'').slice(0,120);}
function fmtRead(iso){const d=new Date(iso);return d.toISOString().replace('T',' ').slice(0,16)+' UTC';}

// Nav
const sel=document.getElementById('proj-select');
PROJECTS.forEach(p=>{
  const o=document.createElement('option');
  o.value=p.name; o.textContent=p.name;
  if(DATA&&p.name===DATA.project.name) o.selected=true;
  sel.appendChild(o);
});

if(!DATA){
  document.getElementById('shell').innerHTML='<div class="no-proj"><h2>No project selected</h2><p>Pick a project from the dropdown above.</p></div>';
} else {
  const proj=DATA.project, s=DATA.summary, areas=DATA.areas;
  document.getElementById('nav-ts').textContent=fmtRead(DATA.read_at);

  const signedOff=new Set(areas.filter(a=>state(a)==='signed-off').map(a=>a.name));
  const startable=areas.filter(a=>{
    if(state(a)==='signed-off') return false;
    if(!a.depends||!a.depends.length) return true;
    return a.depends.every(d=>signedOff.has(d));
  });
  const notStarted=areas.filter(a=>state(a)==='not-started');
  const pct=s.total>0?Math.round(s.signed_off/s.total*100):0;

  let tableHtml='';
  if(!areas.length){
    tableHtml='<div class="empty-state">No areas defined — use <code>plan_area_new</code> to create areas.</div>';
  } else {
    const rows=areas.map(a=>{
      const st=state(a);
      const cls=a.class?`<span class="area-class">${a.class}</span>`:'';
      const desc=descFirst(a.description_md);
      const deps=(a.depends||[]).map(d=>`<span class="dep-tag ${signedOff.has(d)?'clear':'blocked'}">${d}</span>`).join('')||'<span style="color:var(--hair)">—</span>';
      return `<tr>
        <td class="stripe-cell"><div class="stripe ${st}"></div></td>
        <td><div><span class="area-name">${a.name}</span>${cls}</div>${desc?`<div class="area-desc">${desc}</div>`:''}</td>
        <td><span class="pill ${st}">${stateLabel(st)}</span></td>
        <td class="tasks-col"><span class="dn">${a.complete}</span>/${a.complete+a.open}</td>
        <td class="deps-col">${deps}</td>
      </tr>`;
    }).join('');
    tableHtml=`<table><thead><tr><th style="width:3px;padding:0"></th><th>Area</th><th>State</th><th>Tasks</th><th>Depends</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  const startRows=startable.length
    ?startable.map(a=>`<div class="panel-row"><div class="dot startable"></div><span class="area-n">${a.name}</span><span class="area-d">${a.open>0?a.open+' open':'no tasks'}</span></div>`).join('')
    :'<div class="panel-empty">None startable right now</div>';
  const nsRows=notStarted.length
    ?notStarted.map(a=>`<div class="panel-row"><div class="dot ns"></div><span class="area-n">${a.name}</span><span class="area-d">${a.class||''}</span></div>`).join('')
    :'<div class="panel-empty">None</div>';

  document.getElementById('shell').innerHTML=`
    <div class="masthead">
      <div class="masthead-top"><span class="proj-name">${proj.name}</span><span class="proj-label">Area Progress</span></div>
      <p class="proj-desc">${descFirst(proj.description_md)}</p>
      <span class="read-at">${fmtRead(DATA.read_at)}</span>
    </div>
    <div class="figures">
      <div class="fig"><div class="fig-val c-proved">${s.signed_off}</div><div class="fig-label">Signed off</div></div>
      <div class="fig"><div class="fig-val">${s.total}</div><div class="fig-label">Total areas</div></div>
      <div class="fig"><div class="fig-val c-open">${s.tasks_open}</div><div class="fig-label">Tasks open</div></div>
      <div class="fig"><div class="fig-val">${s.tasks_complete}</div><div class="fig-label">Tasks complete</div></div>
      <div class="fig"><div class="fig-val c-accent">${pct}%</div><div class="fig-label">Done</div></div>
    </div>
    <p class="section-head">Areas</p>
    <div class="areas-wrap">${tableHtml}</div>
    <div class="panels">
      <div class="panel"><div class="panel-head">Startable now <span class="count">${startable.length}</span></div><div>${startRows}</div></div>
      <div class="panel"><div class="panel-head">Not started <span class="count">${notStarted.length}</span></div><div>${nsRows}</div></div>
    </div>`;
}
</script>
</body>
</html>"""


def _render(data, projects):
    project_name = data["project"]["name"] if data else "mcpp-plan"
    html = HTML_TEMPLATE.replace("{title}", f"{project_name} — Areas")
    html = html.replace("__DATA__", json.dumps(data, default=str))
    html = html.replace("__PROJECTS__", json.dumps(projects))
    return html.encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path != "/":
            self.send_response(404)
            self.end_headers()
            return

        qs = parse_qs(parsed.query)
        project_name = (qs.get("project") or [None])[0]

        conn = _connect()
        try:
            projects = _list_projects(conn)
            if not project_name and projects:
                project_name = projects[0]["name"]

            if project_name:
                pid = _get_project_by_name(conn, project_name)
                data = _ctx.area_stats(conn, pid) if pid else None
            else:
                data = None
        finally:
            conn.close()

        body = _render(data, projects)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser(description="mcpp-plan area stats server")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    server = HTTPServer((args.host, args.port), Handler)
    print(f"Serving on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
