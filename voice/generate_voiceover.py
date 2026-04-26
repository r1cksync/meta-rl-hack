"""Generate edge-tts MP3s for all scene*.txt files in this directory.

Usage:
    python voice/generate_voiceover.py
    python voice/generate_voiceover.py --voice en-US-AriaNeural
    python voice/generate_voiceover.py --rate -10% --pitch -2Hz

Free, offline-capable (just needs internet for the first call), zero account.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import edge_tts

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


async def synth(text: str, voice: str, rate: str, pitch: str, target: Path) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(target))


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--voice", default="en-US-AndrewMultilingualNeural",
                   help=("Try (most natural first): "
                         "en-US-AndrewMultilingualNeural, en-US-BrianMultilingualNeural, "
                         "en-US-AvaMultilingualNeural, en-US-EmmaMultilingualNeural, "
                         "en-US-GuyNeural (older, more robotic)"))
    p.add_argument("--rate", default="-4%", help="Speech rate, e.g. -10%% or +5%%")
    p.add_argument("--pitch", default="+0Hz", help="Pitch shift, e.g. -2Hz, +0Hz")
    p.add_argument("--only", default=None, help="Only generate this scene (e.g. scene01)")
    args = p.parse_args()

    OUT.mkdir(exist_ok=True)
    txts = sorted(HERE.glob("scene*.txt"))
    if args.only:
        txts = [t for t in txts if t.stem == args.only]
    if not txts:
        print("No scene*.txt found", file=sys.stderr)
        return 1

    for txt in txts:
        text = txt.read_text(encoding="utf-8").strip()
        target = OUT / f"{txt.stem}.mp3"
        print(f"-> {target.name}  ({len(text):4d} chars)  voice={args.voice}")
        await synth(text, args.voice, args.rate, args.pitch, target)
    print(f"\nDone. {len(txts)} files in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
