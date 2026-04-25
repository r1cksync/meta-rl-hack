"""Replay artifact builder — emits a standalone `replay.html` time-lapse.

The judges' automated graders score plain `[START]/[STEP]/[END]` log lines.
The replay artifact runs alongside that, dumping a self-contained HTML file
that visualises:

    * The service-topology DAG, with nodes colour-coded by status per tick.
    * A per-tick line chart of error rate / latency / blast radius.
    * The action history (agent moves) and saboteur moves on a shared timeline.
    * The Slack channel chatter as a side panel.

The HTML embeds a single JSON blob and uses Vis.js + Chart.js from CDN to
render. There are no external assets — judges just open the file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IncidentCommander — Replay {episode_id}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body  {{ margin:0; font-family: -apple-system,Segoe UI,Roboto,sans-serif;
          background:#0d1117; color:#c9d1d9; }}
  header {{ padding:14px 20px; background:#161b22; border-bottom:1px solid #30363d;
           display:flex; align-items:center; gap:18px; }}
  header h1 {{ margin:0; font-size:18px; font-weight:600; }}
  header .pill {{ background:#21262d; padding:4px 10px; border-radius:12px;
                 font-size:12px; color:#8b949e; }}
  #grid {{ display:grid; grid-template-columns: 2fr 1fr; gap:1px;
          background:#30363d; height: calc(100vh - 110px); }}
  #grid > div {{ background:#0d1117; padding:10px; overflow:auto; }}
  #network {{ height: 60%; border-bottom:1px solid #30363d; }}
  #charts  {{ height: 40%; }}
  #side    {{ display:flex; flex-direction:column; gap:8px; }}
  .panel  {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
            padding:10px; }}
  .panel h2 {{ margin:0 0 6px 0; font-size:13px; color:#58a6ff;
              text-transform:uppercase; letter-spacing:0.5px; }}
  .ev      {{ padding:4px 6px; border-left:3px solid #30363d; margin-bottom:4px;
              font-size:12px; }}
  .ev.agent    {{ border-color:#3fb950; }}
  .ev.saboteur {{ border-color:#f85149; }}
  .ev.slack    {{ border-color:#d29922; }}
  .ev .meta {{ color:#8b949e; font-size:11px; }}
  #controls {{ padding:10px 20px; background:#161b22; border-top:1px solid #30363d;
              display:flex; align-items:center; gap:14px; }}
  #controls input[type=range] {{ flex:1; }}
  button {{ background:#238636; color:white; border:0; padding:6px 14px;
           border-radius:6px; cursor:pointer; font-size:13px; }}
  button.pause {{ background:#21262d; }}
</style>
</head>
<body>
<header>
  <h1>📼 IncidentCommander Replay</h1>
  <span class="pill">episode: {episode_id}</span>
  <span class="pill">task: {task_id}</span>
  <span class="pill">steps: {n_steps}</span>
  <span class="pill">final reward: {final_reward}</span>
  <span class="pill">mitigated: {mitigated}</span>
</header>
<div id="grid">
  <div>
    <div id="network"></div>
    <div id="charts"><canvas id="metricChart"></canvas></div>
  </div>
  <div id="side">
    <div class="panel" id="events"><h2>Timeline</h2><div id="evlist"></div></div>
    <div class="panel" id="slackpanel"><h2>#sre-incidents</h2><div id="slacklist"></div></div>
  </div>
</div>
<div id="controls">
  <button id="play">▶ Play</button>
  <input type="range" id="scrub" min="0" max="{n_steps}" value="0">
  <span id="tickLabel">tick 0 / {n_steps}</span>
</div>

<script>
const REPLAY = {payload};

// ── Network setup ───────────────────────────────────────────────────
const STATUS_COLOR = {{
  healthy:'#3fb950', degraded:'#d29922', memory_leak:'#f85149',
  cpu_throttled:'#db61a2', dead:'#6e7681', corrupted:'#a371f7',
  rebuilding:'#58a6ff', rolling_back:'#f0883e'
}};
const nodes = new vis.DataSet(REPLAY.nodes.map(n => ({{
  id: n, label: n, color: STATUS_COLOR.healthy, font:{{color:'#fff'}},
  shape:'dot', size:14
}})));
const edges = new vis.DataSet(REPLAY.edges.map(([a,b]) => ({{
  from: a, to: b, arrows:'to', color:'#30363d'
}})));
const net = new vis.Network(document.getElementById('network'),
  {{nodes, edges}},
  {{physics:{{stabilization:true}},
    interaction:{{hover:true}},
    nodes:{{borderWidth:1.5}}
  }});

// ── Chart ───────────────────────────────────────────────────────────
const ctx = document.getElementById('metricChart');
const chart = new Chart(ctx, {{
  type:'line',
  data:{{
    labels: REPLAY.frames.map(f => 'tick '+f.tick),
    datasets:[
      {{label:'mean error rate', data: REPLAY.frames.map(f => f.mean_err),
       borderColor:'#f85149', tension:0.25}},
      {{label:'mean latency (ms)', data: REPLAY.frames.map(f => f.mean_lat),
       borderColor:'#d29922', tension:0.25, yAxisID:'y2'}},
      {{label:'reward', data: REPLAY.frames.map(f => f.reward),
       borderColor:'#3fb950', tension:0.25}},
    ]
  }},
  options:{{
    plugins:{{legend:{{labels:{{color:'#c9d1d9'}}}}}},
    scales:{{
      x:{{ticks:{{color:'#8b949e'}}}},
      y:{{ticks:{{color:'#8b949e'}}, beginAtZero:true}},
      y2:{{position:'right', ticks:{{color:'#8b949e'}}, grid:{{drawOnChartArea:false}}}}
    }}
  }}
}});

// ── Tick scrubber ───────────────────────────────────────────────────
const evList    = document.getElementById('evlist');
const slackList = document.getElementById('slacklist');
const tickLabel = document.getElementById('tickLabel');
const scrub     = document.getElementById('scrub');

function applyTick(i) {{
  const f = REPLAY.frames[i];
  if (!f) return;
  // recolour nodes
  Object.entries(f.statuses).forEach(([name, st]) => {{
    nodes.update({{id:name, color: STATUS_COLOR[st] || '#6e7681'}});
  }});
  // events up to this tick
  evList.innerHTML = REPLAY.events.filter(e => e.tick <= f.tick)
    .slice(-20).map(e =>
      `<div class="ev ${{e.kind}}"><b>[${{e.kind}}]</b> ${{e.text}}
        <div class="meta">tick ${{e.tick}}</div></div>`).join('');
  slackList.innerHTML = REPLAY.slack.filter(m => m.tick <= f.tick)
    .slice(-12).map(m =>
      `<div class="ev slack"><b>${{m.author}}:</b> ${{m.text}}
        <div class="meta">[${{m.severity}}] tick ${{m.tick}}</div></div>`).join('');
  tickLabel.textContent = `tick ${{f.tick}} / ${{REPLAY.frames.length-1}}`;
}}
scrub.addEventListener('input', e => applyTick(+e.target.value));
applyTick(0);

// ── Auto-play ───────────────────────────────────────────────────────
let playing = false, timer = null;
const playBtn = document.getElementById('play');
playBtn.onclick = () => {{
  playing = !playing;
  playBtn.textContent = playing ? '⏸ Pause' : '▶ Play';
  playBtn.classList.toggle('pause', playing);
  if (playing) {{
    timer = setInterval(() => {{
      let v = +scrub.value + 1;
      if (v > REPLAY.frames.length-1) v = 0;
      scrub.value = v;
      applyTick(v);
    }}, 600);
  }} else {{
    clearInterval(timer);
  }}
}};
</script>
</body>
</html>
"""


def _frame_from_state(sim_state, reward: float) -> dict:
    """Snapshot the current sim state as a single replay frame."""
    topo = sim_state.topology
    statuses = {n: node.status for n, node in topo.nodes.items()}
    err_vals = [node.error_rate for node in topo.nodes.values()]
    lat_vals = [node.latency_p50 for node in topo.nodes.values()]
    return {
        "tick":     sim_state.tick_n,
        "statuses": statuses,
        "mean_err": round(sum(err_vals) / max(len(err_vals), 1), 4),
        "mean_lat": round(sum(lat_vals) / max(len(lat_vals), 1), 1),
        "reward":   round(reward, 4),
    }


def record_step(sim_state, action: dict, action_result: str,
                step_reward: float) -> None:
    """Append a frame + an event to sim_state.history."""
    if sim_state is None:
        return
    sim_state.history.append({
        "frame": _frame_from_state(sim_state, step_reward),
        "agent_action": action,
        "result": action_result[:240],
    })


def build_replay(sim_state, *, task_id: str, episode_id: str,
                 final_reward: float, mitigated: bool,
                 out_path: Path) -> Path:
    """Materialise a standalone replay.html. Returns the path written."""
    topo = sim_state.topology
    nodes = list(topo.nodes.keys())
    edges = []
    for src, dsts in topo.deps.items():
        for d in dsts:
            edges.append([src, d])

    frames = [h["frame"] for h in sim_state.history]
    events: list[dict[str, Any]] = []
    for h in sim_state.history:
        a = h["agent_action"]
        events.append({
            "tick": h["frame"]["tick"], "kind": "agent",
            "text": f'{a.get("id","?")} {a.get("params", {})}',
        })
    for ev in sim_state.saboteur_events:
        events.append({"tick": ev.tick, "kind": "saboteur",
                       "text": f"[{ev.phase}] {ev.note}"})

    slack = []
    if sim_state.slack is not None:
        slack = [m.to_dict() for m in sim_state.slack.all()]

    payload = json.dumps({
        "nodes":  nodes,
        "edges":  edges,
        "frames": frames,
        "events": sorted(events, key=lambda e: e["tick"]),
        "slack":  slack,
    }, default=str)

    html = _TEMPLATE.format(
        payload=payload,
        episode_id=episode_id,
        task_id=task_id,
        n_steps=max(len(frames) - 1, 0),
        final_reward=f"{final_reward:.3f}",
        mitigated="✅" if mitigated else "❌",
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
