"""
voice/auto_demo.py — drive the showcase site through every scene with Playwright,
record the screen, and mux the 12 voiceover MP3s on top to produce voice/out/demo.mp4.

Why this exists:
  Your SHOT_LIST.md already encodes per-scene actions and a per-scene duration
  (taken from each scene*.mp3). This script turns those beats into deterministic
  Playwright actions, sleeps the remainder of each scene's duration, and lets
  Playwright's built-in video recorder capture the whole take in one go.

What it does NOT do:
  - It does NOT switch to GitHub / Kaggle / VS Code (scenes 8, 9, 11 reference
    those). The recorder stays inside the showcase tab the whole time. For those
    beats, it just lingers on relevant showcase content (pipeline section / infra
    section / dashboard link). You can re-record those three scenes manually and
    splice them in DaVinci, OR replace the corresponding `beats` list below with
    `page.goto(...)` to open those URLs in the same tab.
  - It does not move a "real" mouse cursor visibly — Playwright moves the page's
    own mouse, but cursor isn't drawn on the recorded video. If you want a
    visible cursor, add a CSS overlay (see CURSOR_INJECT below — disabled by
    default).

Prereqs (one-time):
  pip install playwright
  playwright install chromium
  # ffmpeg must be on PATH (you already use ffprobe in this repo)

Usage:
  # record + mux in one go (default — produces voice/out/demo.mp4)
  python voice/auto_demo.py

  # record only (skip mux), useful while iterating on beats
  python voice/auto_demo.py --no-mux

  # mux only (uses the most recent .webm Playwright dropped in voice/out/_video/)
  python voice/auto_demo.py --no-record

  # record against a local copy instead of the live HF Space
  python voice/auto_demo.py --url http://localhost:7860/showcase

  # show the browser instead of running headless
  python voice/auto_demo.py --headed
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ROOT     = Path(__file__).resolve().parent.parent          # incident-commander/
VOICE    = ROOT / "voice"
OUT      = VOICE / "out"
VIDEO    = OUT / "_video"                                  # Playwright dumps webm here
FINAL    = OUT / "demo.mp4"
CONCAT_A = OUT / "_voice_concat.mp3"                        # 12 MP3s glued
BGM_SRC  = OUT / "_bgm_source.mp3"                          # downloaded upbeat track (Kevin MacLeod "Inspired")

DEFAULT_URL = "https://sagnik-mukherjee-incodent-commander.hf.space/showcase"

W, H = 1920, 1080

# Set True to inject a big visible mouse cursor that follows page.mouse moves.
# (Pure CSS+JS overlay — recorded frames will show a yellow dot.)
CURSOR_INJECT = True


# ---------------------------------------------------------------------------
# Per-scene choreography. Each scene is a list of (delay_seconds, fn) beats.
# delay_seconds = time to wait BEFORE this beat (relative to scene start).
# fn(page) performs the beat. Sleep until end-of-scene happens automatically.
# ---------------------------------------------------------------------------

def _scroll_to(page, selector: str, *, smooth: bool = True, block: str = "start"):
    behavior = "smooth" if smooth else "auto"
    page.evaluate(
        """([sel, behavior, block]) => {
            const el = document.querySelector(sel);
            if (el) el.scrollIntoView({behavior, block});
        }""",
        [selector, behavior, block],
    )

def _scroll_px(page, delta: int):
    page.evaluate(f"window.scrollBy({{top: {delta}, left: 0, behavior: 'smooth'}})")

def _hover(page, selector: str, nth: int = 0):
    loc = page.locator(selector).nth(nth)
    try:
        loc.scroll_into_view_if_needed(timeout=1500)
        loc.hover(timeout=2000)
    except Exception as e:
        print(f"   hover skipped ({selector}#{nth}): {e}")

def _click(page, selector: str, nth: int = 0):
    # If a modal is open, dismiss it first so it doesn't intercept the click
    try:
        if page.locator("#modal-back.show").count() > 0:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
    except Exception:
        pass
    loc = page.locator(selector).nth(nth)
    try:
        loc.scroll_into_view_if_needed(timeout=1500)
        loc.click(timeout=2500)
    except Exception as e:
        print(f"   click skipped ({selector}#{nth}): {e}")

def _move_mouse(page, x: int, y: int):
    page.mouse.move(x, y, steps=20)

# Each entry: (relative_t_seconds, lambda page: ...)
SCENES = {
    "scene01": [          # Hook
        (0.0, lambda p: _scroll_to(p, "body", smooth=False, block="start")),
        (5.0, lambda p: _scroll_px(p,  60)),
        (8.0, lambda p: _scroll_px(p, -60)),
        (15.0, lambda p: _hover(p, "h1")),
        (23.0, lambda p: _move_mouse(p, W - 200, 60)),  # toward top-right buttons
    ],
    "scene02": [          # KPI strip
        (0.0, lambda p: _scroll_to(p, "#overview")),
        (5.0, lambda p: _hover(p, ".kpi", 0)),
        (11.0, lambda p: _hover(p, ".kpi", 1)),
        (18.0, lambda p: _hover(p, ".kpi", 2)),
        (25.0, lambda p: _hover(p, ".kpi", 3)),
    ],
    "scene03": [          # Pillars + Slack noise
        (0.0, lambda p: _scroll_to(p, "#overview", block="end")),
        (4.0, lambda p: _hover(p, "#overview .card", 1)),
        (8.0, lambda p: _hover(p, "#overview .card", 2)),
        (12.0, lambda p: _scroll_to(p, "#slack")),
        (16.0, lambda p: _hover(p, "#slack .codeblock", 0)),
        (19.0, lambda p: _hover(p, "#slack .codeblock", 1)),
        (22.0, lambda p: _scroll_to(p, "#slack .mermaid-frame", block="center")),
    ],
    "scene04": [          # "Did it actually learn?" + Results
        (0.0, lambda p: _scroll_to(p, "#training")),
        (4.0, lambda p: _scroll_to(p, "#results")),
        (4.5, lambda p: _hover(p, "#results .grid-2 .card", 0)),
        (9.0, lambda p: _hover(p, "#results .grid-2 .card", 1)),
        (14.0, lambda p: _scroll_to(p, "#results table", block="center")),
        (19.0, lambda p: _hover(p, "#results table tbody tr", 2)),
        (23.0, lambda p: _scroll_to(p, "#results .grid-3", block="center")),
    ],
    "scene05": [          # Hyper-parameters
        (0.0, lambda p: _scroll_to(p, "#training", block="end")),
        (0.5, lambda p: _hover(p, "#training .card", 0)),
        (8.0, lambda p: _hover(p, "#training .card", 1)),
        (18.0, lambda p: _hover(p, "#training .card", 2)),
    ],
    "scene06": [          # Task explorer
        (0.0, lambda p: _scroll_to(p, "#tasks")),
        (1.0, lambda p: _click(p, '#tasks .filter-btn[data-diff="hard"]')),
        (4.0, lambda p: p.locator("#search").fill("saboteur", timeout=3000)),
        (8.0, lambda p: _click(p, "#task-grid .task-card", 0)),
        (12.0, lambda p: None),
        (16.0, lambda p: p.keyboard.press("Escape")),
    ],
    "scene07": [          # Methodology
        (0.0, lambda p: _scroll_to(p, "#methodology")),
        (5.0, lambda p: _scroll_to(p, "#methodology .mermaid-frame", block="center")),
        (33.0, lambda p: _scroll_to(p, "#methodology .codeblock", block="center")),
    ],
    "scene08": [          # GitHub → Kaggle pipeline (showcase-only fallback)
        (0.0, lambda p: _scroll_to(p, "#pipeline")),
        (8.0, lambda p: _scroll_px(p, 200)),
        (16.0, lambda p: _scroll_px(p, 200)),
        (24.0, lambda p: _scroll_px(p, 200)),
        (32.0, lambda p: _scroll_to(p, "#pipeline", block="end")),
    ],
    "scene09": [          # Production infra (showcase-only fallback)
        (0.0, lambda p: _scroll_to(p, "#infra")),
        (5.0, lambda p: _scroll_to(p, "#infra .mermaid-frame", block="center")),
        (30.0, lambda p: _scroll_to(p, "#infra", block="end")),
    ],
    "scene10": [          # File index
        (0.0, lambda p: _scroll_to(p, "#files")),
        (5.0, lambda p: _hover(p, "#files .file-table tbody tr", 0)),
        (10.0, lambda p: _hover(p, "#files .file-table tbody tr", 1)),
        (15.0, lambda p: _hover(p, "#files .file-table tbody tr", 2)),
    ],
    "scene11": [          # Dual dashboards — best effort, stays on showcase
        (0.0, lambda p: _scroll_to(p, "body", smooth=True, block="start")),
        (1.0, lambda p: _move_mouse(p, W - 200, 60)),
        (3.0, lambda p: None),       # leave room for manual /dashboard/ppo recording
        (18.0, lambda p: None),
    ],
    "scene12": [          # Wrap
        (0.0, lambda p: _scroll_to(p, "body", smooth=True, block="start")),
        (15.0, lambda p: _move_mouse(p, W - 250, 60)),
        (22.0, lambda p: _move_mouse(p, W - 120, 60)),
        (30.0, lambda p: _move_mouse(p, W // 2, H // 2)),
    ],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def probe(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
    ).strip()
    return float(out)

def scene_durations() -> list[tuple[str, float]]:
    items = []
    for i in range(1, 13):
        p = OUT / f"scene{i:02d}.mp3"
        items.append((f"scene{i:02d}", probe(p)))
    return items


CURSOR_JS = r"""
(() => {
  const dot = document.createElement('div');
  dot.id = '__autocursor';
  Object.assign(dot.style, {
    position: 'fixed', zIndex: 2147483647, pointerEvents: 'none',
    width: '24px', height: '24px', borderRadius: '50%',
    background: 'rgba(255,210,80,0.95)',
    boxShadow: '0 0 0 4px rgba(255,210,80,0.35), 0 0 16px rgba(0,0,0,0.5)',
    transform: 'translate(-50%,-50%)', transition: 'transform 80ms linear',
    left: '0px', top: '0px',
  });
  document.body.appendChild(dot);
  document.addEventListener('mousemove', (e) => {
    dot.style.left = e.clientX + 'px';
    dot.style.top  = e.clientY + 'px';
  }, true);
})();
"""


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------

def record(url: str, headed: bool) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright not installed. Run: pip install playwright && playwright install chromium")

    if VIDEO.exists():
        shutil.rmtree(VIDEO)
    VIDEO.mkdir(parents=True, exist_ok=True)

    durations = scene_durations()
    total = sum(d for _, d in durations)
    print(f"\n[record] target total = {total:.1f}s ({total/60:.2f} min) across 12 scenes")
    for n, d in durations:
        print(f"   {n}  {d:5.1f}s")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not headed,
            args=["--hide-scrollbars", "--disable-features=TranslateUI"],
        )
        ctx = browser.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(VIDEO),
            record_video_size={"width": W, "height": H},
            device_scale_factor=1,
        )
        page = ctx.new_page()
        print(f"\n[record] navigating {url}")
        page.goto(url, wait_until="networkidle", timeout=60_000)

        if CURSOR_INJECT:
            page.evaluate(CURSOR_JS)

        # Park mouse centre so the dot exists before scene 1
        page.mouse.move(W // 2, H // 2)
        time.sleep(1.0)   # 1s pre-roll silence — trim later in DaVinci

        elapsed = 0.0
        for name, dur in durations:
            beats = SCENES.get(name, [])
            print(f"\n[scene {name}] dur={dur:.1f}s · {len(beats)} beats")
            scene_start = time.monotonic()
            for rel_t, fn in beats:
                wait_until = scene_start + rel_t
                slack = wait_until - time.monotonic()
                if slack > 0:
                    time.sleep(slack)
                try:
                    fn(page)
                    print(f"   t+{rel_t:5.1f}s  OK")
                except Exception as e:
                    print(f"   t+{rel_t:5.1f}s  FAIL  {e}")
            # Sleep out the remainder of the scene
            remaining = (scene_start + dur) - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            elapsed += dur

        time.sleep(1.5)   # tail pad
        ctx.close()       # <- this is what flushes the .webm to disk
        browser.close()

    webms = sorted(VIDEO.glob("*.webm"))
    if not webms:
        sys.exit("No .webm produced — did Playwright crash?")
    print(f"\n[record] wrote {webms[-1]}")
    return webms[-1]


# ---------------------------------------------------------------------------
# mux
# ---------------------------------------------------------------------------

def concat_audio() -> Path:
    listfile = OUT / "_concat.txt"
    listfile.write_text(
        "\n".join(f"file '{(OUT / f'scene{i:02d}.mp3').as_posix()}'" for i in range(1, 13)),
        encoding="utf-8",
    )
    subprocess.check_call(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(listfile), "-c", "copy", str(CONCAT_A)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    listfile.unlink(missing_ok=True)
    return CONCAT_A


def mux(webm: Path) -> Path:
    if not BGM_SRC.exists():
        sys.exit(f"missing background track: {BGM_SRC} (download from incompetech.com first)")
    print(f"\n[mux] concatenating 12 MP3s -> {CONCAT_A.name}")
    concat_audio()
    voice_dur = probe(CONCAT_A)
    print(f"[mux] voice = {voice_dur:.1f}s · BGM = {probe(BGM_SRC):.1f}s ('Inspired' by Kevin MacLeod, CC-BY 4.0)")
    print(f"[mux] muxing {webm.name} + voice + sidechain-ducked BGM -> {FINAL.name}")
    subprocess.check_call([
        "ffmpeg", "-y",
        "-i", str(webm),
        "-i", str(CONCAT_A),
        "-stream_loop", "-1", "-i", str(BGM_SRC),     # loop BGM in case it's shorter than voice
        "-filter_complex",
        # 1) prep voice: upsample to 48k, stereo, slight loudness normalisation, then split for sidechain + main mix
        "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,dynaudnorm=g=5,volume=1.4,asplit=2[voice_main][voice_sc];"
        # 2) prep BGM: 48k stereo, trimmed to voice length, base level + fade in/out
        f"[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{voice_dur:.2f},asetpts=PTS-STARTPTS,"
        f"volume=0.40,afade=t=in:st=0:d=2,afade=t=out:st={voice_dur-2:.2f}:d=2[bgm_pre];"
        # 3) sidechain-compress BGM by voice envelope so the bed ducks ~10 dB under speech
        "[bgm_pre][voice_sc]sidechaincompress=threshold=0.04:ratio=8:attack=10:release=350:makeup=1[bgm];"
        # 4) mix voice + ducked BGM
        "[voice_main][bgm]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000",
        "-shortest",
        str(FINAL),
    ])
    print(f"[mux] done -> {FINAL}")
    return FINAL


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--no-record", action="store_true", help="skip recording, mux latest .webm")
    ap.add_argument("--no-mux", action="store_true", help="record only, do not mux to mp4")
    args = ap.parse_args()

    if args.no_record:
        webms = sorted(VIDEO.glob("*.webm"))
        if not webms:
            sys.exit("No prior .webm in voice/out/_video/ — run without --no-record first")
        webm = webms[-1]
    else:
        webm = record(args.url, args.headed)

    if not args.no_mux:
        mux(webm)


if __name__ == "__main__":
    main()
