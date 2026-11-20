#!/usr/bin/env python3
# QA pair of build_als.py (see its header). Without score.json it runs only the structural gates 1-6 (references/qa-gates.md);
# with it, also the checks that match build_als.py's output.
# Structure only: a PASS is not a Live readback. The roles and return layout it expects are the ones in build_als.py: adjust together.
"""Structural QA for a generated .als (not a Live readback).

    python3 scripts/check_als.py <set.als> [score.json]

Gates 1-6 of the als-generator skill (gzip, XML, NextPointeeId, Pointee namespace, list-member Ids, dangling refs) plus, with a score.json,
tempo / tracks / clips / positions / overlaps / sample refs / returns / master / sidechain / locators. Prints PASS/FAIL per item; exit 1 on any FAIL.
"""
from __future__ import annotations

import gzip
import json
import struct
import sys
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
LIST_STRICT = ("Devices", "Tracks", "Envelopes", "Events", "ClipSlotList", "Scenes", "WarpMarkers", "TimeSignatures", "Sends", "SendsPre")
results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))
    return bool(cond)


def is_pointee_tag(tag):
    return tag in ("Pointee", "AutomationTarget") or tag.endswith("ModulationTarget") or tag.startswith("ControllerTargets.")


def list_ids(root):
    bad = []
    for e in root.iter():
        kids = [k for k in e if k.tag != e.tag]
        if kids and (e.tag in LIST_STRICT or (e.tag in ("Locators", "AutomationLanes") and kids[0].tag == e.tag[:-1])):
            bad += [(e.tag, k.tag) for k in kids if "Id" not in k.attrib]
    return bad


def wav_frames(b: bytes):
    pos = 12
    fmt = None
    while pos + 8 <= len(b):
        cid, size = b[pos:pos + 4], struct.unpack("<I", b[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", b[body:body + 16])
        elif cid == b"data":
            return min(size, len(b) - body) // (fmt[1] * fmt[5] // 8), fmt[2]
        pos = body + size + (size & 1)
    raise ValueError("no data chunk")


def val(e, path):
    x = e.find(path)
    return None if x is None else x.get("Value")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    als = Path(sys.argv[1])
    score = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else None

    # 1 gzip, 2 XML
    try:
        raw = gzip.open(als).read()
        ok(True, "1 gzip readable")
    except Exception as e:                              # noqa: BLE001
        ok(False, f"1 gzip readable: {e}")
        return report()
    try:
        root = ET.fromstring(raw)
        ok(True, "2 XML parses")
    except Exception as e:                              # noqa: BLE001
        ok(False, f"2 XML parses: {e}")
        return report()
    ls = root.find("LiveSet")

    # 3 NextPointeeId, 4 Pointee namespace
    max_id, pids, dups = 0, set(), []
    for e in root.iter():
        for a in ("Id", "LomId", "LomIdView"):
            v = e.attrib.get(a)
            if v is not None and v.lstrip("-").isdigit():
                max_id = max(max_id, int(v))
        if e.tag == "PointeeId":
            max_id = max(max_id, int(e.get("Value")))
        if e.get("Id") is not None and is_pointee_tag(e.tag):
            i = int(e.get("Id"))
            if i in pids:
                dups.append(i)
            pids.add(i)
    nxt = int(ls.find("NextPointeeId").get("Value"))
    ok(nxt > max_id, f"3 NextPointeeId {nxt} > max Id {max_id}")
    ok(not dups, f"4 Pointee namespace unique ({len(pids)} ids, {len(dups)} duplicates)")

    # 5 list members have Ids
    bad = list_ids(root)
    ok(not bad, f"5 list members all have Id ({len(bad)} missing {bad[:3]})")

    # 6 dangling references
    grooves = {x.get("Id") for x in ls.findall("GroovePool/Grooves/Groove")}
    badg = [c.find("GrooveSettings/GrooveId").get("Value") for c in root.iter()
            if c.tag in ("AudioClip", "MidiClip") and c.find("GrooveSettings/GrooveId") is not None
            and c.find("GrooveSettings/GrooveId").get("Value") not in ("-1", *grooves)]
    ok(not badg, f"6a GrooveId all -1 or in pool ({len(badg)} dangling)")
    dang = {p.get("Value") for p in root.iter("PointeeId")} - {str(i) for i in pids}
    ok(not dang, f"6b PointeeId all resolve ({len(dang)} dangling)")
    audio = ls.findall("Tracks/AudioTrack")
    audio_ids = {t.get("Id") for t in audio}
    track_ids = {t.get("Id") for t in ls.find("Tracks")}
    ok(len(track_ids) == len(ls.find("Tracks")), "6c track Ids unique")
    refs = [(r.find("Target").get("Value")) for r in root.iter("Routable") if r.find("Target") is not None]
    bad_t = [t for t in refs if "/Track." in t and t.split("/Track.")[1].split("/")[0] not in track_ids]
    ok(not bad_t, f"6d routing Track.N refs exist ({len(bad_t)} dangling)")
    scenes = len(ls.findall("Scenes/Scene"))
    ok(all(len(t.find("DeviceChain/MainSequencer/ClipSlotList")) == scenes for t in audio), f"6e clip slots per track == scenes ({scenes})")

    # clips: refs exist, size/CRC match
    base = als.parent
    clips_all = ls.findall("Tracks/AudioTrack/DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip")
    miss, mism = [], []
    for c in clips_all:
        rel = c.find("SampleRef/FileRef/RelativePath").get("Value")
        p = base / rel
        if not p.is_file():
            miss.append(rel)
            continue
        b = p.read_bytes()
        if int(c.find("SampleRef/FileRef/OriginalFileSize").get("Value")) != len(b) or \
                int(c.find("SampleRef/FileRef/OriginalCrc").get("Value")) != (zlib.crc32(b) & 0xFFFF):
            mism.append(rel)
        else:
            fr, sr = wav_frames(b)
            if int(c.find("SampleRef/DefaultDuration").get("Value")) != fr or int(c.find("SampleRef/DefaultSampleRate").get("Value")) != sr:
                mism.append(rel + " (duration/rate)")
    ok(not miss, f"RelativePath exists for all {len(clips_all)} clips ({len(set(miss))} missing {sorted(set(miss))[:3]})")
    ok(not mism, f"OriginalFileSize/CRC/DefaultDuration/Rate match ({len(mism)} mismatched {mism[:3]})")
    ok(all(c.find("Loop/LoopOn").get("Value") == "false" and c.find("WarpMode").get("Value") == "0" for c in clips_all), "clips: loop off, WarpMode Beats")

    # returns / master
    rets = ls.findall("Tracks/ReturnTrack")
    ok(len(rets) == 3, f"3 return tracks ({len(rets)})")
    ok(len(ls.findall("SendsPre/SendPreBool")) == 3, "SendsPre has 3 entries")
    dev_tags = lambda tr: [d.tag for d in tr.findall("DeviceChain/DeviceChain/Devices/*")]   # noqa: E731
    if len(rets) == 3:
        ok(dev_tags(rets[0]) == ["Reverb", "Eq8"], f"return A devices {dev_tags(rets[0])}")
        ok(dev_tags(rets[1]) == ["Delay", "Eq8"], f"return B devices {dev_tags(rets[1])}")
        ok(dev_tags(rets[2]) == ["Saturator", "Redux2", "Eq8"], f"return C devices {dev_tags(rets[2])}")
        sa = rets[2].find("DeviceChain/DeviceChain/Devices/Saturator")
        ok(sa is not None and [val(sa, k + "/Manual") for k in ("Type", "PreDrive", "PostDrive", "DryWet", "ColorOn")] == ["0", "18", "-14", "1", "false"],
           "return C Saturator Type 0, PreDrive 18, PostDrive -14, DryWet 1, Color off")
        rv, dl = rets[0].find("DeviceChain/DeviceChain/Devices/Reverb"), rets[1].find("DeviceChain/DeviceChain/Devices/Delay")
        ok(rv is not None and val(rv, "MixDirect/Manual") == "1", "Reverb MixDirect 1 (fully wet)")
        ok(dl is not None and val(dl, "DryWet/Manual") == "1" and val(dl, "DelayLine_PingPong/Manual") == "true", "Delay DryWet 1, PingPong on")
    main = ls.find("MainTrack")
    ok(dev_tags(main) == ["Eq8", "StereoGain", "Limiter"], f"master devices {dev_tags(main)}")
    ok(all(len(t.find("DeviceChain/Mixer/Sends")) == 3 for t in audio), "every audio track has 3 sends")
    ok(not any(t.find("DeviceChain/Mixer/SoloSink").get("Value") != "false" for t in ls.find("Tracks")), "no soloed track")
    for r in rets:
        fz = r.find("DeviceChain/FreezeSequencer/ClipSlotList")
        ok(fz is None or len(fz) == 0, "return FreezeSequencer ClipSlotList empty")

    # sidechain: every Compressor2 points at an existing audio track
    comps = [(t, d) for t in audio for d in t.findall("DeviceChain/DeviceChain/Devices/Compressor2")]
    for t, d in comps:
        tgt = d.find("SideChain/RoutedInput/Routable/Target").get("Value")
        n = tgt.split("/Track.")[1].split("/")[0] if "/Track." in tgt else None
        ok(n in audio_ids and d.find("SideChain/OnOff/Manual").get("Value") == "true", f"sidechain of {t.find('Name/EffectiveName').get('Value')} -> {tgt}")

    # compare with score
    if score:
        tempo = float(score["tempo"])
        num, den = score.get("time_signature", [4, 4])
        code = (num - 1) + 99 * [1, 2, 4, 8, 16].index(den)
        mt = ls.find("MainTrack")
        ok(int(mt.find("DeviceChain/Mixer/TimeSignature/Manual").get("Value")) == code and
           all(int(e.get("Value")) == code for e in mt.findall("AutomationEnvelopes/Envelopes/AutomationEnvelope/Automation/Events/EnumEvent")) and
           all((c.find("TimeSignature/TimeSignatures/RemoteableTimeSignature/Numerator").get("Value"),
                c.find("TimeSignature/TimeSignatures/RemoteableTimeSignature/Denominator").get("Value")) == (str(num), str(den)) for c in clips_all),
           f"time signature {num}/{den} (code {code}) in MainTrack, its envelope and all clips")
        ok(abs(float(ls.find("MainTrack/DeviceChain/Mixer/Tempo/Manual").get("Value")) - tempo) < 1e-6, f"tempo == {tempo}")
        by = {t.find("Name/EffectiveName").get("Value"): t for t in audio}
        ok(list(by) == [t["name"] for t in score["tracks"]], f"audio track names/order match score ({len(by)} tracks)")
        total_ok, nclips, overlaps, bad_pos, bad_sc = True, 0, 0, [], []
        sd = ROOT / score["samples_dir"]
        src = [t for t in score["tracks"] if t["role"] == "kick"][:1] or [t for t in score["tracks"] if t["role"] == "strike"][:1]
        kick_ids = {by[t["name"]].get("Id") for t in src if t["name"] in by}      # sidechain source: first kick, else first strike
        for t in score["tracks"]:
            tr = by.get(t["name"])
            if tr is None:
                total_ok = False
                continue
            cl = tr.findall("DeviceChain/MainSequencer/Sample/ArrangerAutomation/Events/AudioClip")
            exp = sorted(t["clips"], key=lambda c: c["beat"])
            if len(cl) != len(exp):
                total_ok = False
                bad_pos.append(f"{t['name']}: {len(cl)} clips != {len(exp)}")
                continue
            nclips += len(cl)
            cl.sort(key=lambda c: float(c.find("CurrentStart").get("Value")))
            prev_end = -1e9
            for c, e in zip(cl, exp):
                s, en = float(c.find("CurrentStart").get("Value")), float(c.find("CurrentEnd").get("Value"))
                fr, sr = wav_frames((sd / e["sample"]).read_bytes())
                want = min(float(e["length_beats"]), fr / sr * tempo / 60.0)
                if abs(s - e["beat"]) > 1e-6 or abs((en - s) - want) > 1e-6 or Path(c.find("SampleRef/FileRef/RelativePath").get("Value")).name != e["sample"]:
                    bad_pos.append(f"{t['name']}@{e['beat']}")
                if s < prev_end - 1e-9:
                    overlaps += 1
                prev_end = en
            for k, key in (("send_a_db", 0), ("send_b_db", 1), ("send_c_db", 2)):
                sv = float(tr.findall("DeviceChain/Mixer/Sends/TrackSendHolder")[key].find("Send/Manual").get("Value"))
                want_s = 0.0003162277571 if float(t.get(k, -70)) <= -70 else 10 ** (float(t[k]) / 20)
                if abs(sv - min(want_s, 1.0)) > 1e-6:
                    bad_sc.append(f"{t['name']} {k}")
            if t["role"] == "kick":
                ks = tr.findall("DeviceChain/DeviceChain/Devices/Saturator")
                if len(ks) != 1 or [val(ks[0], k + "/Manual") for k in ("Type", "PreDrive", "PostDrive", "DryWet", "ColorOn")] != ["0", "6", "-5", "1", "false"]:
                    bad_sc.append(f"{t['name']} kick Saturator")
            hp = dict(snare=150, hats=500, perc=250, clack=150, tick=1500, foley=300, vox=220, bell=300, fx=100, texture=250, stutter=200, field=100, pulse=300, line=200, shadow=200, pad=160)
            r = t["role"]
            tags = [d.tag for d in tr.findall("DeviceChain/DeviceChain/Devices/*")]
            want = ([] if r in ("ground", "strike") else ["Saturator"] if r == "kick" else (["Compressor2"] if kick_ids else []) if r in ("sub", "bass")
                    else (["Eq8"] + (["Compressor2"] if kick_ids else [])) if r == "pad" else ["Eq8"])
            if tags != want:
                bad_sc.append(f"{t['name']} devices {tags} != {want}")
            elif r in hp and tags and tags[0] == "Eq8":
                f = float(tr.find("DeviceChain/DeviceChain/Devices/Eq8/Bands.0/ParameterA/Freq/Manual").get("Value"))
                if abs(f - hp[r]) > 1e-6:
                    bad_sc.append(f"{t['name']} Eq8 {f} != {hp[r]}")
            if t["role"] in ("sub", "pad", "bass") and kick_ids:
                n_c = [d for d in tr.findall("DeviceChain/DeviceChain/Devices/Compressor2")]
                if len(n_c) != 1 or n_c[0].find("SideChain/RoutedInput/Routable/Target").get("Value").split("/Track.")[1].split("/")[0] not in kick_ids:
                    bad_sc.append(f"{t['name']} sidechain not keyed from the first kick (else first strike) track")
                else:
                    cv = {"sub": (4, 0.25, 1, 120), "pad": (2, 0.35, 5, 200), "bass": (2, 0.5, 1, 60)}[t["role"]]
                    got = tuple(float(val(n_c[0], k + "/Manual")) for k in ("Ratio", "Threshold", "Attack", "Release"))
                    if any(abs(x - y) > 1e-6 for x, y in zip(got, cv)):
                        bad_sc.append(f"{t['name']} compressor {got} != {cv}")
        ok(total_ok and nclips == len(clips_all) == sum(len(t["clips"]) for t in score["tracks"]),
           f"clip count per track and total == score ({nclips}/{len(clips_all)})")
        ok(not bad_pos, f"all clip positions/lengths/samples match score (1e-6 beat) ({len(bad_pos)} off {bad_pos[:3]})")
        ok(overlaps == 0, f"no overlaps within a track ({overlaps})")
        ok(not bad_sc, f"sends and sidechain sources match score ({bad_sc[:3]})")
        loc = ls.findall("Locators/Locators/Locator")
        want_l = score.get("locators", [])
        ok(len(loc) == len(want_l) and all(abs(float(l.find("Time").get("Value")) - w["beat"]) < 1e-6 and l.find("Name").get("Value") == w["name"]
                                           for l, w in zip(loc, want_l)), f"locators == score ({len(loc)})")
    return report()


def report():
    fails = 0
    for good, msg in results:
        print(("PASS  " if good else "FAIL  ") + msg)
        fails += not good
    print(f"{len(results) - fails}/{len(results)} passed")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
