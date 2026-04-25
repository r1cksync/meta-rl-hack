"""Multi-page analytics dashboard for IncidentCommander.

Pages (all HTML via Chart.js CDN, no Python plotting deps):
  /dashboard                 -> Overview (reward, grade, mit/rc rates, tier)
  /dashboard/rewards         -> Reward breakdown signals
  /dashboard/tasks           -> Per-task performance grid
  /dashboard/training        -> Training progress (reward/grade/loss curves)
  /dashboard/cluster         -> Live cluster health (EKS/kind)
  /dashboard/adversarial     -> Adversarial designer history
  /dashboard/curriculum      -> Curriculum tier + mastery
  /dashboard/judge           -> Judge/persona config + rubric
  /dashboard/api             -> Endpoint catalog

All pages share a navbar and pull data from existing JSON endpoints or
from `checkpoints/<run>/metrics.jsonl`+`summary.json` on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
CHECKPOINT_ROOT = _HERE / "checkpoints"

_PAGES = [
    ("/dashboard",              "Overview"),
    ("/dashboard/rewards",      "Rewards"),
    ("/dashboard/tasks",        "Tasks"),
    ("/dashboard/training",     "Training"),
    ("/dashboard/cluster",      "Cluster"),
    ("/dashboard/aws",          "AWS"),
    ("/dashboard/adversarial",  "Adversarial"),
    ("/dashboard/curriculum",   "Curriculum"),
    ("/dashboard/judge",        "Judge"),
    ("/dashboard/api",          "API"),
]

_PPO_PAGES = [
    ("/dashboard/ppo",              "Overview"),
    ("/dashboard/ppo/rewards",      "Rewards"),
    ("/dashboard/ppo/tasks",        "Tasks"),
    ("/dashboard/ppo/training",     "Training"),
    ("/dashboard/ppo/cluster",      "Cluster"),
    ("/dashboard/ppo/aws",          "AWS"),
    ("/dashboard/ppo/adversarial",  "Adversarial"),
    ("/dashboard/ppo/curriculum",   "Curriculum"),
    ("/dashboard/ppo/judge",        "Judge"),
    ("/dashboard/ppo/api",          "API"),
]


def _nav(active: str, ds: str = "legacy") -> str:
    pages = _PPO_PAGES if ds == "ppo" else _PAGES
    items = "".join(
        f'<a href="{href}" class="nav-item{" active" if href == active else ""}">{label}</a>'
        for href, label in pages
    )
    return f'<nav class="navbar">{items}</nav>'


_LEGACY_BANNER = """
<div class="ds-banner ds-legacy">
  <div class="ds-tag">LEGACY DATASET</div>
  <div class="ds-text">
    These charts come from the <b>kube-sre-gym-style heuristic + early notebook runs</b> — the 11 hand-curated tasks in
    <code>rl-agent/scenarios/{{easy,medium,hard}}/*.json</code>, recorded into
    <code>rl-agent/checkpoints/&lt;run&gt;/metrics.jsonl</code> and
    <code>colab/logs/reward_breakdown_history.jsonl</code>. They do <b>not</b> include the 381-task PPO Kaggle run.
  </div>
  <div class="ds-actions">
    <a class="ds-btn ds-btn-active" href="{self}">Legacy</a>
    <a class="ds-btn" href="{ppo}">PPO Kaggle (381 tasks) →</a>
  </div>
</div>
"""

_PPO_BANNER = """
<div class="ds-banner ds-ppo">
  <div class="ds-tag">PPO KAGGLE · 381 TASKS</div>
  <div class="ds-text">
    These charts come from the <b>3-shard PPO + LoRA training</b> we ran on free Kaggle T4s. Source data:
    <code>kaggle ran notebooks/shard {{1,2,3}}/training_kaggle{{N}}.json</code> + the 381 scenarios in
    <code>rl-agent/scenarios/sim/{{easy,medium,hard}}/*.json</code>, pre-bundled into
    <code>rl-agent/showcase_data.json</code> by <code>scripts/build_showcase_data.py</code>.
    Every visible number is computed from those files.
  </div>
  <div class="ds-actions">
    <a class="ds-btn" href="{legacy}">← Legacy</a>
    <a class="ds-btn ds-btn-active" href="{self}">PPO Kaggle</a>
    <a class="ds-btn" href="/showcase">Showcase →</a>
  </div>
</div>
"""


def _ds_banner(ds: str, self_url: str, sibling_url: str) -> str:
    if ds == "ppo":
        return _PPO_BANNER.format(self=self_url, legacy=sibling_url)
    return _LEGACY_BANNER.format(self=self_url, ppo=sibling_url)


_CSS = """
<style>
  :root {
    --bg: #07091a;
    --bg-grad: radial-gradient(ellipse at top, #1b2544 0%, #07091a 60%);
    --panel: rgba(20, 27, 53, 0.72);
    --panel-solid: #141b35;
    --panel2: #1b2544;
    --border: rgba(122, 167, 255, 0.18);
    --border-strong: rgba(122, 167, 255, 0.4);
    --accent: #7aa7ff;
    --accent-grad: linear-gradient(135deg, #7aa7ff 0%, #a78bfa 100%);
    --accent2: #ff9f7a;
    --good: #4ade80;
    --bad: #f87171;
    --warn: #fbbf24;
    --text: #e6ecff;
    --muted: #8aa0c7;
    --shadow: 0 8px 24px rgba(0,0,0,0.35), 0 0 1px rgba(122,167,255,0.15);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; }
  body {
    font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    background: var(--bg-grad);
    background-attachment: fixed;
    color: var(--text);
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }
  .navbar {
    display: flex; flex-wrap: wrap; gap: 4px;
    padding: 10px 24px;
    background: rgba(7, 9, 26, 0.85);
    backdrop-filter: saturate(160%) blur(14px);
    -webkit-backdrop-filter: saturate(160%) blur(14px);
    position: sticky; top: 0; z-index: 50;
    border-bottom: 1px solid var(--border);
  }
  .navbar::before {
    content: "\26A1 IncidentCommander";
    font-weight: 700; font-size: 14px; letter-spacing: 0.04em;
    color: var(--text); padding: 8px 14px 8px 0; margin-right: 8px;
    border-right: 1px solid var(--border); margin-right: 14px;
  }
  .nav-item {
    color: var(--muted); padding: 8px 14px; text-decoration: none;
    border-radius: 8px; font-size: 13px; font-weight: 500;
    transition: all 0.18s ease;
  }
  .nav-item:hover {
    background: rgba(122, 167, 255, 0.12);
    color: var(--text); transform: translateY(-1px);
  }
  .nav-item.active {
    background: var(--accent-grad);
    color: #07091a; box-shadow: 0 4px 12px rgba(122,167,255,0.35);
  }
  .page { max-width: 1400px; margin: 0 auto; padding: 28px 24px; }
  h1 {
    margin: 0 0 6px; font-size: 28px; font-weight: 700;
    background: var(--accent-grad); -webkit-background-clip: text;
    -webkit-text-fill-color: transparent; background-clip: text;
  }
  h2 {
    margin-top: 36px; color: var(--text); font-size: 18px;
    font-weight: 600; letter-spacing: 0.01em;
    padding-bottom: 8px; border-bottom: 1px solid var(--border);
  }
  .subtitle { color: var(--muted); margin-bottom: 24px; font-size: 14px; }
  .kpi-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr));
    gap: 14px; margin-bottom: 24px;
  }
  .kpi {
    background: var(--panel); padding: 18px 20px; border-radius: 14px;
    border: 1px solid var(--border); box-shadow: var(--shadow);
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    transition: transform 0.18s ease, border-color 0.18s ease;
  }
  .kpi:hover { transform: translateY(-2px); border-color: var(--border-strong); }
  .kpi .label {
    color: var(--muted); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.1em; font-weight: 600;
  }
  .kpi .value {
    font-size: 30px; font-weight: 700; margin-top: 8px;
    background: var(--accent-grad); -webkit-background-clip: text;
    -webkit-text-fill-color: transparent; background-clip: text;
    line-height: 1.1;
  }
  .kpi .delta { font-size: 12px; margin-top: 4px; color: var(--muted); }
  .delta.up { color: var(--good); } .delta.down { color: var(--bad); }
  .chart-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(420px,1fr));
    gap: 16px; margin-bottom: 16px;
  }
  .chart {
    background: var(--panel); padding: 18px; border-radius: 14px;
    border: 1px solid var(--border); box-shadow: var(--shadow);
    backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
  }
  .chart h3 {
    margin: 0 0 12px; font-size: 13px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600;
  }
  table {
    width: 100%; border-collapse: separate; border-spacing: 0;
    margin-top: 12px; font-size: 13px;
    background: var(--panel); border-radius: 12px; overflow: hidden;
    border: 1px solid var(--border); box-shadow: var(--shadow);
  }
  th, td { text-align: left; padding: 10px 14px;
           border-bottom: 1px solid var(--border); }
  th {
    color: var(--muted); font-weight: 600; text-transform: uppercase;
    font-size: 10px; letter-spacing: 0.08em;
    background: rgba(7,9,26,0.4);
  }
  tbody tr { transition: background 0.12s ease; }
  tbody tr:hover { background: rgba(122,167,255,0.05); }
  tbody tr:last-child td { border-bottom: none; }
  .badge {
    display: inline-block; padding: 3px 10px; border-radius: 14px;
    font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .badge.ok   { background: rgba(74,222,128,0.18); color: var(--good);
                box-shadow: inset 0 0 0 1px rgba(74,222,128,0.32); }
  .badge.warn { background: rgba(251,191,36,0.18); color: var(--warn);
                box-shadow: inset 0 0 0 1px rgba(251,191,36,0.32); }
  .badge.err  { background: rgba(248,113,113,0.18); color: var(--bad);
                box-shadow: inset 0 0 0 1px rgba(248,113,113,0.32); }
  .badge.info { background: rgba(122,167,255,0.18); color: var(--accent);
                box-shadow: inset 0 0 0 1px rgba(122,167,255,0.32); }
  pre {
    background: rgba(7,9,26,0.7); padding: 14px; border-radius: 10px;
    overflow-x: auto; font-size: 12px;
    border: 1px solid var(--border);
    font-family: 'JetBrains Mono', 'Consolas', monospace;
  }
  code {
    background: rgba(122,167,255,0.12); color: var(--accent);
    padding: 1px 6px; border-radius: 4px; font-size: 0.92em;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
  }
  .empty { color: var(--muted); font-style: italic; padding: 14px; text-align: center; }
  .pulse {
    display: inline-block; width: 8px; height: 8px; border-radius: 50%;
    background: var(--good); box-shadow: 0 0 0 0 rgba(74,222,128,0.6);
    animation: pulse 1.8s infinite; margin-right: 6px;
    vertical-align: middle;
  }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(74,222,128,0.55); }
    70%  { box-shadow: 0 0 0 12px rgba(74,222,128,0); }
    100% { box-shadow: 0 0 0 0 rgba(74,222,128,0); }
  }
  .fade-in { animation: fadeIn 0.5s ease; }
  @keyframes fadeIn { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: rgba(7,9,26,0.4); }
  ::-webkit-scrollbar-thumb {
    background: rgba(122,167,255,0.25); border-radius: 6px;
  }
  ::-webkit-scrollbar-thumb:hover { background: rgba(122,167,255,0.45); }

  /* Dataset switcher banner */
  .ds-banner {
    display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
    padding: 14px 20px; margin: 0 0 22px;
    border-radius: 14px; border: 1px solid var(--border);
    background: rgba(20,27,53,0.55);
    backdrop-filter: blur(10px);
  }
  .ds-banner.ds-legacy { border-left: 3px solid #fbbf24; }
  .ds-banner.ds-ppo    { border-left: 3px solid #7aa7ff; }
  .ds-tag {
    font-size: 10.5px; letter-spacing: 0.18em; font-weight: 700;
    text-transform: uppercase; padding: 4px 10px;
    background: rgba(122,167,255,0.14); color: var(--accent);
    border-radius: 999px; flex-shrink: 0;
  }
  .ds-banner.ds-legacy .ds-tag { background: rgba(251,191,36,0.14); color: #fbbf24; }
  .ds-text { flex: 1; min-width: 280px; font-size: 13px; color: var(--muted); line-height: 1.55; }
  .ds-text code { font-size: 12px; }
  .ds-actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .ds-btn {
    padding: 8px 14px; border-radius: 999px; font-size: 12.5px; font-weight: 600;
    text-decoration: none; color: var(--muted);
    background: rgba(122,167,255,0.08); border: 1px solid var(--border);
    transition: all 0.15s ease; white-space: nowrap;
  }
  .ds-btn:hover { color: var(--text); border-color: var(--border-strong); }
  .ds-btn-active { background: var(--accent-grad); color: #07091a; border-color: transparent; }
</style>
"""


def _page(title: str, active: str, body: str, ds: str = "legacy") -> str:
    # Auto-inject the dataset switcher banner so every page shows it.
    if ds == "ppo":
        sibling = active.replace("/dashboard/ppo", "/dashboard", 1) or "/dashboard"
    else:
        # active is a /dashboard/X URL; sibling is /dashboard/ppo/X
        if active == "/dashboard":
            sibling = "/dashboard/ppo"
        else:
            sibling = active.replace("/dashboard/", "/dashboard/ppo/", 1)
    banner = _ds_banner(ds, self_url=active, sibling_url=sibling)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title} — IncidentCommander</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
{_CSS}
</head><body>
{_nav(active, ds)}
<div class="page fade-in">{banner}{body}</div>
<script>
  if (window.Chart) {{
    Chart.defaults.color = '#8aa0c7';
    Chart.defaults.borderColor = 'rgba(122,167,255,0.12)';
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.legend.labels.boxWidth = 8;
  }}
</script>
</body></html>"""


# ---------------------------------------------------------------------------
# Helpers — load metrics from disk
# ---------------------------------------------------------------------------


def _list_runs() -> list[str]:
    if not CHECKPOINT_ROOT.exists():
        return []
    return sorted([
        p.name for p in CHECKPOINT_ROOT.iterdir()
        if p.is_dir() and (p / "metrics.jsonl").exists()
    ])


def _load_metrics(run: str | None) -> tuple[str, list[dict], dict]:
    """Return (run_name, metrics_rows, summary_dict)."""
    runs = _list_runs()
    if not runs:
        return ("", [], {})
    active = run if run in runs else runs[-1]
    base = CHECKPOINT_ROOT / active
    rows: list[dict] = []
    try:
        for line in (base / "metrics.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    summary = {}
    sp = base / "summary.json"
    if sp.exists():
        try:
            summary = json.loads(sp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {}
    return active, rows, summary


def _load_snapshot(run: str | None, name: str) -> Any:
    """Load a JSON snapshot file from the checkpoint dir. Returns None if missing."""
    runs = _list_runs()
    if not runs:
        return None
    active = run if run in runs else runs[-1]
    p = CHECKPOINT_ROOT / active / name
    if not p.exists():
        return None
    try:
        if name.endswith(".jsonl"):
            out = []
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
            return out
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Page bodies
# ---------------------------------------------------------------------------


def _render_overview(app: FastAPI, run: str | None) -> str:
    name, rows, summary = _load_metrics(run)
    env = getattr(app.state, "env", None)
    curriculum = getattr(app.state, "curriculum", None)
    n_eps = summary.get("total_episodes", 0)
    m_r = summary.get("mean_reward", 0.0)
    m_g = summary.get("mean_grade", 0.0)
    mit = summary.get("mitigation_rate", 0.0) * 100
    rc  = summary.get("root_cause_rate", 0.0) * 100
    mode = summary.get("mode", "—")
    tier = curriculum.state.tier if curriculum else "warmup"
    task_id = getattr(env, "_task", None)
    task_id = task_id.task_id if task_id else "—"

    body = f"""
<h1>IncidentCommander — Overview</h1>
<div class="subtitle">Actor-critic PPO training telemetry · run: <b>{name or '(no runs yet)'}</b> · mode: {mode}</div>
<div class="kpi-grid">
  <div class="kpi"><div class="label">Episodes</div><div class="value">{n_eps}</div></div>
  <div class="kpi"><div class="label">Mean Reward</div><div class="value">{m_r:.3f}</div></div>
  <div class="kpi"><div class="label">Mean Grade</div><div class="value">{m_g:.3f}</div></div>
  <div class="kpi"><div class="label">Mitigation Rate</div><div class="value">{mit:.1f}%</div></div>
  <div class="kpi"><div class="label">Root Cause Rate</div><div class="value">{rc:.1f}%</div></div>
  <div class="kpi"><div class="label">Current Tier</div><div class="value">{tier}</div></div>
  <div class="kpi"><div class="label">Current Task</div><div class="value">{task_id}</div></div>
  <div class="kpi"><div class="label">Updates Logged</div><div class="value">{len(rows)}</div></div>
</div>

<div class="chart-grid">
  <div class="chart"><h3>Reward per update</h3><canvas id="c1" height="120"></canvas></div>
  <div class="chart"><h3>Grade per update</h3><canvas id="c2" height="120"></canvas></div>
  <div class="chart"><h3>Mitigation & Root-Cause rate</h3><canvas id="c3" height="120"></canvas></div>
  <div class="chart"><h3>Tier distribution</h3><canvas id="c4" height="120"></canvas></div>
</div>

<h2>Available runs</h2>
<div>{' '.join(f'<a class="nav-item" href="/dashboard?run={r}">{r}</a>' for r in _list_runs()) or '<span class="empty">No runs found yet.</span>'}</div>

<script>
const rows = {json.dumps(rows)};
const labels = rows.map(r => 'u' + r.update);
function chart(id, datasets) {{
  new Chart(document.getElementById(id), {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{ responsive: true, plugins: {{ legend: {{ labels: {{ color: '#e6ecff' }} }} }},
               scales: {{ x: {{ ticks: {{ color: '#8aa0c7' }} }},
                          y: {{ ticks: {{ color: '#8aa0c7' }} }} }} }}
  }});
}}
chart('c1', [{{label:'reward', data: rows.map(r=>r.mean_reward), borderColor:'#7aa7ff', fill:false}}]);
chart('c2', [{{label:'grade',  data: rows.map(r=>r.mean_grade),  borderColor:'#ff9f7a', fill:false}}]);
chart('c3', [
  {{label:'mit',     data: rows.map(r=>r.mitigation_rate), borderColor:'#4ade80', fill:false}},
  {{label:'root',    data: rows.map(r=>r.root_cause_rate), borderColor:'#f87171', fill:false}}
]);
const tierCounts = {{}}; rows.forEach(r => tierCounts[r.tier] = (tierCounts[r.tier]||0)+1);
new Chart(document.getElementById('c4'), {{
  type: 'doughnut',
  data: {{ labels: Object.keys(tierCounts), datasets: [{{
      data: Object.values(tierCounts),
      backgroundColor: ['#7aa7ff','#ff9f7a','#4ade80','#f87171','#fbbf24']
  }}]}},
  options: {{ plugins: {{ legend: {{ labels: {{ color: '#e6ecff' }} }} }} }}
}});
</script>
"""
    return _page("Overview", "/dashboard", body)


def _render_rewards(app: FastAPI) -> str:
    env = getattr(app.state, "env", None)
    breakdown: dict = {}
    source = "live env (awaiting first /reset)"
    if env is not None:
        try:
            breakdown = dict(getattr(env, "_last_reward_breakdown", {}) or {})
        except Exception:
            breakdown = {}
    history = _load_snapshot(None, "reward_breakdown_history.jsonl") or []
    if not breakdown and history:
        last = history[-1]
        breakdown = dict(last.get("reward_breakdown") or {})
        source = f"training snapshot \u00b7 last episode ({last.get('task_id','?')})"
    elif breakdown:
        source = "live env (last /step)"

    # Auto-discover ALL signal keys ever seen across the training history.
    keys_seen: dict[str, int] = {}
    pos_count: dict[str, int] = {}
    neg_count: dict[str, int] = {}
    sums: dict[str, float] = {}
    for row in history:
        for k, v in (row.get("reward_breakdown") or {}).items():
            keys_seen[k] = keys_seen.get(k, 0) + 1
            sums[k] = sums.get(k, 0.0) + float(v)
            if v > 0: pos_count[k] = pos_count.get(k, 0) + 1
            if v < 0: neg_count[k] = neg_count.get(k, 0) + 1
    means: dict[str, float] = {k: sums[k] / max(1, keys_seen[k]) for k in keys_seen}

    # Friendly descriptions; unknown keys auto-show with humanised name.
    DESCS = {
        "step_cost":                    "-0.01 per step (efficiency pressure)",
        "investigation_bonus":          "First-time read action on a new service",
        "root_cause_correct":           "+0.30 for correct postmortem root cause",
        "correct_mitigation":           "+0.20 for the right write action on the right service",
        "useful_log_query":             "+0.10 when log query returns task-relevant keywords",
        "postmortem_quality":           "+0..0.20 from postmortem grader",
        "acting_blind_penalty":         "-0.20 for write action with no prior investigation",
        "red_herring_penalty":          "-0.15 for targeting a known red-herring service",
        "wrong_service_penalty":        "-0.15 for writing to the wrong deployment",
        "time_penalty":                 "-0.05 \u00d7 max(0, step-5)",
        "blast_radius_increase":        "-0.10 when a write made things worse",
        "repeat_command_penalty":       "-0.15 per duplicate command (cap -0.45)",
        "phase_order":                  "\u00b1 Phase progression (triage \u2192 investigate \u2192 fix \u2192 verify)",
        "judge":                        "LLM judge slice [-0.10, +0.15]",
        "evidence_alignment":           "Postmortem cites evidence found via logs",
        "mitigation_efficiency":        "Mitigation in \u22643 writes",
        "mitigation_thrash_penalty":    "Thrashing (>6 writes)",
        "recovery_verified":            "Real cluster confirms pods Running after fix",
        "diverse_evidence":             "\u22653 distinct evidence sources",
        # New extended signals.
        "early_triage_bonus":           "First two steps were read actions",
        "dependency_first_bonus":       "Mapped dependencies before any write",
        "metric_correlation_bonus":     "Same service queried in both logs and metrics",
        "trace_used_bonus":             "Used distributed tracing at least once",
        "exec_diagnostic_bonus":        "Used kubectl describe/get/events (read-verb)",
        "cross_service_evidence":       "Investigated \u22652 distinct services",
        "parameter_specificity_bonus":  "query_logs with a filter_text",
        "quick_root_cause_bonus":       "Identified root cause within 4 steps",
        "verification_after_fix":       "Read action AFTER mitigation (verify)",
        "runbook_match_bonus":          "Postmortem lists correct affected service",
        "low_thrash_bonus":             "\u22642 write actions in entire episode",
        "fast_resolution_bonus":        "Mitigation in \u22646 total steps",
        "exploration_diversity":        "Bonus per unique action type used (cap 0.08)",
        "consistent_postmortem_bonus":  "Required postmortem fields present",
        "log_keyword_match_strength":   "Cumulative useful log queries (cap +0.10)",
        "followup_quality_bonus":       "Postmortem proposes \u22653 followups",
        "safe_action_bonus":            "Avoided destructive verbs (delete/drop/--force)",
    }
    # Order: known first, then any newly-discovered signals.
    ordered = [k for k in DESCS if k in keys_seen]
    ordered += sorted(k for k in keys_seen if k not in DESCS)

    rows_html = ""
    for k in ordered:
        last_v = breakdown.get(k, 0.0)
        mean_v = means.get(k, 0.0)
        n_pos = pos_count.get(k, 0)
        n_neg = neg_count.get(k, 0)
        n_total = keys_seen.get(k, 0)
        if mean_v > 0: badge = '<span class="badge ok">positive</span>'
        elif mean_v < 0: badge = '<span class="badge err">penalty</span>'
        else: badge = '<span class="badge info">neutral</span>'
        last_cell = f'{last_v:+.3f}' if k in breakdown else '\u2014'
        rows_html += (
            f'<tr><td><b>{k}</b> {badge}</td>'
            f'<td>{DESCS.get(k, k.replace("_", " ").title())}</td>'
            f'<td>{last_cell}</td>'
            f'<td>{mean_v:+.3f}</td>'
            f'<td>{n_total} <span class="empty" style="padding:0">'
            f'(\u2191{n_pos} \u2193{n_neg})</span></td></tr>'
        )

    n_signals = len(ordered)
    n_episodes = len(history)
    body = f"""
<h1>Reward signals</h1>
<div class="subtitle"><span class="pulse"></span> {n_signals} reward components observed across <b>{n_episodes}</b> training episodes.
  Source: <b>{source}</b>.</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">Signal count</div><div class="value">{n_signals}</div></div>
  <div class="kpi"><div class="label">Episodes</div><div class="value">{n_episodes}</div></div>
  <div class="kpi"><div class="label">Positive signals fired</div><div class="value">{sum(pos_count.values())}</div></div>
  <div class="kpi"><div class="label">Penalties fired</div><div class="value">{sum(neg_count.values())}</div></div>
</div>

<div class="chart-grid">
  <div class="chart"><h3>Last-episode breakdown</h3><div style="position:relative;height:340px"><canvas id="rb"></canvas></div></div>
  <div class="chart"><h3>Mean across all episodes</h3><div style="position:relative;height:340px"><canvas id="rm"></canvas></div></div>
</div>

<h2>Signal catalogue</h2>
<table><thead><tr><th>Signal</th><th>Meaning</th><th>Last episode</th><th>Mean (n={n_episodes})</th><th>Fire count</th></tr></thead>
<tbody>{rows_html or '<tr><td colspan="5" class="empty">No reward breakdown recorded yet.</td></tr>'}</tbody></table>

<script>
function barChart(id, data, label) {{
  const keys = Object.keys(data);
  const vals = keys.map(k => data[k]);
  const colors = vals.map(v => v >= 0 ? 'rgba(74,222,128,0.78)' : 'rgba(248,113,113,0.78)');
  const borders = vals.map(v => v >= 0 ? '#4ade80' : '#f87171');
  new Chart(document.getElementById(id), {{
    type: 'bar',
    data: {{ labels: keys, datasets: [{{ data: vals, backgroundColor: colors,
                                      borderColor: borders, borderWidth: 1,
                                      borderRadius: 4, label }}]}},
    options: {{
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }},
                  tooltip: {{ backgroundColor: 'rgba(20,27,53,0.96)',
                              borderColor: 'rgba(122,167,255,0.4)', borderWidth: 1 }}
      }},
      scales: {{ x: {{ grid: {{ color: 'rgba(122,167,255,0.08)' }} }},
                 y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }} }}
    }}
  }});
}}
barChart('rb', {json.dumps(breakdown)}, 'last episode');
barChart('rm', {json.dumps(means)}, 'mean');
</script>
"""
    return _page("Rewards", "/dashboard/rewards", body)


def _render_tasks(app: FastAPI, run: str | None) -> str:
    _, _, summary = _load_metrics(run)
    per_task = summary.get("per_task", {})
    task_meta = getattr(app.state, "task_metadata", None)
    if not task_meta:
        # Fall back to module-level TASK_METADATA via import
        try:
            from server import TASK_METADATA  # type: ignore
            task_meta = TASK_METADATA
        except Exception:
            task_meta = []

    rows_html = ""
    labels, rewards, grades, mit_rates = [], [], [], []
    for t in task_meta:
        tid = t["id"]
        stats = per_task.get(tid, {})
        n = stats.get("n", 0)
        r = stats.get("mean_reward", None)
        g = stats.get("mean_grade", None)
        m = stats.get("mitigation_rate", None)
        rc = stats.get("root_cause_rate", None)
        badge = (f'<span class="badge ok">{t["difficulty"]}</span>' if t["difficulty"] == "easy"
                 else f'<span class="badge warn">{t["difficulty"]}</span>' if t["difficulty"] == "medium"
                 else f'<span class="badge err">{t["difficulty"]}</span>')
        rows_html += (
            f"<tr><td><b>{tid}</b></td><td>{t['name']}</td><td>{badge}</td>"
            f"<td>{t['target_score']:.2f}</td><td>{n}</td>"
            f"<td>{'' if r is None else f'{r:+.3f}'}</td>"
            f"<td>{'' if g is None else f'{g:.3f}'}</td>"
            f"<td>{'' if m is None else f'{m*100:.0f}%'}</td>"
            f"<td>{'' if rc is None else f'{rc*100:.0f}%'}</td></tr>"
        )
        labels.append(tid)
        rewards.append(r if r is not None else 0)
        grades.append(g if g is not None else 0)
        mit_rates.append((m or 0) * 100)

    body = f"""
<h1>Per-task performance</h1>
<div class="subtitle">11 hand-authored tasks across 5 difficulty tiers.</div>

<div class="chart-grid">
  <div class="chart"><h3>Mean reward by task</h3><canvas id="tr" height="150"></canvas></div>
  <div class="chart"><h3>Mean grade by task</h3><canvas id="tg" height="150"></canvas></div>
  <div class="chart"><h3>Mitigation rate by task (%)</h3><canvas id="tm" height="150"></canvas></div>
</div>

<h2>Task catalog</h2>
<table>
  <thead><tr><th>ID</th><th>Scenario</th><th>Difficulty</th><th>Target</th>
             <th>N</th><th>Reward</th><th>Grade</th><th>Mit%</th><th>RC%</th></tr></thead>
  <tbody>{rows_html or '<tr><td colspan="9" class="empty">No tasks.</td></tr>'}</tbody>
</table>

<script>
const labels = {json.dumps(labels)};
function bar(id, data, color) {{
  new Chart(document.getElementById(id), {{
    type: 'bar',
    data: {{ labels, datasets: [{{ data, backgroundColor: color }}] }},
    options: {{ plugins: {{ legend: {{ display:false }} }},
               scales: {{ x: {{ ticks: {{ color:'#8aa0c7' }} }},
                          y: {{ ticks: {{ color:'#8aa0c7' }} }} }} }}
  }});
}}
bar('tr', {json.dumps(rewards)},  '#7aa7ff');
bar('tg', {json.dumps(grades)},   '#ff9f7a');
bar('tm', {json.dumps(mit_rates)},'#4ade80');
</script>
"""
    return _page("Tasks", "/dashboard/tasks", body)


def _render_training(run: str | None) -> str:
    name, rows, summary = _load_metrics(run)
    mode = summary.get("mode", "—")
    runs = _list_runs()
    runs_html = " ".join(
        f'<a class="nav-item{" active" if r == name else ""}" href="/dashboard/training?run={r}">{r}</a>'
        for r in runs
    ) or '<span class="empty">No runs yet — call <code>python -m training.train_ppo --tiny</code>.</span>'

    body = f"""
<h1>Training progress</h1>
<div class="subtitle">Run: <b>{name or '—'}</b> · mode: <span class="badge info">{mode}</span> · {len(rows)} updates recorded.</div>
<div>{runs_html}</div>

<div class="chart-grid">
  <div class="chart"><h3>Reward & grade</h3><canvas id="rg" height="140"></canvas></div>
  <div class="chart"><h3>Policy / value loss</h3><canvas id="pl" height="140"></canvas></div>
  <div class="chart"><h3>Entropy</h3><canvas id="en" height="140"></canvas></div>
  <div class="chart"><h3>Mitigation / root-cause rate</h3><canvas id="mr" height="140"></canvas></div>
</div>

<h2>Raw metrics (last 25 updates)</h2>
<pre>{json.dumps(rows[-25:], indent=2)}</pre>

<script>
const rows = {json.dumps(rows)};
const labels = rows.map(r=>'u'+r.update);
function line(id, ds) {{
  new Chart(document.getElementById(id), {{
    type:'line', data:{{labels, datasets:ds}},
    options:{{plugins:{{legend:{{labels:{{color:'#e6ecff'}}}}}},
             scales:{{x:{{ticks:{{color:'#8aa0c7'}}}},y:{{ticks:{{color:'#8aa0c7'}}}}}}}}
  }});
}}
line('rg', [
  {{label:'reward',data:rows.map(r=>r.mean_reward),borderColor:'#7aa7ff',fill:false}},
  {{label:'grade', data:rows.map(r=>r.mean_grade), borderColor:'#ff9f7a',fill:false}}
]);
line('pl', [
  {{label:'policy', data:rows.map(r=>r.policy_loss||null),borderColor:'#f87171',fill:false}},
  {{label:'value',  data:rows.map(r=>r.value_loss||null), borderColor:'#fbbf24',fill:false}}
]);
line('en', [{{label:'entropy', data:rows.map(r=>r.entropy||null),borderColor:'#a78bfa',fill:false}}]);
line('mr', [
  {{label:'mit',  data:rows.map(r=>r.mitigation_rate), borderColor:'#4ade80',fill:false}},
  {{label:'root', data:rows.map(r=>r.root_cause_rate), borderColor:'#f87171',fill:false}}
]);
</script>
"""
    return _page("Training", "/dashboard/training", body)


def _render_cluster(app: FastAPI) -> str:
    env = getattr(app.state, "env", None)
    real_enabled = False
    ns_info: list[dict] = []
    backend_label = "mock"
    try:
        k8s = getattr(env, "_k8s_backend", None)
        if k8s and getattr(k8s, "enabled", False):
            real_enabled = True
            status = k8s.cluster_status()
            ns_info = status.get("namespaces", []) if isinstance(status, dict) else []
            backend_label = "Real EKS/kind"
    except Exception:
        pass

    # Fall back to the snapshot written by the trainer.
    if not ns_info:
        snap = _load_snapshot(None, "cluster_snapshot.json") or {}
        ns_info = snap.get("namespaces", []) or []
        if ns_info:
            backend_label = snap.get("backend", "snapshot")

    # Probe live observability endpoints if env vars are set.
    obs_probes = _probe_observability()

    rows_html = ""
    _ok_badge  = '<span class="badge ok">Running</span>'
    _bad_badge = '<span class="badge err">Degraded</span>'
    for ns in ns_info:
        status_badge = _ok_badge if ns.get('ready', 0) >= ns.get('replicas', 0) else _bad_badge
        rows_html += (
            f"<tr><td>{ns.get('namespace','?')}</td>"
            f"<td>{ns.get('deployment','?')}</td>"
            f"<td>{ns.get('replicas',0)}</td>"
            f"<td>{ns.get('ready',0)}</td>"
            f"<td>{status_badge}</td></tr>"
        )
    badge = ('<span class="badge ok">Real EKS/kind</span>' if real_enabled
             else f'<span class="badge info">{backend_label}</span>')

    _obs_fragments = []
    for name, p in obs_probes.items():
        url_cell = p['url'] if p['url'] else '<span class="empty">not set</span>'
        if p['ok']:
            status_cell = '<span class="badge ok">reachable</span>'
        elif p['url']:
            status_cell = '<span class="badge warn">unreachable</span>'
        else:
            status_cell = '<span class="badge warn">unset</span>'
        detail_cell = p.get('detail', '') or ''
        _obs_fragments.append(
            f"<tr><td><b>{name}</b></td><td>{url_cell}</td>"
            f"<td>{status_cell}</td><td>{detail_cell}</td></tr>"
        )
    obs_rows = "".join(_obs_fragments)

    body = f"""
<h1>Cluster health</h1>
<div class="subtitle">Backend status {badge}</div>

<h2>Namespaces & deployments</h2>
<table>
  <thead><tr><th>Namespace</th><th>Deployment</th><th>Replicas</th><th>Ready</th><th>Status</th></tr></thead>
  <tbody>{rows_html or '<tr><td colspan="5" class="empty">No cluster attached and no snapshot on disk.</td></tr>'}</tbody>
</table>

<h2>Observability stack (live probes)</h2>
<div class="subtitle">Each integration probes the configured URL (env vars <code>PROMETHEUS_URL</code>,
  <code>LOKI_URL</code>, <code>GRAFANA_URL</code>, <code>ALERTMANAGER_URL</code>).</div>
<table>
  <thead><tr><th>Service</th><th>URL</th><th>Status</th><th>Detail</th></tr></thead>
  <tbody>{obs_rows}</tbody>
</table>

<h2>Fault injectors available</h2>
<table>
  <thead><tr><th>Kind</th><th>Effect</th></tr></thead>
  <tbody>
    <tr><td>image_tag_bump</td><td>Roll deployment to a nonexistent tag → ImagePullBackOff</td></tr>
    <tr><td>env_mutation</td><td>Inject a bad env var to break startup</td></tr>
    <tr><td>resource_limit</td><td>Shrink CPU/memory limit to force OOMKill</td></tr>
    <tr><td>liveness_probe</td><td>Flip liveness probe to always-fail → CrashLoopBackOff</td></tr>
    <tr><td>network_latency</td><td>tc netem injection between pod & Redis</td></tr>
    <tr><td>configmap_corruption</td><td>Mutate ConfigMap key → race conditions</td></tr>
    <tr><td>secret_rotation</td><td>Delete JWT secret → auth regressions</td></tr>
    <tr><td>namespace_quota</td><td>Apply ResourceQuota that blocks scheduling</td></tr>
    <tr><td>dns_chaos</td><td>CoreDNS rewrite → NXDOMAIN</td></tr>
  </tbody>
</table>
"""
    return _page("Cluster", "/dashboard/cluster", body)


def _probe_observability() -> dict[str, dict]:
    """Quickly probe Prometheus / Loki / Grafana / Alertmanager if URLs set."""
    import os
    import httpx
    targets = {
        "Prometheus":   (os.getenv("PROMETHEUS_URL"),   "/-/ready"),
        "Loki":         (os.getenv("LOKI_URL"),         "/ready"),
        "Grafana":      (os.getenv("GRAFANA_URL"),      "/api/health"),
        "Alertmanager": (os.getenv("ALERTMANAGER_URL"), "/-/ready"),
    }
    out: dict[str, dict] = {}
    for name, (base, path) in targets.items():
        if not base:
            out[name] = {"url": None, "ok": False, "detail": ""}
            continue
        try:
            r = httpx.get(base.rstrip("/") + path, timeout=2.0)
            out[name] = {"url": base, "ok": r.status_code < 400,
                         "detail": f"HTTP {r.status_code}"}
        except Exception as e:
            out[name] = {"url": base, "ok": False, "detail": str(e)[:60]}
    return out


def _render_aws() -> str:
    # 1) Live status from this process (HF Space typically has no AWS creds).
    try:
        from environment.aws_integrations import aws_status
        status = aws_status()
    except Exception as e:
        status = {"error": str(e), "region": None, "services": {}}

    # 2) Evidence from the most recent training run (committed to the repo).
    evidence = _load_snapshot(None, "aws_evidence.json") or {}

    svcs = status.get("services", {})
    region = status.get("region") or evidence.get("region") or "(unset)"
    account = status.get("account_id") or evidence.get("account_id") or "(no live creds)"

    rows_html = ""
    n_on = 0
    for name, info in svcs.items():
        on = bool(info.get("enabled"))
        n_on += int(on)
        badge = ('<span class="badge ok">connected</span>' if on
                 else '<span class="badge warn">not configured here</span>')
        detail_bits = []
        for k, v in info.items():
            if k == "enabled" or v is None:
                continue
            detail_bits.append(f"<code>{k}</code>: {v}")
        sep = " \u00b7 "
        em_dash = "\u2014"
        detail_str = sep.join(detail_bits) or em_dash
        rows_html += (
            f"<tr><td><b>{name}</b></td>"
            f"<td>{badge}</td>"
            f"<td>{detail_str}</td></tr>"
        )

    # ---- Evidence: real S3 objects, CW datapoints, Dynamo writes from last run.
    ev_summary = evidence.get("summary", {}) if evidence else {}
    s3_objs   = (evidence.get("s3", {}) or {}).get("objects", [])[-12:]
    cw_dps    = (evidence.get("cloudwatch_metrics", {}) or {}).get("datapoints", [])
    cw_logs   = (evidence.get("cloudwatch_logs", {}) or {}).get("events", [])
    ddb_writes= (evidence.get("dynamodb", {}) or {}).get("writes", [])
    sns_msgs  = (evidence.get("sns", {}) or {}).get("messages", [])
    errors    = evidence.get("errors", [])

    bucket = (evidence.get("s3", {}) or {}).get("bucket", "(not configured)")
    last_prefix = (evidence.get("s3", {}) or {}).get("last_prefix", "")

    s3_rows = "".join(
        f'<tr><td><code>s3://{bucket}/{o.get("key","")}</code></td>'
        f'<td>{o.get("bytes",0):,} bytes</td></tr>'
        for o in s3_objs
    ) or '<tr><td colspan="2" class="empty">No S3 uploads yet.</td></tr>'

    cw_metric_table = ""
    if cw_dps:
        # Aggregate by metric name.
        agg: dict[str, list] = {}
        for d in cw_dps:
            agg.setdefault(d.get("metric", "?"), []).append(float(d.get("value", 0.0)))
        cw_metric_table = "".join(
            f'<tr><td><b>{name}</b></td><td>{len(vs)}</td>'
            f'<td>{sum(vs)/len(vs):.3f}</td><td>{min(vs):.3f}</td>'
            f'<td>{max(vs):.3f}</td></tr>'
            for name, vs in sorted(agg.items())
        )
    cw_metric_table = cw_metric_table or '<tr><td colspan="5" class="empty">No CloudWatch metrics published yet.</td></tr>'

    ddb_rows = "".join(
        f'<tr><td>{w.get("task_id","?")}</td><td>{w.get("mastery",0):.3f}</td>'
        f'<td>{w.get("tier","?")}</td></tr>'
        for w in ddb_writes
    ) or '<tr><td colspan="3" class="empty">DynamoDB table not configured (set DYNAMODB_CURRICULUM_TABLE).</td></tr>'

    err_rows = "".join(
        f'<tr><td><code>{e.get("op","?")}</code></td><td>{e.get("error","?")[:200]}</td></tr>'
        for e in errors[-10:]
    ) or '<tr><td colspan="2" class="empty">No errors recorded.</td></tr>'

    services_defined = [
        ("VPC + subnets + NAT", "Dedicated 10.20.0.0/16 network across 2 AZs."),
        ("EKS",                 "Managed Kubernetes where AcmeCorp microservices + Chaos Mesh run."),
        ("ECR",                 "Private registry for the env server + trainer images."),
        ("S3",                  "Versioned bucket for training snapshots, metrics & critic shaping logs."),
        ("DynamoDB",            "PITR-enabled table holding per-run / per-task mastery."),
        ("CloudWatch Logs",     "Two log groups: /aws/eks/.../application + /aws/incident-commander/agent."),
        ("CloudWatch Metrics",  "Custom IncidentCommander namespace + ErrorRate > 5% alarm."),
        ("SNS",                 "Alert topic the agent publishes to when a mitigation is applied."),
        ("Secrets Manager",     "Stores OPENAI_API_KEY so no secrets are baked into the image."),
        ("IAM (IRSA)",          "Least-privilege pod role \u2014 S3/Dynamo/Logs/CW/SNS/Secrets/Bedrock."),
        ("Lambda",              "Subscribed to the SNS topic; POSTs /reset to trigger new episodes."),
        ("Bedrock",             "Optional second critic backend (Claude / Titan via InvokeModel)."),
    ]
    arch_rows = "".join(
        f"<tr><td><b>{n}</b></td><td>{d}</td></tr>" for n, d in services_defined
    )

    has_evidence = bool(evidence)
    last_run_ts = evidence.get("finished_at") or evidence.get("started_at") or 0
    import datetime as _dt
    last_run_str = (_dt.datetime.utcfromtimestamp(last_run_ts).strftime("%Y-%m-%d %H:%M UTC")
                    if last_run_ts else "n/a")

    body = f"""
<h1>AWS wiring & training evidence</h1>
<div class="subtitle">
  Account <b>{account}</b> \u00b7 Region <b>{region}</b> \u00b7
  Live services reachable here: <span class="badge info">{n_on}/{len(svcs) or 12}</span> \u00b7
  Last training run: <b>{last_run_str}</b>
</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">S3 objects uploaded</div><div class="value">{ev_summary.get('s3_objects', 0)}</div><div class="delta">bucket: {bucket}</div></div>
  <div class="kpi"><div class="label">CloudWatch datapoints</div><div class="value">{ev_summary.get('cloudwatch_datapoints', 0)}</div><div class="delta">namespace: IncidentCommander</div></div>
  <div class="kpi"><div class="label">CloudWatch log events</div><div class="value">{ev_summary.get('cloudwatch_log_events', 0)}</div></div>
  <div class="kpi"><div class="label">DynamoDB writes</div><div class="value">{ev_summary.get('dynamodb_writes', 0)}</div></div>
  <div class="kpi"><div class="label">SNS messages</div><div class="value">{ev_summary.get('sns_messages', 0)}</div></div>
  <div class="kpi"><div class="label">Errors</div><div class="value">{ev_summary.get('errors', 0)}</div></div>
</div>

<h2>S3 uploads (last run \u2014 prefix <code>{last_prefix or 'n/a'}</code>)</h2>
<table>
  <thead><tr><th>Object key</th><th>Size</th></tr></thead>
  <tbody>{s3_rows}</tbody>
</table>

<h2>CloudWatch custom metrics published</h2>
<table>
  <thead><tr><th>Metric</th><th>N</th><th>Mean</th><th>Min</th><th>Max</th></tr></thead>
  <tbody>{cw_metric_table}</tbody>
</table>

<h2>DynamoDB curriculum writes</h2>
<table>
  <thead><tr><th>Task</th><th>Mastery</th><th>Tier</th></tr></thead>
  <tbody>{ddb_rows}</tbody>
</table>

<h2>Live AWS service reachability (this process)</h2>
<div class="subtitle">Each integration in <code>environment/aws_integrations.py</code>
is gated on env vars + boto3 credentials. The HF Space typically has no creds,
so the trainer-side evidence above is the source of truth.</div>
<table>
  <thead><tr><th>Service</th><th>State</th><th>Detail</th></tr></thead>
  <tbody>{rows_html or '<tr><td colspan="3" class="empty">No AWS services configured here.</td></tr>'}</tbody>
</table>

<h2>Architecture (provisioned by <code>infra/aws/main.tf</code>)</h2>
<table>
  <thead><tr><th>Service</th><th>Role in IncidentCommander</th></tr></thead>
  <tbody>{arch_rows}</tbody>
</table>

<h2>Recorder errors (last run)</h2>
<table>
  <thead><tr><th>Operation</th><th>Error</th></tr></thead>
  <tbody>{err_rows}</tbody>
</table>

<h2>How the bucket gets data</h2>
<pre>python -m training.train_hybrid --critic groq --updates 12 \\
    --rollouts-per-update 3 --episode-limit 8 --all-tasks \\
    --out-dir checkpoints/ppo-v4-hybrid-ollama-groq \\
    --env-file ../.env.aws.local

# Trainer uploads the run dir to s3://$S3_CHECKPOINT_BUCKET/runs/&lt;ts&gt;-&lt;name&gt;/
# Publishes per-update CloudWatch metrics under namespace IncidentCommander
# Writes per-task mastery to DynamoDB ($DYNAMODB_CURRICULUM_TABLE if set)
# Saves aws_evidence.json so this dashboard can render real ARNs/keys.</pre>
"""
    return _page("AWS", "/dashboard/aws", body)


def _render_adversarial(app: FastAPI) -> str:
    designer = getattr(app.state, "adversarial", None)
    history: list[dict] = []
    enabled = False
    source = "live designer (no scenarios designed yet)"
    try:
        history = list(getattr(designer, "history", []) or [])[-20:]
        enabled = bool(getattr(designer, "_llm_enabled", False))
    except Exception:
        pass
    if not history:
        snap = _load_snapshot(None, "adversarial_history.jsonl") or []
        if snap:
            history = snap[-20:]
            source = f"training snapshot ({len(snap)} scenarios)"
    else:
        source = "live designer"

    rows_html = "".join(
        f"<tr><td>{h.get('task_id','?')}</td>"
        f"<td>{', '.join(h.get('faults', []))}</td>"
        f"<td>{h.get('difficulty','?')}</td>"
        f"<td><code>{json.dumps(h.get('red_herrings', []))[:80]}</code></td></tr>"
        for h in history
    ) or '<tr><td colspan="4" class="empty">No adversarial scenarios designed yet. POST /adversarial/design to generate one.</td></tr>'

    body = f"""
<h1>Adversarial scenario designer</h1>
<div class="subtitle">Designer is <b>{'LLM-backed' if enabled else 'procedural fallback'}</b>.
  Source: <b>{source}</b>. Showing last {len(history)} scenarios.</div>
<h2>Generated scenarios</h2>
<table>
  <thead><tr><th>Base task</th><th>Faults</th><th>Difficulty</th><th>Red herrings</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>

<h2>How it works</h2>
<pre>POST /adversarial/design
{{
  "base_task_id": "task2",
  "difficulty": "hard",
  "mix_faults": true,
  "add_red_herrings": 2
}}</pre>
"""
    return _page("Adversarial", "/dashboard/adversarial", body)


def _render_curriculum(app: FastAPI) -> str:
    c = getattr(app.state, "curriculum", None)
    tier = getattr(getattr(c, "state", None), "tier", "warmup")
    mastery: dict[str, float] = {}
    recent: list[dict] = []
    source = "live curriculum (no episodes yet)"
    try:
        mastery = dict(getattr(c.state, "mastery", {}) or {})
        recent = list(getattr(c.state, "recent_episodes", []) or [])[-20:]
    except Exception:
        pass
    if not mastery and not recent:
        snap = _load_snapshot(None, "curriculum_snapshot.json") or {}
        if snap:
            mastery = snap.get("mastery", {}) or {}
            recent  = (snap.get("recent_episodes") or [])[-20:]
            tier    = snap.get("tier", tier)
            source  = f"training snapshot ({snap.get('total_episodes', 0)} episodes)"
    elif mastery or recent:
        source = "live curriculum"

    mastery_rows = "".join(
        f"<tr><td>{tid}</td><td>{v:.2f}</td><td>"
        f"<div style='background:#27345e;width:200px;height:10px;border-radius:5px;overflow:hidden;'>"
        f"<div style='width:{min(100, v*100):.0f}%;height:100%;background:#4ade80;'></div></div></td></tr>"
        for tid, v in sorted(mastery.items())
    ) or '<tr><td colspan="3" class="empty">No mastery data yet.</td></tr>'

    recent_rows = "".join(
        f"<tr><td>{e.get('task_id','?')}</td>"
        f"<td>{e.get('score',0):.3f}</td>"
        f"<td>{e.get('target_score',0):.2f}</td>"
        f"<td>{'pass' if e.get('score',0) >= e.get('target_score',0) else 'fail'}</td></tr>"
        for e in recent
    ) or '<tr><td colspan="4" class="empty">No episodes recorded yet.</td></tr>'

    body = f"""
<h1>Curriculum controller</h1>
<div class="subtitle">Current tier: <span class="badge info">{tier}</span> · Source: <b>{source}</b></div>

<h2>Tier composition</h2>
<table>
  <thead><tr><th>Tier</th><th>Tasks</th></tr></thead>
  <tbody>
    <tr><td>warmup</td>       <td>task1, task4, task9</td></tr>
    <tr><td>beginner</td>     <td>task1, task2, task4, task5, task9</td></tr>
    <tr><td>intermediate</td> <td>task1–task10</td></tr>
    <tr><td>advanced</td>     <td>task2, task3, task5, task6, task7, task8, task10, task11</td></tr>
    <tr><td>expert</td>       <td>task3, task6, task7, task8, task10, task11</td></tr>
  </tbody>
</table>

<h2>Per-task mastery</h2>
<table><thead><tr><th>Task</th><th>Mastery</th><th></th></tr></thead>
<tbody>{mastery_rows}</tbody></table>

<h2>Recent episodes</h2>
<table><thead><tr><th>Task</th><th>Score</th><th>Target</th><th>Result</th></tr></thead>
<tbody>{recent_rows}</tbody></table>
"""
    return _page("Curriculum", "/dashboard/curriculum", body)


def _render_judge(app: FastAPI) -> str:
    env = getattr(app.state, "env", None)
    persona = getattr(env, "_persona", "senior") if env else "senior"
    enabled = getattr(env, "_use_llm_judge", False) if env else False
    body = f"""
<h1>Judge & persona</h1>
<div class="subtitle">Persona: <span class="badge info">{persona}</span> · LLM judge: <span class="badge {'ok' if enabled else 'warn'}">{'enabled' if enabled else 'disabled'}</span></div>

<h2>Personas</h2>
<table>
  <thead><tr><th>Persona</th><th>Bias</th><th>Description</th></tr></thead>
  <tbody>
    <tr><td>junior</td>
        <td>explores more, investigates thoroughly</td>
        <td>Rewards breadth-first investigation. Tolerates red herrings.</td></tr>
    <tr><td>senior</td>
        <td>balanced, pragmatic</td>
        <td>Default. Rewards hypothesis-driven investigation + timely fix.</td></tr>
    <tr><td>principal</td>
        <td>fast, decisive</td>
        <td>Penalises excessive investigation. Rewards prevention plan.</td></tr>
  </tbody>
</table>

<h2>Holistic rubric</h2>
<pre>{{
  "triage":          "Did the agent identify incident class on turn 1?",
  "investigation":   "Did evidence-gathering precede writes?",
  "mitigation":      "Was the correct remediation applied?",
  "root_cause":      "Is the postmortem root-cause correct?",
  "blast_radius":    "Did the postmortem quantify impact?",
  "prevention":      "Are prevention steps concrete and testable?"
}}</pre>
"""
    return _page("Judge", "/dashboard/judge", body)


def _render_api() -> str:
    endpoints = [
        ("POST", "/reset",              "Reset env; supports use_curriculum, adversarial, persona, real_mode"),
        ("POST", "/step",               "Take one action; returns observation/reward/done/info"),
        ("GET",  "/state",              "Current env state snapshot"),
        ("POST", "/grader",             "Grade the finished episode; records outcome for curriculum"),
        ("GET",  "/tasks",              "List 11 tasks + action schema"),
        ("GET",  "/baseline",           "Run the built-in heuristic agent (deterministic)"),
        ("GET",  "/curriculum",         "Current tier, mastery, rolling success"),
        ("POST", "/curriculum/reset",   "Reset curriculum progress"),
        ("POST", "/adversarial/design", "Procedural or LLM-backed scenario designer"),
        ("GET",  "/judge/config",       "Persona + judge settings"),
        ("POST", "/k8s/inject",         "Inject a fault into the live cluster"),
        ("POST", "/k8s/reset",          "Restore clean cluster state"),
        ("POST", "/k8s/exec",           "Run a kubectl verb (whitelisted)"),
        ("GET",  "/k8s/health",         "Cluster health snapshot"),
        ("GET",  "/dashboard",          "Overview page (this dashboard)"),
        ("GET",  "/dashboard/rewards",  "Reward-signal analytics"),
        ("GET",  "/dashboard/tasks",    "Per-task performance"),
        ("GET",  "/dashboard/training", "Training curves"),
        ("GET",  "/dashboard/cluster",  "Cluster health"),
        ("GET",  "/dashboard/adversarial","Adversarial designer history"),
        ("GET",  "/dashboard/curriculum", "Curriculum state"),
        ("GET",  "/dashboard/judge",    "Judge/persona"),
    ]
    rows_html = "".join(
        f'<tr><td><span class="badge {"info" if m == "GET" else "ok"}">{m}</span></td>'
        f'<td><code>{p}</code></td><td>{d}</td></tr>'
        for m, p, d in endpoints
    )
    body = f"""
<h1>API reference</h1>
<div class="subtitle">All endpoints exposed by the env server.</div>
<table>
  <thead><tr><th>Method</th><th>Path</th><th>Description</th></tr></thead>
  <tbody>{rows_html}</tbody>
</table>
<p style="margin-top:16px">OpenAPI docs: <a class="nav-item" href="/docs">/docs</a></p>
"""
    return _page("API", "/dashboard/api", body)


# ---------------------------------------------------------------------------
# PPO Kaggle dataset (381 tasks, 3 shards) — separate render set
# ---------------------------------------------------------------------------

_SHOWCASE_PATH = _HERE / "showcase_data.json"
_SHOWCASE_CACHE: dict[str, Any] | None = None


def _load_showcase() -> dict:
    """Lazy-load the precomputed PPO bundle. Cached after first read."""
    global _SHOWCASE_CACHE
    if _SHOWCASE_CACHE is not None:
        return _SHOWCASE_CACHE
    if not _SHOWCASE_PATH.exists():
        _SHOWCASE_CACHE = {
            "summary": {}, "scenarios": [], "shards": [],
            "cross_shard_index": {}, "category_breakdown": {},
            "difficulty_breakdown": {},
        }
        return _SHOWCASE_CACHE
    _SHOWCASE_CACHE = json.loads(_SHOWCASE_PATH.read_text(encoding="utf-8"))
    return _SHOWCASE_CACHE


def _ppo_missing_body(title: str) -> str:
    return f"""
<h1>{title}</h1>
<div class="subtitle">No PPO data found.</div>
<div class="empty">
  <code>rl-agent/showcase_data.json</code> is missing.<br>
  Run <code>python scripts/build_showcase_data.py</code> at the repo root, then redeploy.
</div>
"""


def _render_ppo_overview() -> str:
    d = _load_showcase()
    if not d.get("shards"):
        return _page("PPO Overview", "/dashboard/ppo", _ppo_missing_body("PPO Overview"), ds="ppo")
    s = d["summary"]
    shards = d["shards"]
    # Aggregate first/last reward across all per-shard tasks for delta KPI.
    all_first, all_last = [], []
    for sh in shards:
        for tid, summ in sh["task_summary"].items():
            all_first.append(summ["first"]); all_last.append(summ["last"])
    delta = (sum(all_last) / len(all_last)) - (sum(all_first) / len(all_first)) if all_first else 0.0
    final_means = [sh["trajectory"][-1]["r"] for sh in shards if sh["trajectory"]]
    avg_final = sum(final_means) / len(final_means) if final_means else 0.0
    wall_h = s["wall_seconds_total"] / 3600

    shard_cards = "".join(
        f'<div class="kpi"><div class="label">Shard {sh["shard"]}</div>'
        f'<div class="value">{sh["trajectory"][-1]["r"]:+.3f}</div>'
        f'<div class="delta">final mean reward · {sh["n_tasks"]} tasks · {sh["wall_seconds"]/60:.0f} min</div></div>'
        for sh in shards
    )

    body = f"""
<h1>PPO + LoRA · 3-Shard Overview</h1>
<div class="subtitle"><span class="pulse"></span> Phi-3.5-mini actor + DeepSeek-R1 critic, 4-bit, sharded across 3 free Kaggle T4s.</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">Scenarios</div><div class="value">{s["n_tasks_total"]}</div><div class="delta">all simulated incidents</div></div>
  <div class="kpi"><div class="label">Tasks trained</div><div class="value">{s["n_tasks_trained"]}</div><div class="delta">100% coverage</div></div>
  <div class="kpi"><div class="label">PPO updates</div><div class="value">{s["n_updates_per_shard"] * s["n_shards"]}</div><div class="delta">{s["n_updates_per_shard"]} × {s["n_shards"]} shards</div></div>
  <div class="kpi"><div class="label">Wall time</div><div class="value">{wall_h:.1f}h</div><div class="delta">aggregate, all shards</div></div>
  <div class="kpi"><div class="label">Final mean reward</div><div class="value">{avg_final:+.3f}</div><div class="delta {'up' if delta >= 0 else 'down'}">Δ vs. first {delta:+.3f}</div></div>
</div>

<h2>Per-shard final outcome</h2>
<div class="kpi-grid">{shard_cards}</div>

<h2>Mean-reward trajectory per shard</h2>
<div class="chart"><div style="position:relative;height:380px"><canvas id="rew"></canvas></div></div>

<h2>Hyper-parameters</h2>
<table>
  <thead><tr><th>Param</th><th>Value</th><th>Param</th><th>Value</th></tr></thead>
  <tbody>
    <tr><td>actor</td><td><code>{s["actor"]}</code></td><td>critic</td><td><code>{s["critic"]}</code></td></tr>
    <tr><td>lora_r</td><td>{s["lora_r"]}</td><td>lora_alpha</td><td>{s["lora_alpha"]}</td></tr>
    <tr><td>lr</td><td>{s["lr"]}</td><td>gamma</td><td>{s["gamma"]}</td></tr>
    <tr><td>gae_lambda</td><td>{s["gae_lambda"]}</td><td>clip_eps</td><td>{s["clip_eps"]}</td></tr>
    <tr><td>kl_coef</td><td>{s["kl_coef"]}</td><td>rollouts/update</td><td>{s["rollouts_per_update"]}</td></tr>
    <tr><td>max_steps/episode</td><td>{s["max_steps_per_ep"]}</td><td>updates/shard</td><td>{s["n_updates_per_shard"]}</td></tr>
  </tbody>
</table>

<script>
const SH = {json.dumps([{"n":sh["shard"],"x":[t["u"] for t in sh["trajectory"]],"y":[t["r"] for t in sh["trajectory"]]} for sh in shards])};
const C = ['#7aa7ff','#a78bfa','#ff9f7a'];
new Chart(document.getElementById('rew'), {{
  type:'line',
  data:{{ datasets: SH.map((s,i) => ({{
      label:'Shard '+s.n, data:s.x.map((u,k) => ({{x:u,y:s.y[k]}})),
      borderColor:C[i], backgroundColor:C[i]+'22', tension:0.3, borderWidth:2.5, pointRadius:0
  }})) }},
  options:{{ responsive:true, maintainAspectRatio:false,
    scales:{{ x:{{type:'linear',title:{{display:true,text:'PPO update'}}}}, y:{{title:{{display:true,text:'mean reward'}}}}}}}}
}});
</script>
"""
    return _page("PPO Overview", "/dashboard/ppo", body, ds="ppo")


def _render_ppo_rewards() -> str:
    d = _load_showcase()
    if not d.get("shards"):
        return _page("PPO Rewards", "/dashboard/ppo/rewards", _ppo_missing_body("PPO Rewards"), ds="ppo")
    shards = d["shards"]

    # Distribution: per-task mean reward (averaged across shards).
    cross = d["cross_shard_index"]
    means = []
    for tid, info in cross.items():
        rs = [sh["mean_reward"] for sh in info["shards"]]
        means.append(sum(rs) / len(rs))
    means.sort()
    n_pos = sum(1 for m in means if m >= 0)
    n_neg = len(means) - n_pos

    # Histogram bins.
    if means:
        lo, hi = min(means), max(means)
        nbins = 24
        step = (hi - lo) / nbins if hi > lo else 1
        bins = [0] * nbins
        for m in means:
            k = min(nbins - 1, int((m - lo) / step)) if step else 0
            bins[k] += 1
        bin_labels = [f"{lo + i*step:+.2f}" for i in range(nbins)]
    else:
        bins, bin_labels = [], []

    body = f"""
<h1>PPO reward analytics</h1>
<div class="subtitle">Reward range is <b>[-2.0, +1.0]</b> by design. Most components are penalties; mean is expected to be negative early — what matters is the trend.</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">Tasks with positive mean</div><div class="value">{n_pos}</div><div class="delta up">{n_pos/len(means)*100:.1f}%</div></div>
  <div class="kpi"><div class="label">Tasks with negative mean</div><div class="value">{n_neg}</div><div class="delta down">{n_neg/len(means)*100:.1f}%</div></div>
  <div class="kpi"><div class="label">Best task mean</div><div class="value">{max(means):+.3f}</div></div>
  <div class="kpi"><div class="label">Worst task mean</div><div class="value">{min(means):+.3f}</div></div>
</div>

<h2>Per-update mean reward · all 3 shards</h2>
<div class="chart"><div style="position:relative;height:380px"><canvas id="rew"></canvas></div></div>

<h2>Reward distribution across the 381 tasks</h2>
<div class="chart"><div style="position:relative;height:340px"><canvas id="hist"></canvas></div></div>

<h2>Reward signal palette</h2>
<table>
  <thead><tr><th>Component</th><th>Sign</th><th>Magnitude</th></tr></thead>
  <tbody>
    <tr><td>step_cost</td><td><span class="badge err">−</span></td><td>0.01 / step</td></tr>
    <tr><td>acting_blind</td><td><span class="badge err">−</span></td><td>0.20</td></tr>
    <tr><td>red_herring</td><td><span class="badge err">−</span></td><td>0.15</td></tr>
    <tr><td>repeat_command</td><td><span class="badge err">−</span></td><td>0.15 / repeat (cap 0.45)</td></tr>
    <tr><td>wrong_service</td><td><span class="badge err">−</span></td><td>0.15</td></tr>
    <tr><td>time_penalty</td><td><span class="badge err">−</span></td><td>0.05 × max(0, step − 5)</td></tr>
    <tr><td>phase_regression</td><td><span class="badge err">−</span></td><td>0.10</td></tr>
    <tr><td>blast_radius_increase</td><td><span class="badge err">−</span></td><td>0.10</td></tr>
    <tr><td>investigation_bonus</td><td><span class="badge ok">+</span></td><td>0.05 / unique read</td></tr>
    <tr><td>useful_log_query</td><td><span class="badge ok">+</span></td><td>0.10</td></tr>
    <tr><td>correct_mitigation</td><td><span class="badge ok">+</span></td><td>0.20</td></tr>
    <tr><td>root_cause_correct</td><td><span class="badge ok">+</span></td><td>0.30</td></tr>
    <tr><td>postmortem_quality</td><td><span class="badge ok">+</span></td><td>up to 0.20</td></tr>
    <tr><td>phase_order</td><td><span class="badge ok">+</span></td><td>0.10</td></tr>
    <tr><td>judge</td><td><span class="badge info">±</span></td><td>up to 0.15</td></tr>
  </tbody>
</table>

<script>
const SH = {json.dumps([{"n":sh["shard"],"x":[t["u"] for t in sh["trajectory"]],"y":[t["r"] for t in sh["trajectory"]]} for sh in shards])};
const C = ['#7aa7ff','#a78bfa','#ff9f7a'];
new Chart(document.getElementById('rew'), {{
  type:'line',
  data:{{ datasets: SH.map((s,i) => ({{
      label:'Shard '+s.n, data:s.x.map((u,k) => ({{x:u,y:s.y[k]}})),
      borderColor:C[i], backgroundColor:C[i]+'22', tension:0.3, borderWidth:2.5, pointRadius:0
  }})) }},
  options:{{ responsive:true, maintainAspectRatio:false,
    scales:{{ x:{{type:'linear',title:{{display:true,text:'PPO update'}}}}, y:{{title:{{display:true,text:'mean reward'}}}}}}}}
}});

new Chart(document.getElementById('hist'), {{
  type:'bar',
  data:{{ labels:{json.dumps(bin_labels)}, datasets:[{{ label:'tasks', data:{json.dumps(bins)},
            backgroundColor:{json.dumps(['rgba(74,222,128,0.7)' if float(b) >= 0 else 'rgba(248,113,113,0.7)' for b in bin_labels])} }}]}},
  options:{{ responsive:true, maintainAspectRatio:false,
    plugins:{{ legend:{{display:false}} }},
    scales:{{ x:{{title:{{display:true,text:'mean reward'}}}}, y:{{title:{{display:true,text:'task count'}}}}}}}}
}});
</script>
"""
    return _page("PPO Rewards", "/dashboard/ppo/rewards", body, ds="ppo")


def _render_ppo_tasks() -> str:
    d = _load_showcase()
    if not d.get("scenarios"):
        return _page("PPO Tasks", "/dashboard/ppo/tasks", _ppo_missing_body("PPO Tasks"), ds="ppo")
    scenarios = d["scenarios"]
    cross = d["cross_shard_index"]

    enriched = []
    for s in scenarios:
        info = cross.get(s["id"]) or {"shards": []}
        rs = [sh["mean_reward"] for sh in info["shards"]]
        first = [sh["first"] for sh in info["shards"]]
        last = [sh["last"] for sh in info["shards"]]
        visits = sum(sh["visits"] for sh in info["shards"])
        mean = sum(rs) / len(rs) if rs else 0.0
        delta = (sum(last) / len(last) - sum(first) / len(first)) if first else 0.0
        enriched.append({
            "id": s["id"], "title": s["title"], "diff": s["difficulty"],
            "cat": s["category"], "visits": visits, "mean": mean, "delta": delta,
            "n_actions": s["n_actions"],
        })
    enriched.sort(key=lambda r: r["mean"], reverse=True)

    rows = []
    for r in enriched[:300]:
        diff_class = {"easy": "ok", "medium": "warn", "hard": "err"}.get(r["diff"], "info")
        rows.append(
            f'<tr><td><code style="font-size:11px">{r["id"]}</code></td>'
            f'<td>{r["title"]}</td>'
            f'<td><span class="badge {diff_class}">{r["diff"]}</span></td>'
            f'<td>{r["cat"]}</td>'
            f'<td>{r["visits"]}</td>'
            f'<td style="color:{"#4ade80" if r["mean"]>=0 else "#f87171"}">{r["mean"]:+.3f}</td>'
            f'<td style="color:{"#4ade80" if r["delta"]>=0 else "#f87171"}">{r["delta"]:+.3f}</td>'
            f'<td>{r["n_actions"]}</td></tr>'
        )

    cat_counter: dict[str, int] = {}
    diff_counter: dict[str, int] = {"easy": 0, "medium": 0, "hard": 0}
    for s in scenarios:
        cat_counter[s["category"]] = cat_counter.get(s["category"], 0) + 1
        diff_counter[s["difficulty"]] = diff_counter.get(s["difficulty"], 0) + 1
    cats_sorted = sorted(cat_counter.items(), key=lambda x: -x[1])

    body = f"""
<h1>Per-task performance · 381 tasks</h1>
<div class="subtitle">Sorted by mean reward across shards. Δ = (last episode reward) − (first episode reward) per task.</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">Easy</div><div class="value">{diff_counter["easy"]}</div></div>
  <div class="kpi"><div class="label">Medium</div><div class="value">{diff_counter["medium"]}</div></div>
  <div class="kpi"><div class="label">Hard</div><div class="value">{diff_counter["hard"]}</div></div>
  <div class="kpi"><div class="label">Categories</div><div class="value">{len(cat_counter)}</div></div>
</div>

<h2>Distribution by category</h2>
<div class="chart"><div style="position:relative;height:340px"><canvas id="catbar"></canvas></div></div>

<h2>Top 300 tasks by mean reward</h2>
<table>
  <thead><tr><th>ID</th><th>Title</th><th>Diff</th><th>Category</th><th>Visits</th><th>Mean</th><th>Δ</th><th>Actions</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>

<script>
new Chart(document.getElementById('catbar'), {{
  type:'bar',
  data:{{ labels:{json.dumps([c for c,_ in cats_sorted])}, datasets:[{{
      label:'tasks', data:{json.dumps([n for _,n in cats_sorted])},
      backgroundColor:'rgba(122,167,255,0.7)' }}]}},
  options:{{ responsive:true, maintainAspectRatio:false, indexAxis:'y',
    plugins:{{ legend:{{display:false}} }} }}
}});
</script>
"""
    return _page("PPO Tasks", "/dashboard/ppo/tasks", body, ds="ppo")


def _render_ppo_training() -> str:
    d = _load_showcase()
    if not d.get("shards"):
        return _page("PPO Training", "/dashboard/ppo/training", _ppo_missing_body("PPO Training"), ds="ppo")
    shards = d["shards"]
    s = d["summary"]

    body = f"""
<h1>PPO training curves</h1>
<div class="subtitle">Every PPO update from every shard. Source: <code>kaggle ran notebooks/shard {{1,2,3}}/training_kaggle{{N}}.json</code>.</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">Updates / shard</div><div class="value">{s["n_updates_per_shard"]}</div></div>
  <div class="kpi"><div class="label">Rollouts / update</div><div class="value">{s["rollouts_per_update"]}</div></div>
  <div class="kpi"><div class="label">Max steps / episode</div><div class="value">{s["max_steps_per_ep"]}</div></div>
  <div class="kpi"><div class="label">Total transitions</div><div class="value">{s["n_updates_per_shard"] * s["rollouts_per_update"] * s["max_steps_per_ep"] * s["n_shards"]}</div></div>
</div>

<div class="chart-grid">
  <div class="chart"><h3>Mean reward</h3><div style="position:relative;height:300px"><canvas id="cr"></canvas></div></div>
  <div class="chart"><h3>PPO loss</h3><div style="position:relative;height:300px"><canvas id="cl"></canvas></div></div>
  <div class="chart"><h3>KL divergence</h3><div style="position:relative;height:300px"><canvas id="ck"></canvas></div></div>
  <div class="chart"><h3>Value error</h3><div style="position:relative;height:300px"><canvas id="cv"></canvas></div></div>
  <div class="chart"><h3>Policy loss</h3><div style="position:relative;height:300px"><canvas id="cp"></canvas></div></div>
  <div class="chart"><h3>Wall-clock per update (s)</h3><div style="position:relative;height:300px"><canvas id="ce"></canvas></div></div>
</div>

<script>
const SH = {json.dumps([{"n":sh["shard"], "t":sh["trajectory"]} for sh in shards])};
const C = ['#7aa7ff','#a78bfa','#ff9f7a'];
function L(id, key) {{
  new Chart(document.getElementById(id), {{
    type:'line',
    data:{{ datasets: SH.map((s,i) => ({{
      label:'Shard '+s.n,
      data:s.t.map(t => ({{x:t.u, y:t[key]}})),
      borderColor:C[i], backgroundColor:C[i]+'22', tension:0.3, borderWidth:2, pointRadius:0
    }})) }},
    options:{{ responsive:true, maintainAspectRatio:false,
      scales:{{ x:{{type:'linear',title:{{display:true,text:'update'}}}} }}}}
  }});
}}
L('cr','r'); L('cl','loss'); L('ck','kl'); L('cv','value_err'); L('cp','policy_loss'); L('ce','elapsed');
</script>
"""
    return _page("PPO Training", "/dashboard/ppo/training", body, ds="ppo")


def _render_ppo_cluster() -> str:
    body = """
<h1>Cluster integration · PPO mode</h1>
<div class="subtitle">The PPO-trained adapter targets the same <code>IncidentCommanderEnv</code> action set; cluster integration is unchanged.</div>

<h2>Code path</h2>
<table>
  <thead><tr><th>Mode</th><th>Effect</th><th>Env var</th></tr></thead>
  <tbody>
    <tr><td><span class="badge info">mock</span></td><td>All write actions return <code>[MOCK]</code> deltas; pure simulator.</td><td><code>MOCK_MODE=true</code> (default)</td></tr>
    <tr><td><span class="badge ok">live k8s</span></td><td>Write actions hit a real cluster via <code>kubernetes</code> python client.</td><td><code>REAL_K8S=true</code></td></tr>
    <tr><td><span class="badge warn">aws</span></td><td>Lambda / DDB / API Gateway / EventBridge actions hit real AWS.</td><td><code>USE_AWS=true</code></td></tr>
  </tbody>
</table>

<h2>Files</h2>
<table>
  <thead><tr><th>Path</th><th>Purpose</th></tr></thead>
  <tbody>
    <tr><td><code>infra/terraform/main.tf</code></td><td>Hetzner Cloud cluster (3× cx21 + load-balancer)</td></tr>
    <tr><td><code>infra/k8s/*.yaml</code></td><td>Deployments, Services, ConfigMaps for the 5 microservices</td></tr>
    <tr><td><code>infra/helm/acmecorp/</code></td><td>Helm chart that rolls everything out</td></tr>
    <tr><td><code>infra/aws/</code></td><td>CloudFormation alternative (free EKS credits)</td></tr>
    <tr><td><code>environment/k8s_real.py</code></td><td>Bridge from <code>env.step</code> to live cluster</td></tr>
  </tbody>
</table>
"""
    return _page("PPO Cluster", "/dashboard/ppo/cluster", body, ds="ppo")


def _render_ppo_aws() -> str:
    body = """
<h1>AWS scenario coverage · PPO mode</h1>
<div class="subtitle">381 sim scenarios ship across 4 AWS service families plus generated chaos profiles.</div>

<h2>Service-family coverage</h2>
<table>
  <thead><tr><th>Family</th><th>ID prefix</th><th>What it teaches</th></tr></thead>
  <tbody>
    <tr><td>Lambda</td><td><code>sim_easy_lambda_throttle*</code></td><td>Concurrency hits reserved cap; raise reserved-concurrency.</td></tr>
    <tr><td>DynamoDB</td><td><code>sim_easy_ddb_throttle*</code>, <code>sim_hard_ddb_chain*</code></td><td>Hot partition + GSI; scale WCU vs. fix key skew.</td></tr>
    <tr><td>API Gateway</td><td><code>sim_easy_apigw*</code>, <code>sim_med_apigw_lambda*</code>, <code>sim_hard_apigw_chain*</code></td><td>Stage-variable drift, integration timeouts, multi-stage cascade.</td></tr>
    <tr><td>EventBridge</td><td><code>sim_easy_eb*</code>, <code>sim_med_eb_lambda*</code></td><td>Rule mis-routes, FailedInvocations, two-hop chain.</td></tr>
    <tr><td>Step Functions</td><td><code>sim_med_sfn_lambda*</code></td><td>Catch vs. Retry semantics in execution history.</td></tr>
    <tr><td>IAM</td><td><code>sim_hard_iam_chain*</code></td><td>Missing assume-role two services deep.</td></tr>
  </tbody>
</table>

<h2>Configuration</h2>
<pre>
USE_AWS=true
AWS_REGION=us-east-1
AWS_PROFILE=incident-commander-rl
# Optional: pre-provisioned sandbox via scripts/aws_inventory.py --provision
</pre>
"""
    return _page("PPO AWS", "/dashboard/ppo/aws", body, ds="ppo")


def _render_ppo_adversarial() -> str:
    d = _load_showcase()
    if not d.get("scenarios"):
        return _page("PPO Adversarial", "/dashboard/ppo/adversarial", _ppo_missing_body("PPO Adversarial"), ds="ppo")
    cross = d["cross_shard_index"]
    adv = [s for s in d["scenarios"] if "Adversarial" in s["category"] or "Saboteur" in s["category"]
           or "Trolley" in s["category"] or "Runbook" in s["category"] or "Cascading" in s["category"]
           or "Red Herring" in s["category"] or "Slack" in s["category"]]
    rows = []
    for s in adv[:120]:
        info = cross.get(s["id"], {"shards": []})
        rs = [sh["mean_reward"] for sh in info["shards"]]
        mean = sum(rs) / len(rs) if rs else 0.0
        diff_class = {"easy": "ok", "medium": "warn", "hard": "err"}.get(s["difficulty"], "info")
        rows.append(
            f'<tr><td><code style="font-size:11px">{s["id"]}</code></td>'
            f'<td>{s["title"]}</td><td><span class="badge {diff_class}">{s["difficulty"]}</span></td>'
            f'<td>{s["category"]}</td>'
            f'<td style="color:{"#4ade80" if mean>=0 else "#f87171"}">{mean:+.3f}</td></tr>'
        )

    body = f"""
<h1>Adversarial scenarios · PPO coverage</h1>
<div class="subtitle">Scenarios with active adversaries, runbook traps, cascading failures, or noisy distractors.</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">Adversarial scenarios</div><div class="value">{len(adv)}</div></div>
  <div class="kpi"><div class="label">Total tasks</div><div class="value">{len(d["scenarios"])}</div></div>
  <div class="kpi"><div class="label">Coverage</div><div class="value">{len(adv)/len(d["scenarios"])*100:.1f}%</div></div>
</div>

<h2>Definition</h2>
<p style="color:var(--muted);max-width:780px">
  Adversarial scenarios add a saboteur agent that re-injects faults on a cooldown,
  noisy Slack channels designed to actively misdirect the agent, runbook traps
  where the standard playbook makes things worse, and cascading failures where
  the loud symptom hides the real root cause.
  Source files: <code>rl-agent/scenarios/sim/hard/sim_advanced_*.json</code>.
</p>

<h2>Per-scenario performance</h2>
<table>
  <thead><tr><th>ID</th><th>Title</th><th>Difficulty</th><th>Category</th><th>Mean reward</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""
    return _page("PPO Adversarial", "/dashboard/ppo/adversarial", body, ds="ppo")


def _render_ppo_curriculum() -> str:
    d = _load_showcase()
    if not d.get("scenarios"):
        return _page("PPO Curriculum", "/dashboard/ppo/curriculum", _ppo_missing_body("PPO Curriculum"), ds="ppo")
    diff_counter = d.get("difficulty_breakdown", {})
    cat_counter = d.get("category_breakdown", {})
    cats_sorted = sorted(cat_counter.items(), key=lambda x: -x[1])

    body = f"""
<h1>Curriculum composition</h1>
<div class="subtitle">In the PPO run we shuffled all 381 tasks (modulo-3 across shards) rather than escalating tiers — the curriculum knob is reserved for the next training pass.</div>

<div class="kpi-grid">
  <div class="kpi"><div class="label">Easy</div><div class="value">{diff_counter.get("easy", 0)}</div></div>
  <div class="kpi"><div class="label">Medium</div><div class="value">{diff_counter.get("medium", 0)}</div></div>
  <div class="kpi"><div class="label">Hard</div><div class="value">{diff_counter.get("hard", 0)}</div></div>
  <div class="kpi"><div class="label">Categories</div><div class="value">{len(cat_counter)}</div></div>
</div>

<h2>Categories</h2>
<table>
  <thead><tr><th>Category</th><th>Tasks</th></tr></thead>
  <tbody>
    {''.join(f'<tr><td>{c}</td><td>{n}</td></tr>' for c,n in cats_sorted)}
  </tbody>
</table>

<h2>Where the controller will plug in</h2>
<p style="color:var(--muted);max-width:780px">
  The legacy curriculum tiers (warmup → beginner → intermediate → advanced → expert)
  remain wired into <code>environment/curriculum.py</code> and
  <code>POST /reset</code> with <code>use_curriculum:true</code>. The next training
  pass will turn it on so the agent sees easy scenarios first and graduates only
  after rolling success ≥ 0.65 in the current tier.
</p>
"""
    return _page("PPO Curriculum", "/dashboard/ppo/curriculum", body, ds="ppo")


def _render_ppo_judge() -> str:
    body = """
<h1>Judge configuration · PPO mode</h1>
<div class="subtitle">During the Kaggle run we used the DeepSeek-R1 critic for value estimation, not the LLM judge — it remains fully wired for fine-tuning passes.</div>

<h2>Two scoring paths</h2>
<table>
  <thead><tr><th>Path</th><th>Used for</th><th>Where</th></tr></thead>
  <tbody>
    <tr><td><span class="badge info">Critic value</span></td><td>Per-(state, action) value baseline V(s,a) consumed by GAE.</td><td><code>environment/llm_critic.py</code></td></tr>
    <tr><td><span class="badge ok">LLM judge</span></td><td>Per-action 0–1 score sliced into the reward; persona-styled (junior/senior/principal).</td><td><code>environment/judge.py</code></td></tr>
  </tbody>
</table>

<h2>Critic prompt rubric (excerpt)</h2>
<pre>
You are an expert SRE auditor. Given:
  - the current cluster observation,
  - a candidate action the agent is about to take,
return a score 0..10:
  0 = catastrophic / clearly wrong
  3 = stalls progress
  5 = neutral
  7 = useful read or sane fix
  9 = directly addresses the root cause
Return ONLY the integer.
</pre>

<h2>Switching at inference time</h2>
<pre>
curl -X POST $BASE/judge/config \\
  -H 'Content-Type: application/json' \\
  -d '{"persona":"principal","use_llm":true}'
</pre>
"""
    return _page("PPO Judge", "/dashboard/ppo/judge", body, ds="ppo")


def _render_ppo_api() -> str:
    endpoints = [
        ("GET", "/showcase",            "Apple-style fluid showcase page (this dataset)"),
        ("GET", "/showcase/data",       "Pre-computed bundle (381 scenarios + 3 shards)"),
        ("GET", "/dashboard/ppo",                 "PPO Overview (this page family)"),
        ("GET", "/dashboard/ppo/rewards",         "PPO reward analytics"),
        ("GET", "/dashboard/ppo/tasks",           "PPO per-task table"),
        ("GET", "/dashboard/ppo/training",        "PPO training curves"),
        ("GET", "/dashboard/ppo/cluster",         "Cluster integration in PPO mode"),
        ("GET", "/dashboard/ppo/aws",             "AWS scenario coverage"),
        ("GET", "/dashboard/ppo/adversarial",     "Adversarial scenarios"),
        ("GET", "/dashboard/ppo/curriculum",      "Curriculum composition"),
        ("GET", "/dashboard/ppo/judge",           "Judge config"),
        ("GET", "/dashboard?ds=legacy",           "Switch back to the legacy 11-task dataset"),
    ]
    rows = "".join(
        f'<tr><td><span class="badge {"info" if m == "GET" else "ok"}">{m}</span></td>'
        f'<td><code>{p}</code></td><td>{d}</td></tr>'
        for m, p, d in endpoints
    )
    body = f"""
<h1>PPO endpoint catalogue</h1>
<div class="subtitle">Routes specific to the 381-task PPO Kaggle run. Core /reset, /step, /state etc. are documented in the legacy API view.</div>
<table>
  <thead><tr><th>Method</th><th>Path</th><th>Description</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
<p style="margin-top:16px">OpenAPI docs: <a class="nav-item" href="/docs">/docs</a></p>
"""
    return _page("PPO API", "/dashboard/ppo/api", body, ds="ppo")


# ---------------------------------------------------------------------------
# Register routes
# ---------------------------------------------------------------------------


def register(app: FastAPI) -> None:
    @app.get("/dashboard/rewards", response_class=HTMLResponse)
    def d_rewards():
        return HTMLResponse(_render_rewards(app))

    @app.get("/dashboard/tasks", response_class=HTMLResponse)
    def d_tasks(run: str | None = Query(default=None)):
        return HTMLResponse(_render_tasks(app, run))

    @app.get("/dashboard/training", response_class=HTMLResponse)
    def d_training(run: str | None = Query(default=None)):
        return HTMLResponse(_render_training(run))

    @app.get("/dashboard/cluster", response_class=HTMLResponse)
    def d_cluster():
        return HTMLResponse(_render_cluster(app))

    @app.get("/dashboard/aws", response_class=HTMLResponse)
    def d_aws():
        return HTMLResponse(_render_aws())

    @app.get("/dashboard/adversarial", response_class=HTMLResponse)
    def d_adversarial():
        return HTMLResponse(_render_adversarial(app))

    @app.get("/dashboard/curriculum", response_class=HTMLResponse)
    def d_curriculum():
        return HTMLResponse(_render_curriculum(app))

    @app.get("/dashboard/judge", response_class=HTMLResponse)
    def d_judge():
        return HTMLResponse(_render_judge(app))

    @app.get("/dashboard/api", response_class=HTMLResponse)
    def d_api():
        return HTMLResponse(_render_api())

    @app.get("/dashboard/metrics", response_class=JSONResponse)
    def d_metrics(run: str | None = Query(default=None)):
        name, rows, summary = _load_metrics(run)
        return {"run": name, "rows": rows, "summary": summary, "available_runs": _list_runs()}

    # Replace the /dashboard handler with the multi-page overview
    # (the original handler in server.py will be shadowed by FastAPI's first-match,
    # so we register a wrapper that server.py will call via the new route below.)

    @app.get("/dashboard/overview", response_class=HTMLResponse)
    def d_overview(run: str | None = Query(default=None)):
        return HTMLResponse(_render_overview(app, run))

    # ---- PPO Kaggle dataset (381 tasks, 3 shards) ------------------------
    @app.get("/dashboard/ppo", response_class=HTMLResponse)
    def d_ppo_overview():
        return HTMLResponse(_render_ppo_overview())

    @app.get("/dashboard/ppo/rewards", response_class=HTMLResponse)
    def d_ppo_rewards():
        return HTMLResponse(_render_ppo_rewards())

    @app.get("/dashboard/ppo/tasks", response_class=HTMLResponse)
    def d_ppo_tasks():
        return HTMLResponse(_render_ppo_tasks())

    @app.get("/dashboard/ppo/training", response_class=HTMLResponse)
    def d_ppo_training():
        return HTMLResponse(_render_ppo_training())

    @app.get("/dashboard/ppo/cluster", response_class=HTMLResponse)
    def d_ppo_cluster():
        return HTMLResponse(_render_ppo_cluster())

    @app.get("/dashboard/ppo/aws", response_class=HTMLResponse)
    def d_ppo_aws():
        return HTMLResponse(_render_ppo_aws())

    @app.get("/dashboard/ppo/adversarial", response_class=HTMLResponse)
    def d_ppo_adversarial():
        return HTMLResponse(_render_ppo_adversarial())

    @app.get("/dashboard/ppo/curriculum", response_class=HTMLResponse)
    def d_ppo_curriculum():
        return HTMLResponse(_render_ppo_curriculum())

    @app.get("/dashboard/ppo/judge", response_class=HTMLResponse)
    def d_ppo_judge():
        return HTMLResponse(_render_ppo_judge())

    @app.get("/dashboard/ppo/api", response_class=HTMLResponse)
    def d_ppo_api():
        return HTMLResponse(_render_ppo_api())
