"""Helper that builds Live stock-device chains from the Core Library .adv presets.

Used in production (2026-07, three mix sets that opened in Live 12). Details: native-devices.md (same folder).

Usage (share the ID allocator with the rest of your .als builder):
    from native_device_chain import DeviceBuilder
    b = DeviceBuilder(aid)                       # aid = your IDAlloc, shared with the track builder
    eq  = b.eq8_lowcut(30)                       # HPF 30 Hz 48 dB/oct
    sat = b.saturator(curve=1, drive=8, wet=0.4) # Soft Sine, parallel
    cmp = b.sidechain_comp(src_track_id=8, thresh=0.45, release=120)
    utl = b.bass_mono()
    devices_xml = b.wrap(eq, sat, cmp, utl)      # -> "<Devices>...</Devices>"
    # build_multi_clip_track_xml(..., devices_xml=devices_xml)

Inserting into the MainTrack and setting the fader is done in ElementTree post-processing:
    devs = root.find("./LiveSet/MainTrack/DeviceChain/DeviceChain/Devices")
    devs.append(ET.fromstring(b.limiter(ceiling=-1)))
    tr.find("./DeviceChain/Mixer/Volume/Manual").set("Value", "0.3981071706")  # -8dB
"""
import glob
import gzip
import os
import xml.etree.ElementTree as ET
from pathlib import Path

_CORE_LIBRARY = None


def core_library():
    """Core Library of the installed Live: $ABLETON_CORE_LIBRARY, else the last match of /Applications/Ableton Live 12*.app (Suite, Standard, Intro, Lite).
    Some editions may not ship every preset used here."""
    global _CORE_LIBRARY
    if _CORE_LIBRARY is None:
        env = os.environ.get("ABLETON_CORE_LIBRARY")
        cand = [env] if env else sorted(glob.glob("/Applications/Ableton Live 12*.app/Contents/App-Resources/Core Library"))
        found = [Path(c) for c in cand if Path(c).is_dir()]
        if not found:
            raise SystemExit("Ableton Core Library not found. Install Live 12 or set ABLETON_CORE_LIBRARY to the 'Core Library' folder.")
        _CORE_LIBRARY = found[-1]
    return _CORE_LIBRARY


def _devices_dir():
    return core_library() / "Devices/Audio Effects"


def _defaults_dir():
    return core_library() / "Defaults/Audio Effects"


class DeviceBuilder:
    def __init__(self, aid):
        self.aid = aid          # share one IDAlloc with the rest of the builder (one Pointee namespace)
        self._n = 0             # device index within the chain

    # -- basics ----------------------------------------------------
    def load(self, rel):
        """Take the device element (root[0]) out of an .adv."""
        p = _devices_dir() / rel
        if not p.is_file():
            raise SystemExit(f"preset not found in your Core Library: {p} (this edition of Live may not ship it)")
        return ET.fromstring(gzip.open(p).read())[0]

    def setp(self, dev, param, value):
        e = dev.find(param + "/Manual")
        assert e is not None, f"param not found: {param}"
        e.set("Value", str(value))

    def finish(self, dev):
        """Give the device an Id and renumber AutomationTarget/ModulationTarget/Pointee; return an XML string."""
        dev.set("Id", str(self._n)); self._n += 1
        for e in dev.iter():
            if (e.tag == "AutomationTarget" or e.tag.endswith("ModulationTarget")
                    or e.tag == "Pointee") and "Id" in e.attrib:
                e.set("Id", str(self.aid.next()))
        return ET.tostring(dev, encoding="unicode")

    def wrap(self, *device_strs):
        self._n = 0             # reset for the next track
        return "<Devices>" + "".join(device_strs) + "</Devices>"

    # -- common devices -------------------------------------------
    def eq8_lowcut(self, freq, slope48=True):
        """A single low-cut band. Mode: 0 = LC48, 1 = LC12 (other modes: see native-devices.md)."""
        eq = self.load("EQ Eight/Filter/Cheesy Speaker.adv")
        self.setp(eq, "GlobalGain", 0)
        for i in range(8):
            for ab in ("ParameterA", "ParameterB"):
                p = eq.find(f"Bands.{i}/{ab}")
                p.find("IsOn/Manual").set("Value", "true" if i == 0 else "false")
                p.find("Mode/Manual").set("Value", "0" if slope48 else "1")
                p.find("Freq/Manual").set("Value", str(freq))
                p.find("Gain/Manual").set("Value", "0")
                p.find("Q/Manual").set("Value", "0.7071")
        return self.finish(eq)

    def saturator(self, curve=1, drive=8, wet=0.4, post=-6):
        """curve: 0 = Analog Clip, 1 = Soft Sine. Hi-Quality is not an XML parameter (ask the user to switch it on)."""
        sat = self.load("Saturator/Basic Soft.adv")
        for k, v in {"On": "true", "Type": curve, "PreDrive": drive,
                     "ColorOn": "false", "BaseDrive": 0, "ColorDepth": 0,
                     "PostDrive": post, "DryWet": wet}.items():
            self.setp(sat, k, v)
        return self.finish(sat)

    def clipper(self, drive=0, post=0):
        """Use Analog Clip as a clipper."""
        return self.saturator(curve=0, drive=drive, wet=1, post=post)

    def sidechain_comp(self, src_track_id, thresh=0.45, ratio=4,
                       attack=0.1, release=120, src_name="",
                       key_bell=(55, 1, 6)):
        """Compressor2 with a sidechain. thresh is linear amplitude (0.45 is about -6.9 dB).
        key_bell=(freq, q, gain_db) is the key EQ. Despite the name it is not a bell: SideChainEq_Mode 3 is a low-pass
        (see the table in native-devices.md; corrected 2026-11-11). freq = low-pass frequency, q = Q; gain_db has no effect.
        The default (55, 1, 6) is a 55 Hz low-pass, i.e. a key that reacts to the low end of the kick only. None disables it."""
        comp = self.load("Compressor/Basic Peak Compressor.adv")
        for k, v in {"On": "true", "Threshold": thresh, "Ratio": ratio,
                     "Attack": attack, "Release": release, "Gain": 0,
                     "GainCompensation": "false", "Model": 0, "Knee": 6,
                     "DryWet": 1, "LookAhead": 0,
                     "AutoReleaseControlOnOff": "false"}.items():
            self.setp(comp, k, v)
        if key_bell:
            f, q, g = key_bell
            for k, v in {"SideChainEq_On": "true", "SideChainEq_Mode": 3,
                         "SideChainEq_Freq": f, "SideChainEq_Q": q,
                         "SideChainEq_Gain": g}.items():
                self.setp(comp, k, v)
        sc = comp.find("SideChain")
        sc.find("OnOff/Manual").set("Value", "true")
        r = sc.find("RoutedInput/Routable")
        r.find("Target").set("Value", f"AudioIn/Track.{src_track_id}/TrackOut")
        r.find("UpperDisplayString").set("Value", src_name)
        r.find("LowerDisplayString").set("Value", "Post Mixer")
        return self.finish(comp)

    def bass_mono(self, freq=None):
        """Utility Bass Mono (default 120 Hz)."""
        u = self.load("Utility/Bass Mono.adv")
        self.setp(u, "On", "true")
        if freq is not None:
            self.setp(u, "BassMonoFrequency", freq)
        return self.finish(u)

    def drum_buss(self, drive=0.0, drive_type=2, crunch=0.0,
                  transients=0.5, damp=20000, boom=0.0):
        """drive/crunch: 0..1, transients: -1..+1 (0 = centre)."""
        d = self.load("Drum Buss/Drum Sharpener.adv")
        for k, v in {"On": "true", "EnableCompression": "false",
                     "DriveAmount": drive, "DriveType": drive_type,
                     "CrunchAmount": crunch, "DampingFrequency": damp,
                     "TransientShaping": transients, "BoomAmount": boom,
                     "InputTrim": 1, "OutputGain": 1, "DryWet": 1}.items():
            self.setp(d, k, v)
        return self.finish(d)

    def limiter(self, ceiling=-1.0, gain=0.0):
        l = self.load("Limiter/Low Latency.adv")
        for k, v in {"On": "true", "Ceiling": ceiling, "Gain": gain,
                     "AutoRelease": "true", "Lookahead": 2}.items():
            self.setp(l, k, v)
        return self.finish(l)

    def spectrum(self):
        s = self.load("Spectrum/Master.adv")
        self.setp(s, "On", "true")
        return self.finish(s)

    # -- for DJ mixes (2026-10-10, used by a two-deck DJ-mix set builder) --
    def finish_with_targets(self, dev):
        """Same as finish (Id + renumbering), and also returns {parameter name: AutomationTarget Id} (for automation)."""
        xml = self.finish(dev)
        el = ET.fromstring(xml)
        targets = {ch.tag: int(ch.find("AutomationTarget").get("Id"))
                   for ch in el if ch.find("AutomationTarget") is not None}
        return xml, targets

    def eq_three(self, lo=1.0, mid=1.0, hi=1.0, freq_lo=250.0, freq_hi=2500.0):
        """EQ Three (tag FilterEQ3). Gains are linear: 1.0 = 0 dB, 0.000316 = -70 dB (kill), maximum 1.995 (+6 dB).
        Returns (xml, targets); use targets["GainLo"] etc. as the PointeeId of automation."""
        eq = ET.fromstring(gzip.open(_devices_dir() / "EQ Three/Hi.adv").read())[0]
        for k, v in {"GainLo": lo, "GainMid": mid, "GainHi": hi, "FreqLo": freq_lo, "FreqHi": freq_hi,
                     "LowOn": "true", "MidOn": "true", "HighOn": "true"}.items():
            self.setp(eq, k, v)
        return self.finish_with_targets(eq)

    def delay_synced(self, sixteenth_index=2, feedback=0.45, drywet=0.0, filter_hz=1500.0, filter_bw=6.0, pingpong=True):
        """Delay (Delay.adv from Defaults). Synced to the beat, left/right linked. sixteenth_index is DelayLine_SyncedSixteenthL/R (0 to 7).
        2 was used as a dotted eighth (3/16) (the meaning of the value is not verified on screen in Live). DryWet 0..1, Feedback 0..0.95. Returns (xml, targets)."""
        d = ET.fromstring(gzip.open(_defaults_dir() / "Delay.adv").read())[0]
        for k, v in {"DryWet": drywet, "Feedback": feedback, "DelayLine_Link": "true",
                     "DelayLine_PingPong": "true" if pingpong else "false", "DelayLine_SyncL": "true",
                     "DelayLine_SyncR": "true", "DelayLine_SyncedSixteenthL": sixteenth_index,
                     "DelayLine_SyncedSixteenthR": sixteenth_index, "Filter_On": "true", "Filter_Frequency": filter_hz,
                     "Filter_Bandwidth": filter_bw}.items():
            self.setp(d, k, v)
        return self.finish_with_targets(d)


# -- QA: list members must have Ids (2026-10-10) --------------------------------
# Live refuses a set with "corrupt and cannot be loaded. (Not all list members have Ids. (at line L, column C))" when an element of a list has no Id.
# Device elements in an .adv have no Id, so embedding one without going through finish() causes this.
# The list names were picked from lists whose members always carry an Id in three sets saved by Live 12.4 (0 false positives).
LIST_STRICT = ("Devices", "Tracks", "Envelopes", "Events", "ClipSlotList", "Scenes", "WarpMarkers", "TimeSignatures",
               "Sends", "SendsPre")


def list_ids(root):
    """Return the list members that have no Id as [(parent, child)]. It must be empty. root = ET.fromstring(gzip.open(als).read())."""
    bad = []
    for e in root.iter():
        kids = [k for k in e if k.tag != e.tag]          # the <Envelopes><Envelopes/></Envelopes> wrapper is not counted
        if kids and (e.tag in LIST_STRICT
                     or (e.tag in ("Locators", "AutomationLanes") and kids[0].tag == e.tag[:-1])):
            bad += [(e.tag, k.tag) for k in kids if "Id" not in k.attrib]
    return bad


def db_to_linear(db):
    return 10 ** (db / 20.0)
