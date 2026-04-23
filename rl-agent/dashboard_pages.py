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


def _nav(active: str) -> str:
    items = "".join(
        f'<a href="{href}" class="nav-item{" active" if href == active else ""}">{label}</a>'
        for href, label in _PAGES
    )
    return f'<nav class="navbar">{items}</nav>'


_CSS = """
<style>
  :root {
    --bg: #0b1021;
    --panel: #141b35;
    --panel2: #1b2544;
    --accent: #7aa7ff;
    --accent2: #ff9f7a;
    --good: #4ade80;
    --bad: #f87171;
    --text: #e6ecff;
    --muted: #8aa0c7;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background: var(--bg); color: var(--text); }
  .navbar { display: flex; flex-wrap: wrap; gap: 2px; background: #0a0f22;
            padding: 8px 16px; position: sticky; top: 0; z-index: 10;
            border-bottom: 1px solid #27345e; }
  .nav-item { color: var(--muted); padding: 8px 14px; text-decoration: none;
              border-radius: 6px; font-size: 14px; font-weight: 500; }
  .nav-item:hover { background: #1b2544; color: var(--text); }
  .nav-item.active { background: var(--accent); color: #0b1021; }
  .page { max-width: 1400px; margin: 0 auto; padding: 20px; }
  h1 { margin: 0 0 4px; }
  h2 { margin-top: 28px; color: var(--accent); font-size: 20px; }
  .subtitle { color: var(--muted); margin-bottom: 22px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px,1fr));
              gap: 14px; margin-bottom: 22px; }
  .kpi { background: var(--panel); padding: 18px; border-radius: 10px;
         border: 1px solid #27345e; }
  .kpi .label { color: var(--muted); font-size: 12px; text-transform: uppercase;
                letter-spacing: 0.08em; }
  .kpi .value { font-size: 28px; font-weight: 700; margin-top: 6px; }
  .kpi .delta { font-size: 12px; margin-top: 4px; }
  .delta.up { color: var(--good); } .delta.down { color: var(--bad); }
  .chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px,1fr));
                gap: 16px; }
  .chart { background: var(--panel); padding: 16px; border-radius: 10px;
           border: 1px solid #27345e; }
  .chart h3 { margin: 0 0 8px; font-size: 15px; color: var(--accent2); }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #27345e; }
  th { color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 11px;
       letter-spacing: 0.06em; }
  .badge { display:inline-block; padding: 2px 8px; border-radius: 12px;
           font-size: 11px; font-weight: 600; }
  .badge.ok { background: #134f2d; color: var(--good); }
  .badge.warn { background: #553d12; color: #fbbf24; }
  .badge.err { background: #551c1c; color: var(--bad); }
  .badge.info { background: #1d3557; color: var(--accent); }
  pre { background: #07091a; padding: 12px; border-radius: 8px; overflow-x: auto;
        font-size: 12px; border: 1px solid #27345e; }
  .empty { color: var(--muted); font-style: italic; padding: 10px; }
</style>
"""


def _page(title: str, active: str, body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title} — IncidentCommander</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
{_CSS}
</head><body>
{_nav(active)}
<div class="page">{body}</div>
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
    breakdown = {}
    if env is not None:
        try:
            breakdown = dict(getattr(env, "_last_reward_breakdown", {}) or {})
        except Exception:
            breakdown = {}
    signals = [
        ("triage_reward",            "Triage: correct first instinct"),
        ("investigation_bonus",      "Evidence gathering"),
        ("tool_proficiency",         "Proper use of tools"),
        ("red_herring_penalty",      "Chased a red herring"),
        ("acting_blind_penalty",     "Wrote without investigating"),
        ("repeat_command_penalty",   "Duplicate command"),
        ("phase_bonus",              "Phase-aware progression"),
        ("mitigation_efficiency",    "Fixed in ≤3 writes"),
        ("mitigation_thrash_penalty","Thrashing (>6 writes)"),
        ("evidence_alignment",       "Postmortem cites evidence"),
        ("diverse_evidence",         "≥3 evidence sources"),
        ("recovery_verified",        "Pods actually Running"),
        ("judge_total",              "LLM judge holistic score"),
        ("correct_rollback",         "Rolled back right service"),
        ("correct_postmortem",       "Correct root cause"),
    ]
    rows_html = "".join(
        f"<tr><td><b>{k}</b></td><td>{desc}</td><td>{breakdown.get(k, 0.0):+.3f}</td></tr>"
        for k, desc in signals
    )
    body = f"""
<h1>Reward signals</h1>
<div class="subtitle">15 shaped reward components gate the learning signal. Values shown are from the LAST episode.</div>

<div class="chart-grid">
  <div class="chart"><h3>Last-episode breakdown</h3><canvas id="rb" height="200"></canvas></div>
  <div class="chart"><h3>Signal catalogue</h3>
    <table><thead><tr><th>Signal</th><th>Meaning</th><th>Last</th></tr></thead>
    <tbody>{rows_html}</tbody></table>
  </div>
</div>

<script>
const bd = {json.dumps(breakdown)};
const keys = Object.keys(bd);
const vals = keys.map(k => bd[k]);
const colors = vals.map(v => v >= 0 ? '#4ade80' : '#f87171');
new Chart(document.getElementById('rb'), {{
  type: 'bar',
  data: {{ labels: keys, datasets: [{{data: vals, backgroundColor: colors}}]}},
  options: {{ indexAxis: 'y', plugins: {{ legend: {{ display:false }} }},
             scales: {{ x: {{ ticks: {{ color:'#8aa0c7' }} }},
                        y: {{ ticks: {{ color:'#e6ecff' }} }} }} }}
}});
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
    try:
        k8s = getattr(env, "_k8s_backend", None)
        if k8s and getattr(k8s, "enabled", False):
            real_enabled = True
            status = k8s.cluster_status()  # expected dict with namespaces
            ns_info = status.get("namespaces", []) if isinstance(status, dict) else []
    except Exception:
        pass

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
             else '<span class="badge warn">Mock (REAL_K8S not set)</span>')
    body = f"""
<h1>Cluster health</h1>
<div class="subtitle">Backend status {badge}</div>

<h2>Namespaces & deployments</h2>
<table>
  <thead><tr><th>Namespace</th><th>Deployment</th><th>Replicas</th><th>Ready</th><th>Status</th></tr></thead>
  <tbody>{rows_html or '<tr><td colspan="5" class="empty">No real cluster attached. Set <code>REAL_K8S=true</code> and point <code>KUBECONFIG</code> at your EKS cluster.</td></tr>'}</tbody>
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


def _render_aws() -> str:
    try:
        from environment.aws_integrations import aws_status
        status = aws_status()
    except Exception as e:
        status = {"error": str(e), "region": None, "services": {}}

    svcs = status.get("services", {})
    region = status.get("region") or "(unset)"
    account = status.get("account_id") or "(no credentials)"

    rows_html = ""
    n_on = 0
    for name, info in svcs.items():
        on = bool(info.get("enabled"))
        n_on += int(on)
        badge = ('<span class="badge ok">connected</span>' if on
                 else '<span class="badge warn">not configured</span>')
        detail_bits = []
        for k, v in info.items():
            if k == "enabled" or v is None:
                continue
            detail_bits.append(f"<code>{k}</code>: {v}")
        rows_html += (
            f"<tr><td><b>{name}</b></td>"
            f"<td>{badge}</td>"
            f"<td>{' · '.join(detail_bits) or '—'}</td></tr>"
        )

    services_defined = [
        ("VPC + subnets + NAT", "Dedicated 10.20.0.0/16 network across 2 AZs."),
        ("EKS",                 "Managed Kubernetes where AcmeCorp microservices + Chaos Mesh run."),
        ("ECR",                 "Private registry for the env server + trainer images."),
        ("S3",                  "Versioned bucket for LoRA adapters + metrics.jsonl archive."),
        ("DynamoDB",            "PITR-enabled table holding per-run / per-task mastery."),
        ("CloudWatch Logs",     "Two log groups: /aws/eks/.../application + /aws/incident-commander/agent."),
        ("CloudWatch Metrics",  "Custom IncidentCommander namespace + ErrorRate > 5% alarm."),
        ("SNS",                 "Alert topic the agent publishes to when a mitigation is applied."),
        ("Secrets Manager",     "Stores OPENAI_API_KEY so no secrets are baked into the image."),
        ("IAM (IRSA)",          "Least-privilege pod role — S3/Dynamo/Logs/CW/SNS/Secrets/Bedrock."),
        ("Lambda",              "Subscribed to the SNS topic; POSTs /reset to trigger new episodes."),
        ("Bedrock",             "Runtime permission for the LLM judge (Claude / Titan)."),
    ]
    arch_rows = "".join(
        f"<tr><td><b>{n}</b></td><td>{d}</td></tr>" for n, d in services_defined
    )

    body = f"""
<h1>AWS wiring</h1>
<div class="subtitle">
  Account <b>{account}</b> · Region <b>{region}</b> · Reachable services:
  <span class="badge info">{n_on}/{len(svcs) or 12}</span>
</div>

<h2>Live service status</h2>
<div class="subtitle">Each integration in <code>environment/aws_integrations.py</code>
is gated on env vars + boto3 credentials; unconfigured rows are safe no-ops.</div>
<table>
  <thead><tr><th>Service</th><th>State</th><th>Detail</th></tr></thead>
  <tbody>{rows_html or '<tr><td colspan="3" class="empty">No AWS services configured — set AWS_REGION and the service-specific env vars.</td></tr>'}</tbody>
</table>

<h2>Architecture (provisioned by <code>infra/aws/main.tf</code>)</h2>
<table>
  <thead><tr><th>Service</th><th>Role in IncidentCommander</th></tr></thead>
  <tbody>{arch_rows}</tbody>
</table>

<h2>Apply</h2>
<pre>cd incident-commander/infra/aws
terraform init
terraform apply -var='project=incident-commander' -var='region=us-east-1'
terraform output env_file &gt; ../../.env.aws.local</pre>

<h2>IAM policy highlights</h2>
<pre>S3         PutObject / GetObject / ListBucket   (checkpoints bucket only)
DynamoDB   GetItem / PutItem / Query            (curriculum table only)
CloudWatch PutMetricData + FilterLogEvents
SNS        Publish                              (alerts topic only)
Secrets    GetSecretValue                       (openai secret only)
Bedrock    InvokeModel / InvokeModelWithResponseStream</pre>
"""
    return _page("AWS", "/dashboard/aws", body)


def _render_adversarial(app: FastAPI) -> str:
    designer = getattr(app.state, "adversarial", None)
    history = []
    enabled = False
    try:
        history = list(getattr(designer, "history", []) or [])[-20:]
        enabled = bool(getattr(designer, "_llm_enabled", False))
    except Exception:
        pass
    rows_html = "".join(
        f"<tr><td>{h.get('task_id','?')}</td>"
        f"<td>{', '.join(h.get('faults', []))}</td>"
        f"<td>{h.get('difficulty','?')}</td>"
        f"<td><code>{json.dumps(h.get('red_herrings', []))[:80]}</code></td></tr>"
        for h in history
    ) or '<tr><td colspan="4" class="empty">No adversarial scenarios designed yet. POST /adversarial/design to generate one.</td></tr>'

    body = f"""
<h1>Adversarial scenario designer</h1>
<div class="subtitle">Designer is <b>{'LLM-backed' if enabled else 'procedural fallback'}</b>. History: last {len(history)} scenarios.</div>
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
    mastery = {}
    recent = []
    try:
        mastery = dict(getattr(c.state, "mastery", {}) or {})
        recent = list(getattr(c.state, "recent_episodes", []) or [])[-20:]
    except Exception:
        pass

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
<div class="subtitle">Current tier: <span class="badge info">{tier}</span></div>

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
