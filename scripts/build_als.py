#!/usr/bin/env python3
# score.json -> Ableton Live 12 Set (.als). The sets this script wrote opened in Live 12.4.16 (verified in a production pipeline, 2026-11).
# Input score.json: {title, tempo, bars, samples_dir, [time_signature:[n,d]], [locators], tracks:[{name, role, [volume_db], [pan],
#   [send_a_db], [send_b_db], [send_c_db], clips:[{sample, beat, length_beats, [gain_db]}]}]}.
#   ROOT = the repository folder (a relative samples_dir and the default output path hang off it; an absolute samples_dir also works).
# The role tables (ROLE_COLOR / ROLE_HP / ROLE_SC) and the return chains are tuned to one piece: edit them for yours, and run check_als.py after.
"""score.json -> Ableton Live 12 Set (.als): audio tracks with one-shot Arrangement clips, 3 returns, master chain.

    python3 scripts/build_als.py score.json [--out PATH.als]

Built on pieces that were opened in Live 12 before (a DJ-mix set builder, a loop-arrangement builder and references/native_device_chain.py),
copied here so this script stands alone.

Clips: Arrangement AudioClip, WarpMode Beats, warp markers at the file's own speed (BeatTime = SecTime * tempo / 60, three
points), loop off, 5 ms fade-out. Standard devices are taken from the Core Library .adv files of your own Live installation, Ids and
Pointee namespace renumbered. Standard library only.

Core Library location: the ABLETON_CORE_LIBRARY environment variable if set, otherwise the last match (sorted by name) of
/Applications/Ableton Live 12*.app/Contents/App-Resources/Core Library (Suite, Standard, Intro or Lite). Some editions may not ship
every preset used here (Reverb Dark Hall, Redux New Mirage, ...); the build stops with a clear error if a preset is missing.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CORE: Path | None = None


def core_library() -> Path:
    """Core Library of the installed Live: $ABLETON_CORE_LIBRARY, else a glob over /Applications/Ableton Live 12*.app (last match in name order)."""
    global _CORE
    if _CORE is None:
        env = os.environ.get("ABLETON_CORE_LIBRARY")
        if env:
            cand = [env]
        else:
            cand = sorted(glob.glob("/Applications/Ableton Live 12*.app/Contents/App-Resources/Core Library"))
        found = [Path(c) for c in cand if Path(c).is_dir()]
        if not found:
            raise SystemExit("Ableton Core Library not found. Install Live 12 or set ABLETON_CORE_LIBRARY to the 'Core Library' folder "
                             "(it holds Devices/ and Defaults/).")
        _CORE = found[-1]
    return _CORE


def _dev() -> Path:
    return core_library() / "Devices/Audio Effects"


def _defaults() -> Path:
    return core_library() / "Defaults/Audio Effects"


REVERB_PRESET = "Reverb/Hall/Dark Hall.adv"
REDUX_PRESET = "Redux/New Mirage.adv"
KILL = 0.0003162277571          # -70 dB: Live's minimum for volume and sends
FADE_OUT_SEC = 0.005

# role -> colour index / high-pass frequency (Hz) / sidechain compressor settings. Edit to suit your piece.
ROLE_COLOR = dict(kick=12, snare=13, hats=13, perc=13, foley=4, fx=4, texture=4, stutter=2, sub=24, pad=18, bell=18, vox=11,
                  strike=8, clack=15, tick=22, bass=26, ground=24, field=18, pulse=1, line=11, shadow=69)
ROLE_HP = dict(snare=150, hats=500, perc=250, foley=300, vox=220, bell=300, fx=100, texture=250, stutter=200, clack=150, tick=1500, field=100, pulse=300, line=200, shadow=200)
ROLE_SC = dict(bass=dict(ratio=2, threshold=0.5, attack=1, release=60),
               sub=dict(ratio=4, threshold=0.25, attack=1, release=120),
               pad=dict(ratio=2, threshold=0.35, attack=5, release=200))
PAD_HP = 160


class IDAlloc:
    def __init__(self, start):
        self._next = start

    def next(self):
        v = self._next
        self._next += 1
        return v

    def peek(self):
        return self._next


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def g(v):
    return f"{v:.12g}"


def db_lin(db):
    return 10 ** (db / 20.0)


# --------------------------------------------------------------------------- WAV
def wav_info(path: Path) -> dict:
    """frames / rate / channels from a RIFF WAV (own parser: handles 24 bit and WAVE_FORMAT_EXTENSIBLE)."""
    b = path.read_bytes()
    if b[:4] != b"RIFF" or b[8:12] != b"WAVE":
        raise ValueError(f"not a WAV: {path}")
    pos, fmt, data = 12, None, None
    while pos + 8 <= len(b):
        cid, size = b[pos:pos + 4], struct.unpack("<I", b[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", b[body:body + 16])
        elif cid == b"data":
            data = min(size, len(b) - body)
            break
        pos = body + size + (size & 1)
    if fmt is None or data is None:
        raise ValueError(f"WAV without fmt/data: {path}")
    _, ch, sr, _, _, bits = fmt
    return dict(frames=data // (ch * bits // 8), rate=sr, channels=ch, size=len(b), crc=zlib.crc32(b) & 0xFFFF)


# --------------------------------------------------------------------------- generic XML pieces (from the vendored builders)
def xml_on_bool(aid):
    return (f'<On><LomId Value="0"/><Manual Value="true"/><AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
            f'<MidiCCOnOffThresholds><Min Value="64"/><Max Value="127"/></MidiCCOnOffThresholds></On>')


MPE = '<MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/>'


def xml_routing_audio():
    return (f'<AudioInputRouting><Target Value="AudioIn/External/M0"/><UpperDisplayString Value="Ext. In"/><LowerDisplayString Value="1"/>{MPE}</AudioInputRouting>'
            f'<MidiInputRouting><Target Value="MidiIn/External.All/-1"/><UpperDisplayString Value="Ext: All Ins"/><LowerDisplayString Value=""/>{MPE}</MidiInputRouting>'
            f'<AudioOutputRouting><Target Value="AudioOut/Main"/><UpperDisplayString Value="Master"/><LowerDisplayString Value=""/>{MPE}</AudioOutputRouting>'
            f'<MidiOutputRouting><Target Value="MidiOut/None"/><UpperDisplayString Value="None"/><LowerDisplayString Value=""/>{MPE}</MidiOutputRouting>')


def xml_routing_main():
    return (f'<AudioInputRouting><Target Value="AudioIn/External/S0"/><UpperDisplayString Value="Ext. In"/><LowerDisplayString Value="1/2"/>{MPE}</AudioInputRouting>'
            f'<MidiInputRouting><Target Value="MidiIn/External.All/-1"/><UpperDisplayString Value="Ext: All Ins"/><LowerDisplayString Value=""/>{MPE}</MidiInputRouting>'
            f'<AudioOutputRouting><Target Value="AudioOut/External/S0"/><UpperDisplayString Value="Ext. Out"/><LowerDisplayString Value="1/2"/>{MPE}</AudioOutputRouting>'
            f'<MidiOutputRouting><Target Value="MidiOut/None"/><UpperDisplayString Value="None"/><LowerDisplayString Value=""/>{MPE}</MidiOutputRouting>')


def xml_automation_lanes(sel_dev=1, sel_env=0, height=68):
    return (f'<AutomationLanes><AutomationLanes><AutomationLane Id="0"><SelectedDevice Value="{sel_dev}"/><SelectedEnvelope Value="{sel_env}"/>'
            f'<IsContentSelectedInDocument Value="false"/><LaneHeight Value="{height}"/></AutomationLane></AutomationLanes>'
            f'<AreAdditionalAutomationLanesFolded Value="false"/></AutomationLanes>')


def xml_device_header(aid, pointee_id):
    return (f'<LomId Value="0"/><LomIdView Value="0"/><IsExpanded Value="true"/><BreakoutIsExpanded Value="false"/>{xml_on_bool(aid)}'
            f'<ModulationSourceCount Value="0"/><ParametersListWrapper LomId="0"/><Pointee Id="{pointee_id}"/>'
            f'<LastSelectedTimeableIndex Value="0"/><LastSelectedClipEnvelopeIndex Value="0"/><LastPresetRef><Value/></LastPresetRef>'
            f'<LockedScripts/><IsFolded Value="false"/><ShouldShowPresetName Value="false"/><UserName Value=""/><Annotation Value=""/>'
            f'<SourceContext><Value/></SourceContext><MpePitchBendUsesTuning Value="true"/><ViewData Value="{{}}" />')


def xml_speaker(aid):
    return (f'<Speaker><LomId Value="0"/><Manual Value="true"/><AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
            f'<MidiCCOnOffThresholds><Min Value="64"/><Max Value="127"/></MidiCCOnOffThresholds></Speaker>')


def xml_param(name, value, lo, hi, aid, has_mod=False):
    s = (f'<{name}><LomId Value="0"/><Manual Value="{value}"/><MidiControllerRange><Min Value="{lo}"/><Max Value="{hi}"/></MidiControllerRange>'
         f'<AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>')
    if has_mod:
        s += f'<ModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></ModulationTarget>'
    return s + f'</{name}>'


def xml_sends(aid, values):
    out = ""
    for sid, v in enumerate(values):
        out += (f'<TrackSendHolder Id="{sid}"><Send><LomId Value="0"/><Manual Value="{g(v)}"/>'
                f'<MidiControllerRange><Min Value="0.0003162277571"/><Max Value="1"/></MidiControllerRange>'
                f'<AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
                f'<ModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></ModulationTarget></Send><EnabledByUser Value="true"/></TrackSendHolder>')
    return f"<Sends>{out}</Sends>"


def xml_mixer(aid, pointee_id, volume=1.0, pan=0.0, sends=None):
    sends_xml = xml_sends(aid, sends) if sends is not None else "<Sends/>"
    return (f'<Mixer><LomId Value="0"/><LomIdView Value="0"/><IsExpanded Value="true"/><BreakoutIsExpanded Value="false"/>{xml_on_bool(aid)}'
            f'<ModulationSourceCount Value="0"/><ParametersListWrapper LomId="0"/><Pointee Id="{pointee_id}"/>'
            f'<LastSelectedTimeableIndex Value="0"/><LastSelectedClipEnvelopeIndex Value="0"/><LastPresetRef><Value/></LastPresetRef>'
            f'<LockedScripts/><IsFolded Value="false"/><ShouldShowPresetName Value="false"/><UserName Value=""/><Annotation Value=""/>'
            f'<SourceContext><Value/></SourceContext><MpePitchBendUsesTuning Value="true"/><ViewData Value="{{}}" />'
            f'{sends_xml}{xml_speaker(aid)}<SoloSink Value="false"/><PanMode Value="0"/>'
            f'{xml_param("Pan", g(pan), "-1", "1", aid, True)}'
            f'{xml_param("SplitStereoPanL", "-1", "-1", "1", aid, True)}'
            f'{xml_param("SplitStereoPanR", "1", "-1", "1", aid, True)}'
            f'{xml_param("Volume", g(volume), "0.0003162277571", "1.99526238", aid, True)}'
            f'<ViewStateSessionTrackWidth Value="93"/>'
            f'<CrossFadeState><LomId Value="0"/><Manual Value="1"/><AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
            f'<MidiControllerRange><Min Value="0"/><Max Value="2"/></MidiControllerRange></CrossFadeState><SendsListWrapper LomId="0"/></Mixer>')


def xml_clip_slots(n):
    return "".join(f'<ClipSlot Id="{i}"><LomId Value="0"/><ClipSlot><Value/></ClipSlot><HasStop Value="true"/><NeedRefreeze Value="true"/></ClipSlot>'
                   for i in range(n))


def xml_modulation_targets(aid):
    names = ("Volume", "Transposition", "TransientEnvelope", "GrainSize", "Flux", "SampleOffset", "ComplexProFormants", "ComplexProEnvelope")
    return "".join(f'<{n}ModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></{n}ModulationTarget>' for n in names)


def xml_sequencer_tail():
    return ('<PitchViewScrollPosition Value="-1073741824"/><SampleOffsetModulationScrollPosition Value="-1073741824"/>'
            '<Recorder><IsArmed Value="false"/><TakeCounter Value="1"/></Recorder>')


def xml_audio_sequencer(aid, pointee_id, slots=8):
    return (f'{xml_device_header(aid, pointee_id)}<ClipSlotList>{xml_clip_slots(slots)}</ClipSlotList><MonitoringEnum Value="1"/>'
            f'<KeepRecordMonitoringLatency Value="true"/><Sample><ArrangerAutomation><Events/><AutomationTransformViewState>'
            f'<IsTransformPending Value="false"/><TimeAndValueTransforms/></AutomationTransformViewState></ArrangerAutomation></Sample>'
            f'{xml_modulation_targets(aid)}{xml_sequencer_tail()}')


N_SCENES = 8


# --------------------------------------------------------------------------- standard devices from Core Library .adv
class Devices:
    """Takes devices from .adv files (root[0]), gives each an Id (chain index), renumbers the Pointee namespace from the shared allocator."""

    def __init__(self, aid):
        self.aid = aid
        self.n = 0

    def chain(self, *devs):
        self.n = 0
        return "<Devices>" + "".join(devs) + "</Devices>"

    @staticmethod
    def load(path):
        if not Path(path).is_file():
            raise SystemExit(f"preset not found in your Core Library: {path} (this edition of Live may not ship it)")
        return ET.fromstring(gzip.open(path).read())[0]

    @staticmethod
    def setp(dev, name, value):
        e = dev.find(name + "/Manual")
        assert e is not None, f"parameter not found: {dev.tag}/{name}"
        e.set("Value", ("true" if value else "false") if isinstance(value, bool) else g(value) if isinstance(value, float) else str(value))

    def finish(self, dev):
        dev.set("Id", str(self.n))
        self.n += 1
        for e in dev.iter():
            if "Id" in e.attrib and (e.tag in ("AutomationTarget", "Pointee") or e.tag.endswith("ModulationTarget")):
                e.set("Id", str(self.aid.next()))
        lp = dev.find("LastPresetRef")
        if lp is not None:
            for ch in list(lp):
                lp.remove(ch)
            ET.SubElement(lp, "Value")
        return ET.tostring(dev, encoding="unicode")

    def eq8_highpass(self, freq, slope48=False):
        """One low-cut band (Eq8 band mode 0 = Low Cut 48 dB/oct, 1 = Low Cut 12 dB/oct), the other seven bands off."""
        eq = self.load(_dev() / "EQ Eight/Filter/Cheesy Speaker.adv")
        self.setp(eq, "GlobalGain", 0.0)
        for i in range(8):
            for ab in ("ParameterA", "ParameterB"):
                p = eq.find(f"Bands.{i}/{ab}")
                p.find("IsOn/Manual").set("Value", "true" if i == 0 else "false")
                p.find("Mode/Manual").set("Value", "0" if slope48 else "1")
                p.find("Freq/Manual").set("Value", g(float(freq)))
                p.find("Gain/Manual").set("Value", "0")
                p.find("Q/Manual").set("Value", "0.7071")
        return self.finish(eq)

    def sidechain_comp(self, src_track_id, ratio, threshold, attack, release, src_name):
        """Compressor2 keyed from another track's post-mixer output (Threshold is linear amplitude, Attack/Release in ms)."""
        c = self.load(_dev() / "Compressor/Basic Peak Compressor.adv")
        for k, v in dict(On=True, Threshold=float(threshold), Ratio=float(ratio), Attack=float(attack), Release=float(release), Gain=0.0,
                         GainCompensation=False, Model=0, DryWet=1.0, AutoReleaseControlOnOff=False, SideChainEq_On=False).items():
            self.setp(c, k, v)
        sc = c.find("SideChain")
        sc.find("OnOff/Manual").set("Value", "true")
        r = sc.find("RoutedInput/Routable")
        r.find("Target").set("Value", f"AudioIn/Track.{src_track_id}/TrackOut")
        r.find("UpperDisplayString").set("Value", src_name)
        r.find("LowerDisplayString").set("Value", "Post Mixer")
        return self.finish(c)

    def reverb(self):
        """Core Library Reverb 'Dark Hall' for a return: only MixDirect (the preset's 1 = fully wet, as in 63 of the 80 reverb presets) and DecayTime
        (ms, range 200-60000) are written; the rest stays as the preset."""
        r = self.load(_dev() / REVERB_PRESET)
        self.setp(r, "MixDirect", 1.0)
        self.setp(r, "DecayTime", 5500.0)
        return self.finish(r)

    def delay(self):
        """Delay: synced 3/16 (SyncedSixteenth index 2), Feedback 0.55, PingPong on, Filter on, DryWet 1."""
        d = self.load(_defaults() / "Delay.adv")
        for k, v in dict(DryWet=1.0, Feedback=0.55, DelayLine_Link=True, DelayLine_PingPong=True, DelayLine_SyncL=True, DelayLine_SyncR=True,
                         DelayLine_SyncedSixteenthL=2, DelayLine_SyncedSixteenthR=2, Filter_On=True).items():
            self.setp(d, k, v)
        return self.finish(d)

    def saturator(self, pre_drive, post_drive):
        """Saturator Type 0 (Analog Clip), DryWet 1, colour section off."""
        sa = self.load(_dev() / "Saturator/Basic Soft.adv")
        for k, v in dict(On=True, Type=0, PreDrive=float(pre_drive), PostDrive=float(post_drive), DryWet=1.0, ColorOn=False, BaseDrive=0.0, ColorDepth=0.0).items():
            self.setp(sa, k, v)
        return self.finish(sa)

    def redux(self):
        """Core Library Redux preset, untouched (Redux2 tag)."""
        return self.finish(self.load(_dev() / REDUX_PRESET))

    def bass_mono(self, freq=120.0):
        u = self.load(_dev() / "Utility/Bass Mono.adv")
        self.setp(u, "On", True)
        self.setp(u, "BassMono", True)
        self.setp(u, "BassMonoFrequency", float(freq))
        return self.finish(u)

    def limiter(self, ceiling=-1.0, gain=0.0):
        li = self.load(_defaults() / "Limiter.adv")
        for k, v in dict(On=True, Gain=float(gain), Ceiling=float(ceiling), AutoRelease=True).items():
            self.setp(li, k, v)
        return self.finish(li)


# --------------------------------------------------------------------------- clips and tracks
NO_DEVICES = ("kick", "ground", "strike")   # roles with no Eq8 (kick gets a Saturator when it exists)


def ts_code(num: int, den: int) -> int:
    """Live's time-signature code: (numerator - 1) + 99 * i, i = 0..4 for denominators 1, 2, 4, 8, 16 (4/4 = 201, 13/16 = 408, max 494)."""
    if den not in (1, 2, 4, 8, 16) or not 1 <= num <= 99:
        raise SystemExit(f"unsupported time signature {num}/{den} (numerator 1-99, denominator 1/2/4/8/16)")
    return (num - 1) + 99 * (1, 2, 4, 8, 16).index(den)


def clip_xml(clip_id, name, rel_path, abs_path, start_beat, played_beats, file_beats, info, tempo, color, gain_db, fade_out_sec=FADE_OUT_SEC, ts=(4, 4)):
    """Arrangement AudioClip: Beats warp at the file's own speed (3 warp markers), loop off, 5 ms fade-out, GrooveId -1."""
    dur = info["frames"] / info["rate"]
    end_beat = start_beat + played_beats
    fade = min(fade_out_sec, played_beats * 60.0 / tempo)
    wm2_beat = file_beats + 1 / 32
    wm2_sec = dur + (1 / 32) * 60.0 / tempo
    return (
        f'<AudioClip Id="{clip_id}" Time="{g(start_beat)}"><LomId Value="0"/><LomIdView Value="0"/>'
        f'<CurrentStart Value="{g(start_beat)}"/><CurrentEnd Value="{g(end_beat)}"/>'
        f'<Loop><LoopStart Value="0"/><LoopEnd Value="{g(played_beats)}"/><StartRelative Value="0"/><LoopOn Value="false"/>'
        f'<OutMarker Value="{g(played_beats)}"/><HiddenLoopStart Value="0"/><HiddenLoopEnd Value="{g(played_beats)}"/></Loop>'
        f'<Name Value="{esc(name)}"/><Annotation Value=""/><Color Value="{color}"/><LaunchMode Value="0"/><LaunchQuantisation Value="0"/>'
        f'<TimeSignature><TimeSignatures><RemoteableTimeSignature Id="0"><Numerator Value="{ts[0]}"/><Denominator Value="{ts[1]}"/><Time Value="0"/>'
        f'</RemoteableTimeSignature></TimeSignatures></TimeSignature>'
        f'<Envelopes><Envelopes/></Envelopes>'
        f'<ScrollerTimePreserver><LeftTime Value="0"/><RightTime Value="{g(played_beats)}"/></ScrollerTimePreserver>'
        f'<TimeSelection><AnchorTime Value="0"/><OtherTime Value="0"/></TimeSelection><Legato Value="false"/><Ram Value="false"/>'
        f'<GrooveSettings><GrooveId Value="-1"/></GrooveSettings><Disabled Value="false"/><VelocityAmount Value="0"/>'
        f'<FollowAction><FollowTime Value="4"/><IsLinked Value="true"/><LoopIterations Value="1"/><FollowActionA Value="4"/><FollowActionB Value="0"/>'
        f'<FollowChanceA Value="100"/><FollowChanceB Value="0"/><JumpIndexA Value="1"/><JumpIndexB Value="1"/><FollowActionEnabled Value="false"/></FollowAction>'
        f'<Grid><FixedNumerator Value="1"/><FixedDenominator Value="16"/><GridIntervalPixel Value="20"/><Ntoles Value="2"/><SnapToGrid Value="true"/><Fixed Value="false"/></Grid>'
        f'<FreezeStart Value="0"/><FreezeEnd Value="0"/><IsWarped Value="true"/><TakeId Value="-1"/><IsInKey Value="true"/>'
        f'<ScaleInformation><Root Value="0"/><Name Value="0"/></ScaleInformation>'
        f'<SampleRef><FileRef><RelativePathType Value="3"/><RelativePath Value="{esc(rel_path)}"/><Path Value="{esc(abs_path)}"/><Type Value="2"/>'
        f'<LivePackName Value=""/><LivePackId Value=""/><OriginalFileSize Value="{info["size"]}"/><OriginalCrc Value="{info["crc"]}"/><SourceHint Value=""/></FileRef>'
        f'<LastModDate Value="1772765797"/><SourceContext/><SampleUsageHint Value="0"/><DefaultDuration Value="{info["frames"]}"/>'
        f'<DefaultSampleRate Value="{info["rate"]}"/><SamplesToAutoWarp Value="0"/></SampleRef>'
        f'<Onsets><UserOnsets/><HasUserOnsets Value="false"/></Onsets><WarpMode Value="0"/>'
        f'<GranularityTones Value="30"/><GranularityTexture Value="65"/><FluctuationTexture Value="25"/><TransientResolution Value="6"/>'
        f'<TransientLoopMode Value="2"/><TransientEnvelope Value="100"/><ComplexProFormants Value="100"/><ComplexProEnvelope Value="128"/>'
        f'<Sync Value="true"/><HiQ Value="true"/><Fade Value="true"/>'
        f'<Fades><FadeInLength Value="0"/><FadeOutLength Value="{g(fade)}"/><ClipFadesAreInitialized Value="true"/><CrossfadeInState Value="0"/>'
        f'<FadeInCurveSkew Value="0"/><FadeInCurveSlope Value="0"/><FadeOutCurveSkew Value="0"/><FadeOutCurveSlope Value="0"/>'
        f'<IsDefaultFadeIn Value="false"/><IsDefaultFadeOut Value="false"/></Fades>'
        f'<PitchCoarse Value="0"/><PitchFine Value="0"/><SampleVolume Value="{g(db_lin(gain_db))}"/>'
        f'<WarpMarkers><WarpMarker Id="0" SecTime="0" BeatTime="0"/><WarpMarker Id="1" SecTime="{g(dur)}" BeatTime="{g(file_beats)}"/>'
        f'<WarpMarker Id="2" SecTime="{g(wm2_sec)}" BeatTime="{g(wm2_beat)}"/></WarpMarkers>'
        f'<SavedWarpMarkersForStretched/><MarkersGenerated Value="false"/><IsSongTempoLeader Value="false"/></AudioClip>')


def audio_track_xml(track_id, name, color, clips, aid, pid, devices_xml, volume, pan, sends):
    mix_p, seq_p, frz_p = pid.next(), pid.next(), pid.next()
    return (
        f'<AudioTrack Id="{track_id}" SelectedToolPanel="3" SelectedTransformationName="" SelectedGeneratorName="">'
        f'<LomId Value="0"/><LomIdView Value="0"/><IsContentSelectedInDocument Value="false"/><PreferredContentViewMode Value="0"/>'
        f'<TrackDelay><Value Value="0"/><IsValueSampleBased Value="false"/></TrackDelay>'
        f'<Name><EffectiveName Value="{esc(name)}"/><UserName Value="{esc(name)}"/><Annotation Value=""/><MemorizedFirstClipName Value=""/></Name>'
        f'<Color Value="{color}"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><TrackGroupId Value="-1"/><TrackUnfolded Value="true"/>'
        f'<DevicesListWrapper LomId="0"/><ClipSlotsListWrapper LomId="0"/><ArrangementClipsListWrapper LomId="0"/><TakeLanesListWrapper LomId="0"/>'
        f'<ViewData Value="{{}}" /><TakeLanes><TakeLanes/><AreTakeLanesFolded Value="true"/></TakeLanes><LinkedTrackGroupId Value="-1"/>'
        f'<SavedPlayingSlot Value="-1"/><SavedPlayingOffset Value="0"/><Freeze Value="false"/><NeedArrangerRefreeze Value="true"/><PostProcessFreezeClips Value="0"/>'
        f'<DeviceChain>{xml_automation_lanes()}'
        f'<ClipEnvelopeChooserViewState><SelectedDevice Value="1"/><SelectedEnvelope Value="2"/><PreferModulationVisible Value="false"/></ClipEnvelopeChooserViewState>'
        f'{xml_routing_audio()}{xml_mixer(aid, mix_p, volume, pan, sends)}'
        f'<MainSequencer>{xml_device_header(aid, seq_p)}<ClipSlotList>{xml_clip_slots(N_SCENES)}</ClipSlotList><MonitoringEnum Value="2"/>'
        f'<KeepRecordMonitoringLatency Value="true"/><Sample><ArrangerAutomation><Events>{"".join(clips)}</Events>'
        f'<AutomationTransformViewState><IsTransformPending Value="false"/><TimeAndValueTransforms/></AutomationTransformViewState></ArrangerAutomation></Sample>'
        f'{xml_modulation_targets(aid)}{xml_sequencer_tail()}</MainSequencer>'
        f'<FreezeSequencer>{xml_audio_sequencer(aid, frz_p, N_SCENES)}</FreezeSequencer>'
        f'<DeviceChain>{devices_xml}<SignalModulations/></DeviceChain></DeviceChain><IsTuned Value="true"/></AudioTrack>')


def return_track_xml(track_id, name, color, aid, pid, devices_xml):
    mix_p, frz_p = pid.next(), pid.next()
    return (
        f'<ReturnTrack Id="{track_id}" SelectedToolPanel="7" SelectedTransformationName="" SelectedGeneratorName="">'
        f'<LomId Value="0"/><LomIdView Value="0"/><IsContentSelectedInDocument Value="false"/><PreferredContentViewMode Value="0"/>'
        f'<TrackDelay><Value Value="0"/><IsValueSampleBased Value="false"/></TrackDelay>'
        f'<Name><EffectiveName Value="{esc(name)}"/><UserName Value="{esc(name)}"/><Annotation Value=""/><MemorizedFirstClipName Value=""/></Name>'
        f'<Color Value="{color}"/><AutomationEnvelopes><Envelopes/></AutomationEnvelopes><TrackGroupId Value="-1"/><TrackUnfolded Value="false"/>'
        f'<DevicesListWrapper LomId="0"/><ClipSlotsListWrapper LomId="0"/><ArrangementClipsListWrapper LomId="0"/><TakeLanesListWrapper LomId="0"/>'
        f'<ViewData Value="{{}}" /><TakeLanes><TakeLanes/><AreTakeLanesFolded Value="true"/></TakeLanes><LinkedTrackGroupId Value="-1"/>'
        f'<DeviceChain>{xml_automation_lanes()}'
        f'<ClipEnvelopeChooserViewState><SelectedDevice Value="0"/><SelectedEnvelope Value="0"/><PreferModulationVisible Value="false"/></ClipEnvelopeChooserViewState>'
        f'{xml_routing_audio()}{xml_mixer(aid, mix_p)}<DeviceChain>{devices_xml}<SignalModulations/></DeviceChain>'
        f'<FreezeSequencer>{xml_device_header(aid, frz_p)}<ClipSlotList/><MonitoringEnum Value="1"/><KeepRecordMonitoringLatency Value="true"/>'
        f'<Sample><ArrangerAutomation><Events/><AutomationTransformViewState><IsTransformPending Value="false"/><TimeAndValueTransforms/>'
        f'</AutomationTransformViewState></ArrangerAutomation></Sample>{xml_modulation_targets(aid)}{xml_sequencer_tail()}</FreezeSequencer>'
        f'</DeviceChain></ReturnTrack>')


def main_track_xml(tempo, aid, pid, devices_xml, ts=201):
    mix_p, tempo_a, tempo_m, ts_a = pid.next(), aid.next(), aid.next(), aid.next()
    env = ('<AutomationTransformViewState><IsTransformPending Value="false"/><TimeAndValueTransforms/></AutomationTransformViewState>')
    return (
        f'<MainTrack SelectedToolPanel="7" SelectedTransformationName="" SelectedGeneratorName="">'
        f'<LomId Value="0"/><LomIdView Value="0"/><IsContentSelectedInDocument Value="false"/><PreferredContentViewMode Value="0"/>'
        f'<TrackDelay><Value Value="0"/><IsValueSampleBased Value="false"/></TrackDelay>'
        f'<Name><EffectiveName Value="Main"/><UserName Value=""/><Annotation Value=""/><MemorizedFirstClipName Value=""/></Name><Color Value="6"/>'
        f'<AutomationEnvelopes><Envelopes>'
        f'<AutomationEnvelope Id="0"><EnvelopeTarget><PointeeId Value="{ts_a}"/></EnvelopeTarget><Automation><Events><EnumEvent Id="0" Time="-63072000" Value="{ts}"/></Events>{env}</Automation></AutomationEnvelope>'
        f'<AutomationEnvelope Id="1"><EnvelopeTarget><PointeeId Value="{tempo_a}"/></EnvelopeTarget><Automation><Events><FloatEvent Id="0" Time="-63072000" Value="{g(tempo)}"/></Events>{env}</Automation></AutomationEnvelope>'
        f'</Envelopes></AutomationEnvelopes><TrackGroupId Value="-1"/><TrackUnfolded Value="false"/>'
        f'<DevicesListWrapper LomId="0"/><ClipSlotsListWrapper LomId="0"/><ArrangementClipsListWrapper LomId="0"/><TakeLanesListWrapper LomId="0"/>'
        f'<ViewData Value="{{}}" /><TakeLanes><TakeLanes/><AreTakeLanesFolded Value="true"/></TakeLanes><LinkedTrackGroupId Value="-1"/>'
        f'<DeviceChain>{xml_automation_lanes(1, 4, 85)}'
        f'<ClipEnvelopeChooserViewState><SelectedDevice Value="0"/><SelectedEnvelope Value="0"/><PreferModulationVisible Value="false"/></ClipEnvelopeChooserViewState>'
        f'{xml_routing_main()}'
        f'<Mixer><LomId Value="0"/><LomIdView Value="0"/><IsExpanded Value="true"/><BreakoutIsExpanded Value="false"/>{xml_on_bool(aid)}'
        f'<ModulationSourceCount Value="0"/><ParametersListWrapper LomId="0"/><Pointee Id="{mix_p}"/>'
        f'<LastSelectedTimeableIndex Value="4"/><LastSelectedClipEnvelopeIndex Value="0"/><LastPresetRef><Value/></LastPresetRef><LockedScripts/>'
        f'<IsFolded Value="false"/><ShouldShowPresetName Value="false"/><UserName Value=""/><Annotation Value=""/><SourceContext><Value/></SourceContext>'
        f'<MpePitchBendUsesTuning Value="true"/><ViewData Value="{{}}" /><Sends/>{xml_speaker(aid)}<SoloSink Value="false"/><PanMode Value="0"/>'
        f'{xml_param("Pan", "0", "-1", "1", aid, True)}{xml_param("SplitStereoPanL", "-1", "-1", "1", aid, True)}'
        f'{xml_param("SplitStereoPanR", "1", "-1", "1", aid, True)}{xml_param("Volume", "1", "0.0003162277571", "1.99526238", aid, True)}'
        f'<ViewStateSessionTrackWidth Value="103"/>'
        f'<CrossFadeState><LomId Value="0"/><Manual Value="1"/><AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
        f'<MidiControllerRange><Min Value="0"/><Max Value="2"/></MidiControllerRange></CrossFadeState><SendsListWrapper LomId="0"/>'
        f'<Tempo><LomId Value="0"/><Manual Value="{g(tempo)}"/><MidiControllerRange><Min Value="60"/><Max Value="200"/></MidiControllerRange>'
        f'<AutomationTarget Id="{tempo_a}"><LockEnvelope Value="0"/></AutomationTarget><ModulationTarget Id="{tempo_m}"><LockEnvelope Value="0"/></ModulationTarget></Tempo>'
        f'<TimeSignature><LomId Value="0"/><Manual Value="{ts}"/><AutomationTarget Id="{ts_a}"><LockEnvelope Value="0"/></AutomationTarget>'
        f'<MidiControllerRange><Min Value="0"/><Max Value="494"/></MidiControllerRange></TimeSignature>'
        f'{xml_param("GlobalGrooveAmount", "0", "0", "131.25", aid, True)}{xml_param("CrossFade", "0", "-1", "1", aid, True)}'
        f'<TempoAutomationViewBottom Value="60"/><TempoAutomationViewTop Value="200"/></Mixer>'
        f'<FreezeSequencer><AudioSequencer Id="0">{xml_audio_sequencer(aid, pid.next(), N_SCENES)}</AudioSequencer></FreezeSequencer>'
        f'<DeviceChain>{devices_xml}<SignalModulations/></DeviceChain></DeviceChain></MainTrack>')


def prehear_track_xml(aid, pid):
    mix_p = pid.next()
    return (
        f'<PreHearTrack SelectedToolPanel="7" SelectedTransformationName="" SelectedGeneratorName="">'
        f'<LomId Value="0"/><LomIdView Value="0"/><IsContentSelectedInDocument Value="false"/><PreferredContentViewMode Value="0"/>'
        f'<TrackDelay><Value Value="0"/><IsValueSampleBased Value="false"/></TrackDelay>'
        f'<Name><EffectiveName Value="0-Main"/><UserName Value=""/><Annotation Value=""/><MemorizedFirstClipName Value=""/></Name><Color Value="-1"/>'
        f'<AutomationEnvelopes><Envelopes/></AutomationEnvelopes><TrackGroupId Value="-1"/><TrackUnfolded Value="false"/>'
        f'<DevicesListWrapper LomId="0"/><ClipSlotsListWrapper LomId="0"/><ArrangementClipsListWrapper LomId="0"/><TakeLanesListWrapper LomId="0"/>'
        f'<ViewData Value="{{}}" /><TakeLanes><TakeLanes/><AreTakeLanesFolded Value="true"/></TakeLanes><LinkedTrackGroupId Value="-1"/>'
        f'<DeviceChain>{xml_automation_lanes(0, 0, 85)}'
        f'<ClipEnvelopeChooserViewState><SelectedDevice Value="0"/><SelectedEnvelope Value="0"/><PreferModulationVisible Value="false"/></ClipEnvelopeChooserViewState>'
        f'{xml_routing_main()}'
        f'<Mixer><LomId Value="0"/><LomIdView Value="0"/><IsExpanded Value="true"/><BreakoutIsExpanded Value="false"/>{xml_on_bool(aid)}'
        f'<ModulationSourceCount Value="0"/><ParametersListWrapper LomId="0"/><Pointee Id="{mix_p}"/>'
        f'<LastSelectedTimeableIndex Value="0"/><LastSelectedClipEnvelopeIndex Value="0"/><LastPresetRef><Value/></LastPresetRef><LockedScripts/>'
        f'<IsFolded Value="false"/><ShouldShowPresetName Value="false"/><UserName Value=""/><Annotation Value=""/><SourceContext><Value/></SourceContext>'
        f'<MpePitchBendUsesTuning Value="true"/><ViewData Value="{{}}" /><Sends/>{xml_speaker(aid)}<SoloSink Value="false"/><PanMode Value="0"/>'
        f'{xml_param("Pan", "0", "-1", "1", aid, True)}{xml_param("SplitStereoPanL", "-1", "-1", "1", aid, True)}'
        f'{xml_param("SplitStereoPanR", "1", "-1", "1", aid, True)}{xml_param("Volume", "0.5012149811", "0.0003162277571", "1.99526238", aid, True)}'
        f'<ViewStateSessionTrackWidth Value="74"/>'
        f'<CrossFadeState><LomId Value="0"/><Manual Value="1"/><AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
        f'<MidiControllerRange><Min Value="0"/><Max Value="2"/></MidiControllerRange></CrossFadeState><SendsListWrapper LomId="0"/></Mixer>'
        f'<DeviceChain><Devices/><SignalModulations/></DeviceChain></DeviceChain></PreHearTrack>')


def scenes_xml(tempo):
    return "<Scenes>" + "".join(
        f'<Scene Id="{i}"><FollowAction><FollowTime Value="4"/><IsLinked Value="true"/><LoopIterations Value="1"/><FollowActionA Value="4"/>'
        f'<FollowActionB Value="0"/><FollowChanceA Value="100"/><FollowChanceB Value="0"/><JumpIndexA Value="0"/><JumpIndexB Value="0"/>'
        f'<FollowActionEnabled Value="false"/></FollowAction><Name Value=""/><Annotation Value=""/><Color Value="-1"/><Tempo Value="{g(tempo)}"/>'
        f'<IsTempoEnabled Value="false"/><TimeSignatureId Value="201"/><IsTimeSignatureEnabled Value="false"/><LomId Value="0"/><ClipSlotsListWrapper LomId="0"/></Scene>'
        for i in range(N_SCENES)) + "</Scenes>"


def locators_xml(locs):
    return "<Locators><Locators>" + "".join(
        f'<Locator Id="{i}"><LomId Value="0"/><Time Value="{g(l["beat"])}"/><Name Value="{esc(l["name"])}"/><Annotation Value=""/><IsSongStart Value="false"/></Locator>'
        for i, l in enumerate(locs)) + "</Locators></Locators>"


FOOTER = (
    '<Transport><PhaseNudgeTempo Value="10"/><LoopOn Value="false"/><LoopStart Value="0"/><LoopLength Value="__LOOPLEN__"/><LoopIsSongStart Value="false"/>'
    '<CurrentTime Value="0"/><PunchIn Value="false"/><PunchOut Value="false"/><MetronomeTickDuration Value="0"/><DrawMode Value="false"/></Transport>'
    '<SessionScrollPos X="0" Y="0"/><SelectedBreakpointValue Value="0"/><SignalModulations/><GlobalQuantisation Value="4"/><AutoQuantisation Value="0"/>'
    '<Grid><FixedNumerator Value="1"/><FixedDenominator Value="16"/><GridIntervalPixel Value="20"/><Ntoles Value="2"/><SnapToGrid Value="true"/><Fixed Value="false"/></Grid>'
    '<ScaleInformation><Root Value="0"/><Name Value="0"/></ScaleInformation><InKey Value="false"/><SmpteFormat Value="0"/>'
    '<TimeSelection><AnchorTime Value="0"/><OtherTime Value="0"/></TimeSelection>'
    '<SequencerNavigator><BeatTimeHelper><CurrentZoom Value="0.25"/></BeatTimeHelper><ScrollerPos X="0" Y="0"/><ClientSize X="828" Y="227"/></SequencerNavigator>'
    '<IsContentSplitterOpen Value="true"/><IsExpressionSplitterOpen Value="true"/>'
    '<ExpressionLanes><MidiEditorLaneModel Id="0"><Type Value="5"/><Size Value="41"/><IsMinimized Value="true"/></MidiEditorLaneModel>'
    '<MidiEditorLaneModel Id="1"><Type Value="0"/><Size Value="41"/><IsMinimized Value="false"/></MidiEditorLaneModel>'
    '<MidiEditorLaneModel Id="2"><Type Value="1"/><Size Value="41"/><IsMinimized Value="false"/></MidiEditorLaneModel>'
    '<MidiEditorLaneModel Id="3"><Type Value="2"/><Size Value="41"/><IsMinimized Value="true"/></MidiEditorLaneModel>'
    '<MidiEditorLaneModel Id="4"><Type Value="3"/><Size Value="41"/><IsMinimized Value="true"/></MidiEditorLaneModel></ExpressionLanes>'
    '<ContentLanes><MidiEditorLaneModel Id="0"><Type Value="2"/><Size Value="41"/><IsMinimized Value="false"/></MidiEditorLaneModel>'
    '<MidiEditorLaneModel Id="2"><Type Value="3"/><Size Value="25"/><IsMinimized Value="true"/></MidiEditorLaneModel>'
    '<MidiEditorLaneModel Id="1"><Type Value="4"/><Size Value="25"/><IsMinimized Value="true"/></MidiEditorLaneModel></ContentLanes>'
    '<ViewStateFxSlotCount Value="4"/><ViewStateSessionMixerVolumeSectionHeight Value="120"/><ViewStateArrangerMixerVolumeSectionHeight Value="120"/>'
    '<ShouldSceneTempoAndTimeSignatureBeVisible Value="false"/><WaveformVerticalZoomFactor Value="1"/><IsWaveformVerticalZoomActive Value="true"/>'
    '__LOCATORS__'
    '<DetailClipKeyMidis/><TracksListWrapper LomId="0"/><VisibleTracksListWrapper LomId="0"/><ReturnTracksListWrapper LomId="0"/><ScenesListWrapper LomId="0"/>'
    '<CuePointsListWrapper LomId="0"/><SelectedDocumentViewInMainWindow Value="0"/><Annotation Value=""/><SoloOrPflSavedValue Value="true"/><SoloInPlace Value="true"/>'
    '<CrossfadeCurve Value="2"/><LatencyCompensation Value="2"/><HighlightedTrackIndex Value="0"/>'
    '<GroovePool><LomId Value="0"/><Grooves/><DefaultGrooveId Value="-1"/><GroovesListWrapper LomId="0"/></GroovePool>'
    '<AutomationMode Value="false"/><SnapAutomationToGrid Value="true"/><ArrangementOverdub Value="false"/><ColorSequenceIndex Value="0"/>'
    '<AutoColorPickerForPlayerAndGroupTracks><NextColorIndex Value="0"/></AutoColorPickerForPlayerAndGroupTracks>'
    '<AutoColorPickerForReturnAndMainTracks><NextColorIndex Value="0"/></AutoColorPickerForReturnAndMainTracks><ViewData Value="{}"/>'
    '<ResetNonautomatedMidiControllersOnClipStarts Value="true"/><MidiFoldIn Value="false"/><MidiFoldMode Value="-99"/><MultiClipFocusMode Value="false"/>'
    '<MultiClipLoopBarHeight Value="0"/><MidiPrelisten Value="false"/><LinkedTrackGroups/><NoteSpellingPreference Value="0"/>'
    '<AccidentalSpellingPreference Value="3"/><PreferFlatRootNote Value="false"/><UseWarperLegacyHiQMode Value="false"/>'
    '<VideoWindowRect Top="-2147483648" Left="-2147483648" Bottom="-2147483648" Right="-2147483648"/><ShowVideoWindow Value="true"/><TuningSystems/>'
    '<TrackHeaderWidth Value="93"/><ViewStateMainWindowClipDetailOpen Value="true"/><ViewStateMainWindowHiddenOtherDocViewTypeClipDetailOpen Value="true"/>'
    '<ViewStateMainWindowHiddenOtherDocViewTypeDeviceDetailOpen Value="false"/><ViewStateMainWindowDeviceDetailOpen Value="false"/>'
    '<ViewStateSecondWindowClipDetailOpen Value="false"/><ViewStateSecondWindowDeviceDetailOpen Value="true"/>'
    '<ViewStates><MixerInArrangement Value="0"/><ArrangerMixerIO Value="1"/><ArrangerMixerSends Value="1"/><ArrangerMixerReturns Value="1"/>'
    '<ArrangerMixerVolume Value="1"/><ArrangerMixerTrackOptions Value="0"/><ArrangerMixerCrossFade Value="0"/><ArrangerMixerTrackPerformanceImpactMeter Value="0"/>'
    '<MixerInSession Value="1"/><SessionIO Value="1"/><SessionSends Value="1"/><SessionReturns Value="1"/><SessionVolume Value="1"/><SessionTrackOptions Value="0"/>'
    '<SessionCrossFade Value="0"/><SessionTrackPerformanceImpactMeter Value="0"/><SessionShowOverView Value="0"/>'
    '<ArrangerIO Value="1"/><ArrangerReturns Value="1"/><ArrangerVolume Value="1"/><ArrangerTrackOptions Value="0"/><ArrangerShowOverView Value="1"/></ViewStates>')


# --------------------------------------------------------------------------- build
def build(score: dict, out: Path) -> dict:
    tempo = float(score["tempo"])
    bars = int(score["bars"])
    samples_dir = ROOT / score["samples_dir"]
    tracks = score["tracks"]
    names = [t["name"] for t in tracks]
    if len(set(names)) != len(names):
        raise SystemExit("track names are not unique")

    infos: dict[str, dict] = {}

    def info(sample: str) -> dict:
        if sample not in infos:
            p = samples_dir / sample
            if not p.is_file():
                raise SystemExit(f"sample missing: {p}")
            infos[sample] = wav_info(p)
        return infos[sample]

    aid, pid = IDAlloc(1), IDAlloc(2_000_000)
    dev = Devices(aid)
    track_ids = {t["name"]: 8 + i for i, t in enumerate(tracks)}
    tsig = tuple(int(x) for x in score.get("time_signature", [4, 4]))
    ts_code(*tsig)
    known = set(ROLE_COLOR)
    unknown = sorted({t["role"] for t in tracks} - known)
    if unknown:
        raise SystemExit(f"unknown role(s): {unknown}")
    kicks = [t for t in tracks if t["role"] == "kick"]
    strikes = [t for t in tracks if t["role"] == "strike"]
    kick = kicks[0] if kicks else strikes[0] if strikes else None      # sidechain source: first kick, else first strike

    track_xml, n_clips = [], 0
    for i, t in enumerate(tracks):
        role, tid = t["role"], 8 + i
        color = ROLE_COLOR.get(role, 4)
        clips = []
        ordered = sorted(t["clips"], key=lambda c: c["beat"])
        for j, c in enumerate(ordered):
            inf = info(c["sample"])
            file_beats = inf["frames"] / inf["rate"] * tempo / 60.0
            played = min(float(c["length_beats"]), file_beats)
            stem = Path(c["sample"]).stem
            # a texture loop that runs straight into the next clip is seamless: no fade, or every join would dip
            nxt = ordered[j + 1] if j + 1 < len(ordered) else None
            seamless = role == "texture" and nxt is not None and abs(float(nxt["beat"]) - (float(c["beat"]) + played)) < 1e-3
            clips.append(clip_xml(j, stem, f"Samples/Imported/{c['sample']}", str((samples_dir / c["sample"]).resolve()), float(c["beat"]), played,
                                  file_beats, inf, tempo, color, float(c.get("gain_db", 0.0)), 0.0 if seamless else FADE_OUT_SEC, tsig))
            n_clips += 1
        devs = []
        if role in ROLE_SC:
            sc = ROLE_SC[role]
            if role == "pad":
                devs.append(dev.eq8_highpass(PAD_HP))
            if kick is not None:
                devs.append(dev.sidechain_comp(track_ids[kick["name"]], sc["ratio"], sc["threshold"], sc["attack"], sc["release"], kick["name"]))
        elif role == "kick":
            devs.append(dev.saturator(6.0, -5.0))
        elif role in ROLE_HP:
            devs.append(dev.eq8_highpass(ROLE_HP[role]))
        devices_xml = dev.chain(*devs) if devs else "<Devices/>"
        dev.n = 0
        vol = min(max(db_lin(float(t.get("volume_db", 0.0))), KILL), 1.99526238)
        sends = [KILL if float(t.get(k, -70.0)) <= -70.0 else min(db_lin(float(t[k])), 1.0) for k in ("send_a_db", "send_b_db", "send_c_db")]
        track_xml.append(audio_track_xml(tid, t["name"], color, clips, aid, pid, devices_xml, vol, float(t.get("pan", 0.0)), sends))

    n = len(tracks)
    ret_a = return_track_xml(8 + n, "A Reverb", 1, aid, pid, dev.chain(dev.reverb(), dev.eq8_highpass(250)))
    ret_b = return_track_xml(9 + n, "B Delay", 14, aid, pid, dev.chain(dev.delay(), dev.eq8_highpass(300)))
    ret_c = return_track_xml(10 + n, "C Dirt", 9, aid, pid, dev.chain(dev.saturator(18.0, -14.0), dev.redux(), dev.eq8_highpass(300)))
    master_devs = dev.chain(dev.eq8_highpass(28, slope48=True), dev.bass_mono(120), dev.limiter(-1.0, 0.0))
    master = main_track_xml(tempo, aid, pid, master_devs, ts_code(*tsig))
    prehear = prehear_track_xml(aid, pid)
    footer = FOOTER.replace("__LOOPLEN__", g(bars * 4.0)).replace("__LOCATORS__", locators_xml(score.get("locators", [])))
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><Ableton MajorVersion="5" MinorVersion="12.0_12300" SchemaChangeCount="1" Creator="als-generator" Revision="">'
           f'<LiveSet><NextPointeeId Value="{max(aid.peek(), pid.peek())}"/><OverwriteProtectionNumber Value="3075"/><LomId Value="0"/><LomIdView Value="0"/>'
           f'<Tracks>{"".join(track_xml)}{ret_a}{ret_b}{ret_c}</Tracks>{master}{prehear}'
           f'<SendsPre><SendPreBool Id="0" Value="false"/><SendPreBool Id="1" Value="false"/><SendPreBool Id="2" Value="false"/></SendsPre>{scenes_xml(tempo)}{footer}</LiveSet></Ableton>')
    ET.fromstring(xml)                                  # well-formed before it is written
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / "Ableton Project Info").mkdir(exist_ok=True)
    with gzip.open(out, "wb") as f:
        f.write(xml.encode("utf-8"))
    return dict(tracks=n, clips=n_clips, samples=len(infos))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("score")
    ap.add_argument("--out", help="output .als (default: <samples_dir>/../../<title>.als)")
    a = ap.parse_args()
    score = json.loads(Path(a.score).read_text())
    title = score.get("title", "Set")
    out = Path(a.out) if a.out else (ROOT / score["samples_dir"]).parent.parent / f"{title}.als"
    r = build(score, out)
    print(f"{out}  tracks {r['tracks']}  clips {r['clips']}  samples {r['samples']}")
    # rel paths are "Samples/Imported/<name>"; they only resolve if the set sits in the project that holds the samples
    probe = next((c["sample"] for t in score["tracks"] for c in t["clips"]), None)
    if probe and not (out.parent / "Samples/Imported" / probe).is_file():
        print(f"WARNING: {out.parent}/Samples/Imported/{probe} does not exist; the RelativePath will not resolve from this location "
              f"(the absolute Path still points at the sample)", file=sys.stderr)


if __name__ == "__main__":
    main()
