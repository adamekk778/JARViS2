"""python -m jarvis.evals [--offline | --live] [--min-score 0.9] [--limit N] [--json]"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import live, offline


def _print(rep: dict) -> None:
    if rep["mode"] == "offline":
        print(f"JARVIS evals (offline): {rep['score'] * 100:.1f} % z {rep['cases']} případů")
        for p in rep["parts"]:
            print(f"  {p['name']}: {p['ok']}/{p['total']} ({p['rate'] * 100:.1f} %)")
            for m in p["misses"][:15]:
                print(f"    - {m}")
    else:
        print(f"JARVIS evals (AI): {rep['cases']} požadavků, nejlepší {rep['best'] or '–'}")
        for p in rep["providers"]:
            print(f"  {p['name']}: {p['ok']}/{p['total']} ({p['rate'] * 100:.1f} %) za {p['seconds']} s")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jarvis.evals")
    ap.add_argument("--offline", action="store_true", help="bez AI (výchozí)")
    ap.add_argument("--live", action="store_true", help="zeptat se nastavených AI")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--voice", metavar="SLOŽKA", help="nahrávky + cases.json → rozpoznání řeči a příkazy")
    a = ap.parse_args(argv)
    if a.voice:
        from .. import config
        from ..voice.stt import Transcriber
        from .voice import run as voice_run

        stt = Transcriber(config.load().voice)
        rep = voice_run(a.voice, stt.transcribe_file)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep["commands_ok"] is None or rep["commands_ok"] >= a.min_score else 1
    if a.live:
        from ..runtime import Runtime

        rep = asyncio.run(live(Runtime(persist_config=False), a.limit))
        score = max((p["rate"] for p in rep["providers"]), default=0.0)
    else:
        rep = offline()
        score = rep["score"]
    print(json.dumps(rep, ensure_ascii=False, indent=1)) if a.json else _print(rep)
    if score < a.min_score:
        print(f"Skóre {score:.3f} je pod hranicí {a.min_score}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
