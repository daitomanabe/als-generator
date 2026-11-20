#!/usr/bin/env python3
"""Build two example Live Sets (4/4 and 13/16) from synthesized one-shots. One command, standard library only.

    python3 examples/make_example.py

Writes to examples/out/:
    Example Project/Samples/Imported/*.wav   five short synthesized samples
    score_4-4.json, score_13-16.json          the inputs for scripts/build_als.py
    Example Project/Example 4-4.als, Example 13-16.als
then runs scripts/check_als.py on both. Needs Ableton Live 12 installed (the stock devices are read from its Core Library); it never starts Live.
"""
import json
import math
import random
import struct
import subprocess
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out"
PROJECT = OUT / "Example Project"
SAMPLES = PROJECT / "Samples" / "Imported"
SR = 44100


def write_wav(name, samples):
    SAMPLES.mkdir(parents=True, exist_ok=True)
    peak = max(1e-9, max(abs(x) for x in samples))
    with wave.open(str(SAMPLES / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(32000 * x / peak)) for x in samples))


def make_samples():
    rnd = random.Random(1)
    n = lambda sec: int(SR * sec)                                           # noqa: E731
    # kick: sine sweeping 140 -> 45 Hz with an exponential decay
    ph, k = 0.0, []
    for i in range(n(0.35)):
        t = i / SR
        ph += 2 * math.pi * (45 + 95 * math.exp(-t * 28)) / SR
        k.append(math.sin(ph) * math.exp(-t * 9))
    write_wav("kick.wav", k)
    # hat: short burst of differentiated noise
    prev, h = 0.0, []
    for i in range(n(0.08)):
        x = rnd.uniform(-1, 1)
        h.append((x - prev) * math.exp(-i / SR * 60))
        prev = x
    write_wav("hat.wav", h)
    # clap: noise with a few quick re-attacks
    c = [rnd.uniform(-1, 1) * (math.exp(-(i / SR % 0.012) * 250) * 0.6 + math.exp(-i / SR * 18)) for i in range(n(0.25))]
    write_wav("clap.wav", c)
    # sub: 55 Hz sine, 1 s
    write_wav("sub.wav", [math.sin(2 * math.pi * 55 * i / SR) * min(1, i / 400) * math.exp(-i / SR * 1.5) for i in range(n(1.0))])
    # pad: A minor triad, 2 s, soft attack
    p = []
    for i in range(n(2.0)):
        t = i / SR
        env = min(1.0, t / 0.4) * min(1.0, (2.0 - t) / 0.4)
        p.append(env * sum(math.sin(2 * math.pi * f * t) for f in (220.0, 261.63, 329.63)))
    write_wav("pad.wav", p)


def track(name, role, clips, volume_db=0.0, pan=0.0, **sends):
    t = dict(name=name, role=role, volume_db=volume_db, pan=pan, clips=clips)
    t.update(sends)
    return t


def clip(sample, beat, length_beats=16, gain_db=0.0):
    return dict(sample=sample, beat=beat, length_beats=length_beats, gain_db=gain_db)


def score_4_4():
    bar = 4.0
    bars = 8
    return dict(
        title="Example 4-4", tempo=120.0, bars=bars, time_signature=[4, 4], samples_dir="examples/out/Example Project/Samples/Imported",
        locators=[dict(beat=0.0, name="Intro"), dict(beat=4 * bar, name="Main")],
        tracks=[
            track("Kick", "kick", [clip("kick.wav", i * bar) for i in range(bars)], volume_db=-3.0),
            track("Hat", "hats", [clip("hat.wav", i * bar + 2.0) for i in range(bars)], volume_db=-9.0, pan=0.2, send_a_db=-12.0),
            track("Clap", "snare", [clip("clap.wav", i * bar) for i in (2, 4, 6)], volume_db=-6.0, send_c_db=-20.0),
            track("Sub", "sub", [clip("sub.wav", i * bar) for i in (0, 4)], volume_db=-6.0),
            track("Pad", "pad", [clip("pad.wav", i * bar) for i in (0, 4)], volume_db=-12.0, send_a_db=-6.0, send_b_db=-18.0),
        ])


def score_13_16():
    bar = 13 / 16 * 4                                                        # 3.25 quarter-note beats
    bars = 6
    return dict(
        title="Example 13-16", tempo=140.0, bars=bars, time_signature=[13, 16], samples_dir="examples/out/Example Project/Samples/Imported",
        locators=[dict(beat=0.0, name="A"), dict(beat=3 * bar, name="B")],
        tracks=[
            track("Kick", "kick", [clip("kick.wav", i * bar) for i in range(bars)], volume_db=-3.0),
            track("Hat", "hats", [clip("hat.wav", i * bar + bar / 2) for i in range(bars)], volume_db=-9.0, send_a_db=-12.0),
            track("Clap", "snare", [clip("clap.wav", i * bar + bar / 4) for i in range(bars)], volume_db=-6.0),
            track("Sub", "sub", [clip("sub.wav", i * bar) for i in (0, 3)], volume_db=-6.0),
            track("Pad", "pad", [clip("pad.wav", i * bar) for i in (0, 3)], volume_db=-12.0, send_b_db=-18.0),
        ])


def main():
    make_samples()
    failed = False
    for sc in (score_4_4(), score_13_16()):
        score_path = OUT / f"score_{sc['title'].split()[-1]}.json"
        score_path.write_text(json.dumps(sc, indent=2))
        als = PROJECT / f"{sc['title']}.als"
        for cmd in ([sys.executable, str(ROOT / "scripts/build_als.py"), str(score_path), "--out", str(als)],
                    [sys.executable, str(ROOT / "scripts/check_als.py"), str(als), str(score_path)]):
            r = subprocess.run(cmd, text=True, capture_output=True)
            print(r.stdout, end="")
            if r.returncode:
                print(r.stderr, end="")
                failed = True
    print("FAILED" if failed else f"OK: open the .als files in {PROJECT} with Live (save your current set first).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
