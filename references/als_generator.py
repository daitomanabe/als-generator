#!/usr/bin/env python3
"""
ALS Generator - Ableton Live Set (.als) file generator
Generates valid gzip-compressed XML for Ableton Live 12.x

Based on ALS generation logic that has opened in Live 12.

Usage:
    from als_generator import ALSGenerator
    gen = ALSGenerator(tempo=120)
    t = gen.add_midi_track("Bass", color=7)
    gen.add_clip(t, 0, 4, "Loop", [(60, 0.0, 0.5, 100), (64, 1.0, 0.5, 90)])
    gen.save("output.als")

CLI:
    python3 als_generator.py --json input.json --output output.als
    python3 als_generator.py --demo --output demo.als
"""

import gzip
import json
import sys
from collections import defaultdict


class IDAlloc:
    """Simple incrementing ID allocator."""
    def __init__(self, start):
        self._next = start

    def next(self):
        val = self._next
        self._next += 1
        return val

    def peek(self):
        return self._next


def esc_xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def xml_on_bool(aid):
    return (
        f'<On><LomId Value="0"/><Manual Value="true"/>'
        f'<AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
        f'<MidiCCOnOffThresholds><Min Value="64"/><Max Value="127"/></MidiCCOnOffThresholds></On>'
    )


def xml_routing():
    return (
        '<AudioInputRouting><Target Value="AudioIn/External/S0"/><UpperDisplayString Value="Ext. In"/><LowerDisplayString Value="1/2"/><MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/></AudioInputRouting>'
        '<MidiInputRouting><Target Value="MidiIn/External.All/-1"/><UpperDisplayString Value="Ext: All Ins"/><LowerDisplayString Value=""/><MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/></MidiInputRouting>'
        '<AudioOutputRouting><Target Value="AudioOut/Main"/><UpperDisplayString Value="Master"/><LowerDisplayString Value=""/><MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/></AudioOutputRouting>'
        '<MidiOutputRouting><Target Value="MidiOut/None"/><UpperDisplayString Value="None"/><LowerDisplayString Value=""/><MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/></MidiOutputRouting>'
    )


def xml_routing_main():
    return (
        '<AudioInputRouting><Target Value="AudioIn/External/S0"/><UpperDisplayString Value="Ext. In"/><LowerDisplayString Value="1/2"/><MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/></AudioInputRouting>'
        '<MidiInputRouting><Target Value="MidiIn/External.All/-1"/><UpperDisplayString Value="Ext: All Ins"/><LowerDisplayString Value=""/><MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/></MidiInputRouting>'
        '<AudioOutputRouting><Target Value="AudioOut/External/S0"/><UpperDisplayString Value="Ext. Out"/><LowerDisplayString Value="1/2"/><MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/></AudioOutputRouting>'
        '<MidiOutputRouting><Target Value="MidiOut/None"/><UpperDisplayString Value="None"/><LowerDisplayString Value=""/><MpeSettings><ZoneType Value="0"/><FirstNoteChannel Value="1"/><LastNoteChannel Value="15"/></MpeSettings><MpePitchBendUsesTuning Value="true"/></MidiOutputRouting>'
    )


def xml_clip_slot_list():
    slots = "".join(
        f'<ClipSlot Id="{i}"><LomId Value="0"/><ClipSlot><Value/></ClipSlot>'
        f'<HasStop Value="true"/><NeedRefreeze Value="true"/></ClipSlot>'
        for i in range(8)
    )
    return f"<ClipSlotList>{slots}</ClipSlotList>"


def xml_automation_lanes():
    return (
        '<AutomationLanes><AutomationLanes><AutomationLane Id="0">'
        '<SelectedDevice Value="1"/><SelectedEnvelope Value="0"/>'
        '<IsContentSelectedInDocument Value="false"/><LaneHeight Value="68"/>'
        '</AutomationLane></AutomationLanes>'
        '<AreAdditionalAutomationLanesFolded Value="false"/></AutomationLanes>'
    )


def xml_device_header(aid, pointee_id):
    return (
        f'<LomId Value="0"/><LomIdView Value="0"/><IsExpanded Value="true"/><BreakoutIsExpanded Value="false"/>'
        f'{xml_on_bool(aid)}'
        f'<ModulationSourceCount Value="0"/><ParametersListWrapper LomId="0"/>'
        f'<Pointee Id="{pointee_id}"/>'
        f'<LastSelectedTimeableIndex Value="0"/><LastSelectedClipEnvelopeIndex Value="0"/>'
        f'<LastPresetRef><Value/></LastPresetRef>'
        f'<LockedScripts/>'
        f'<IsFolded Value="false"/><ShouldShowPresetName Value="false"/><UserName Value=""/><Annotation Value=""/>'
        f'<SourceContext><Value/></SourceContext>'
        f'<MpePitchBendUsesTuning Value="true"/>'
        f'<ViewData Value="{{}}" />'
    )


def xml_speaker(aid):
    return (
        f'<Speaker><LomId Value="0"/><Manual Value="true"/>'
        f'<AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
        f'<MidiCCOnOffThresholds><Min Value="64"/><Max Value="127"/></MidiCCOnOffThresholds></Speaker>'
    )


def xml_param(name, value, min_val, max_val, aid, has_mod=False):
    s = (
        f'<{name}><LomId Value="0"/><Manual Value="{value}"/>'
        f'<MidiControllerRange><Min Value="{min_val}"/><Max Value="{max_val}"/></MidiControllerRange>'
        f'<AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
    )
    if has_mod:
        s += f'<ModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></ModulationTarget>'
    s += f'</{name}>'
    return s


def xml_mixer(aid, pointee_id):
    return (
        f'<Mixer>'
        f'<LomId Value="0"/><LomIdView Value="0"/><IsExpanded Value="true"/><BreakoutIsExpanded Value="false"/>'
        f'{xml_on_bool(aid)}'
        f'<ModulationSourceCount Value="0"/><ParametersListWrapper LomId="0"/>'
        f'<Pointee Id="{pointee_id}"/>'
        f'<LastSelectedTimeableIndex Value="0"/><LastSelectedClipEnvelopeIndex Value="0"/>'
        f'<LastPresetRef><Value/></LastPresetRef>'
        f'<LockedScripts/>'
        f'<IsFolded Value="false"/><ShouldShowPresetName Value="false"/><UserName Value=""/><Annotation Value=""/>'
        f'<SourceContext><Value/></SourceContext>'
        f'<MpePitchBendUsesTuning Value="true"/>'
        f'<ViewData Value="{{}}" />'
        f'<Sends/>'
        f'{xml_speaker(aid)}'
        f'<SoloSink Value="false"/><PanMode Value="0"/>'
        f'{xml_param("Pan", "0", "-1", "1", aid, True)}'
        f'{xml_param("SplitStereoPanL", "-1", "-1", "1", aid, True)}'
        f'{xml_param("SplitStereoPanR", "1", "-1", "1", aid, True)}'
        f'{xml_param("Volume", "1", "0.0003162277571", "1.99526238", aid, True)}'
        f'<ViewStateSessionTrackWidth Value="93"/>'
        f'<CrossFadeState><LomId Value="0"/><Manual Value="1"/>'
        f'<AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget>'
        f'<MidiControllerRange><Min Value="0"/><Max Value="2"/></MidiControllerRange></CrossFadeState>'
        f'<SendsListWrapper LomId="0"/>'
        f'</Mixer>'
    )


def xml_freeze_sequencer(aid, pointee_id):
    return (
        f'<FreezeSequencer>'
        f'{xml_device_header(aid, pointee_id)}'
        f'{xml_clip_slot_list()}'
        f'<MonitoringEnum Value="1"/>'
        f'<KeepRecordMonitoringLatency Value="true"/>'
        f'<Sample><ArrangerAutomation><Events/><AutomationTransformViewState>'
        f'<IsTransformPending Value="false"/><TimeAndValueTransforms/>'
        f'</AutomationTransformViewState></ArrangerAutomation></Sample>'
        f'<VolumeModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></VolumeModulationTarget>'
        f'<TranspositionModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></TranspositionModulationTarget>'
        f'<TransientEnvelopeModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></TransientEnvelopeModulationTarget>'
        f'<GrainSizeModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></GrainSizeModulationTarget>'
        f'<FluxModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></FluxModulationTarget>'
        f'<SampleOffsetModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></SampleOffsetModulationTarget>'
        f'<ComplexProFormantsModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></ComplexProFormantsModulationTarget>'
        f'<ComplexProEnvelopeModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></ComplexProEnvelopeModulationTarget>'
        f'<PitchViewScrollPosition Value="-1073741824"/>'
        f'<SampleOffsetModulationScrollPosition Value="-1073741824"/>'
        f'<Recorder><IsArmed Value="false"/><TakeCounter Value="1"/></Recorder>'
        f'</FreezeSequencer>'
    )


def xml_midi_controllers(aid):
    s = "<MidiControllers>"
    for i in range(131):
        lock = "1" if i in (1, 11, 66) else "0"
        s += f'<ControllerTargets.{i} Id="{aid.next()}"><LockEnvelope Value="{lock}"/></ControllerTargets.{i}>'
    s += "</MidiControllers>"
    return s


# ── MidiClip Builder ─────────────────────────

def build_midi_clip_xml(clip, clip_id, note_id_start=1):
    by_pitch = defaultdict(list)
    for n in clip["notes"]:
        by_pitch[n["pitch"]].append(n)

    kt_xml = ""
    kt_id = 0
    note_id = note_id_start

    for pitch in sorted(by_pitch.keys()):
        events = sorted(by_pitch[pitch], key=lambda n: n["time"])
        ev_xml = ""
        for n in events:
            ev_xml += (
                f'<MidiNoteEvent Time="{n["time"]}" Duration="{n["duration"]}" '
                f'Velocity="{n["velocity"]}" OffVelocity="64" NoteId="{note_id}"/>'
            )
            note_id += 1
        kt_xml += f'<KeyTrack Id="{kt_id}"><Notes>{ev_xml}</Notes><MidiKey Value="{pitch}"/></KeyTrack>'
        kt_id += 1

    loop_end = clip["length"]
    start_time = clip["start"]
    end_time = start_time + clip["length"]
    name = esc_xml(clip.get("name", ""))
    color = clip.get("color", -1)
    loop_on = "true" if clip.get("loop", True) else "false"

    return (
        f'<MidiClip Id="{clip_id}" Time="{start_time}">'
        f'<LomId Value="0"/><LomIdView Value="0"/>'
        f'<CurrentStart Value="{start_time}"/><CurrentEnd Value="{end_time}"/>'
        f'<Loop><LoopStart Value="0"/><LoopEnd Value="{loop_end}"/><StartRelative Value="0"/>'
        f'<LoopOn Value="{loop_on}"/><OutMarker Value="{loop_end}"/>'
        f'<HiddenLoopStart Value="0"/><HiddenLoopEnd Value="{loop_end}"/></Loop>'
        f'<Name Value="{name}"/><Annotation Value=""/>'
        f'<Color Value="{color}"/>'
        f'<LaunchMode Value="0"/><LaunchQuantisation Value="0"/>'
        f'<TimeSignature><TimeSignatures><RemoteableTimeSignature Id="0">'
        f'<Numerator Value="4"/><Denominator Value="4"/><Time Value="0"/>'
        f'</RemoteableTimeSignature></TimeSignatures></TimeSignature>'
        f'<Envelopes><Envelopes/></Envelopes>'
        f'<ScrollerTimePreserver><LeftTime Value="0"/><RightTime Value="{loop_end}"/></ScrollerTimePreserver>'
        f'<TimeSelection><AnchorTime Value="0"/><OtherTime Value="0"/></TimeSelection>'
        f'<Legato Value="false"/>'
        f'<Ram Value="false"/>'
        f'<GrooveSettings><GrooveId Value="-1"/></GrooveSettings>'
        f'<Disabled Value="false"/>'
        f'<VelocityAmount Value="0"/>'
        f'<FollowAction><FollowTime Value="4"/><IsLinked Value="true"/><LoopIterations Value="1"/>'
        f'<FollowActionA Value="4"/><FollowActionB Value="0"/><FollowChanceA Value="100"/>'
        f'<FollowChanceB Value="0"/><JumpIndexA Value="1"/><JumpIndexB Value="1"/>'
        f'<FollowActionEnabled Value="false"/></FollowAction>'
        f'<Grid><FixedNumerator Value="1"/><FixedDenominator Value="16"/>'
        f'<GridIntervalPixel Value="20"/><Ntoles Value="2"/><SnapToGrid Value="true"/><Fixed Value="true"/></Grid>'
        f'<FreezeStart Value="0"/><FreezeEnd Value="0"/>'
        f'<IsWarped Value="true"/>'
        f'<TakeId Value="1"/>'
        f'<IsInKey Value="false"/>'
        f'<ScaleInformation><Root Value="0"/><Name Value="0"/></ScaleInformation>'
        f'<Notes>'
        f'<KeyTracks>{kt_xml}</KeyTracks>'
        f'<PerNoteEventStore><EventLists/></PerNoteEventStore>'
        f'<NoteProbabilityGroups/>'
        f'<ProbabilityGroupIdGenerator><NextId Value="1"/></ProbabilityGroupIdGenerator>'
        f'<NoteIdGenerator><NextId Value="{note_id}"/></NoteIdGenerator>'
        f'</Notes>'
        f'<BankSelectCoarse Value="-1"/><BankSelectFine Value="-1"/><ProgramChange Value="-1"/>'
        f'<NoteEditorFoldInZoom Value="-1"/><NoteEditorFoldInScroll Value="0"/>'
        f'<NoteEditorFoldOutZoom Value="867"/><NoteEditorFoldOutScroll Value="-373"/>'
        f'<NoteEditorFoldScaleZoom Value="-1"/><NoteEditorFoldScaleScroll Value="0"/>'
        f'<NoteSpellingPreference Value="0"/>'
        f'<AccidentalSpellingPreference Value="3"/>'
        f'<PreferFlatRootNote Value="false"/>'
        f'<ExpressionGrid><FixedNumerator Value="1"/><FixedDenominator Value="16"/>'
        f'<GridIntervalPixel Value="20"/><Ntoles Value="2"/><SnapToGrid Value="false"/><Fixed Value="false"/></ExpressionGrid>'
        f'</MidiClip>'
    )


# ── MidiTrack Builder ────────────────────────

def build_midi_track_xml(track, track_id, aid, pid):
    clip_xml = "\n".join(
        build_midi_clip_xml(clip, ci, 1) for ci, clip in enumerate(track["clips"])
    )
    seq_pointee = pid.next()
    mix_pointee = pid.next()
    frz_pointee = pid.next()

    name = esc_xml(track.get("name", "MIDI"))
    color = track.get("color", 0)

    return (
        f'<MidiTrack Id="{track_id}" SelectedToolPanel="2" SelectedTransformationName="Arpeggiate" SelectedGeneratorName="Rhythm">'
        f'<LomId Value="0"/><LomIdView Value="0"/>'
        f'<IsContentSelectedInDocument Value="false"/>'
        f'<PreferredContentViewMode Value="0"/>'
        f'<TrackDelay><Value Value="0"/><IsValueSampleBased Value="false"/></TrackDelay>'
        f'<Name><EffectiveName Value="{name}"/><UserName Value="{name}"/><Annotation Value=""/><MemorizedFirstClipName Value=""/></Name>'
        f'<Color Value="{color}"/>'
        f'<AutomationEnvelopes><Envelopes/></AutomationEnvelopes>'
        f'<TrackGroupId Value="-1"/>'
        f'<TrackUnfolded Value="true"/>'
        f'<DevicesListWrapper LomId="0"/>'
        f'<ClipSlotsListWrapper LomId="0"/>'
        f'<ArrangementClipsListWrapper LomId="0"/>'
        f'<TakeLanesListWrapper LomId="0"/>'
        f'<ViewData Value="{{}}" />'
        f'<TakeLanes><TakeLanes/><AreTakeLanesFolded Value="true"/></TakeLanes>'
        f'<LinkedTrackGroupId Value="-1"/>'
        f'<SavedPlayingSlot Value="-1"/>'
        f'<SavedPlayingOffset Value="0"/>'
        f'<Freeze Value="false"/>'
        f'<NeedArrangerRefreeze Value="true"/>'
        f'<PostProcessFreezeClips Value="0"/>'
        f'<DeviceChain>'
        f'{xml_automation_lanes()}'
        f'<ClipEnvelopeChooserViewState><SelectedDevice Value="1"/><SelectedEnvelope Value="0"/><PreferModulationVisible Value="false"/></ClipEnvelopeChooserViewState>'
        f'{xml_routing()}'
        f'{xml_mixer(aid, mix_pointee)}'
        f'<MainSequencer>'
        f'{xml_device_header(aid, seq_pointee)}'
        f'{xml_clip_slot_list()}'
        f'<MonitoringEnum Value="1"/>'
        f'<KeepRecordMonitoringLatency Value="true"/>'
        f'<ClipTimeable><ArrangerAutomation><Events>'
        f'{clip_xml}'
        f'</Events><AutomationTransformViewState><IsTransformPending Value="false"/><TimeAndValueTransforms/></AutomationTransformViewState></ArrangerAutomation></ClipTimeable>'
        f'<Recorder><IsArmed Value="false"/><TakeCounter Value="0"/></Recorder>'
        f'{xml_midi_controllers(aid)}'
        f'</MainSequencer>'
        f'{xml_freeze_sequencer(aid, frz_pointee)}'
        f'<DeviceChain><Devices/><SignalModulations/></DeviceChain>'
        f'</DeviceChain>'
        f'<ReWireDeviceMidiTargetId Value="0"/>'
        f'<PitchbendRange Value="96"/>'
        f'<IsTuned Value="true"/>'
        f'<ControllerLayoutRemoteable Value="0"/>'
        f'<ControllerLayoutCustomization><PitchClassSource Value="0"/><OctaveSource Value="2"/><KeyNoteTarget Value="60"/><StepSize Value="1"/><OctaveEvery Value="12"/><AllowedKeys Value="0"/><FillerKeysMapTo Value="0"/></ControllerLayoutCustomization>'
        f'</MidiTrack>'
    )


# ── MainTrack Builder ────────────────────────

def build_main_track_xml(tempo, aid, pid):
    mix_pointee = pid.next()
    tempo_auto_id = aid.next()
    tempo_mod_id = aid.next()
    time_sig_auto_id = aid.next()
    tempo_env_pointee = tempo_auto_id
    time_sig_env_pointee = time_sig_auto_id

    return (
        f'<MainTrack SelectedToolPanel="7" SelectedTransformationName="" SelectedGeneratorName="">'
        f'<LomId Value="0"/><LomIdView Value="0"/>'
        f'<IsContentSelectedInDocument Value="false"/>'
        f'<PreferredContentViewMode Value="0"/>'
        f'<TrackDelay><Value Value="0"/><IsValueSampleBased Value="false"/></TrackDelay>'
        f'<Name><EffectiveName Value="Main"/><UserName Value=""/><Annotation Value=""/><MemorizedFirstClipName Value=""/></Name>'
        f'<Color Value="4"/>'
        f'<AutomationEnvelopes><Envelopes>'
        f'<AutomationEnvelope Id="0"><EnvelopeTarget><PointeeId Value="{time_sig_env_pointee}"/></EnvelopeTarget><Automation><Events><EnumEvent Id="0" Time="-63072000" Value="201"/></Events><AutomationTransformViewState><IsTransformPending Value="false"/><TimeAndValueTransforms/></AutomationTransformViewState></Automation></AutomationEnvelope>'
        f'<AutomationEnvelope Id="1"><EnvelopeTarget><PointeeId Value="{tempo_env_pointee}"/></EnvelopeTarget><Automation><Events><FloatEvent Id="0" Time="-63072000" Value="{tempo}"/></Events><AutomationTransformViewState><IsTransformPending Value="false"/><TimeAndValueTransforms/></AutomationTransformViewState></Automation></AutomationEnvelope>'
        f'</Envelopes></AutomationEnvelopes>'
        f'<TrackGroupId Value="-1"/>'
        f'<TrackUnfolded Value="false"/>'
        f'<DevicesListWrapper LomId="0"/>'
        f'<ClipSlotsListWrapper LomId="0"/>'
        f'<ArrangementClipsListWrapper LomId="0"/>'
        f'<TakeLanesListWrapper LomId="0"/>'
        f'<ViewData Value="{{}}" />'
        f'<TakeLanes><TakeLanes/><AreTakeLanesFolded Value="true"/></TakeLanes>'
        f'<LinkedTrackGroupId Value="-1"/>'
        f'<DeviceChain>'
        f'<AutomationLanes><AutomationLanes><AutomationLane Id="0"><SelectedDevice Value="1"/><SelectedEnvelope Value="4"/><IsContentSelectedInDocument Value="false"/><LaneHeight Value="85"/></AutomationLane></AutomationLanes><AreAdditionalAutomationLanesFolded Value="false"/></AutomationLanes>'
        f'<ClipEnvelopeChooserViewState><SelectedDevice Value="0"/><SelectedEnvelope Value="0"/><PreferModulationVisible Value="false"/></ClipEnvelopeChooserViewState>'
        f'{xml_routing_main()}'
        f'<Mixer>'
        f'<LomId Value="0"/><LomIdView Value="0"/><IsExpanded Value="true"/><BreakoutIsExpanded Value="false"/>'
        f'{xml_on_bool(aid)}'
        f'<ModulationSourceCount Value="0"/><ParametersListWrapper LomId="0"/>'
        f'<Pointee Id="{mix_pointee}"/>'
        f'<LastSelectedTimeableIndex Value="4"/><LastSelectedClipEnvelopeIndex Value="0"/>'
        f'<LastPresetRef><Value/></LastPresetRef>'
        f'<LockedScripts/>'
        f'<IsFolded Value="false"/><ShouldShowPresetName Value="false"/><UserName Value=""/><Annotation Value=""/>'
        f'<SourceContext><Value/></SourceContext>'
        f'<MpePitchBendUsesTuning Value="true"/>'
        f'<ViewData Value="{{}}" />'
        f'<Sends/>'
        f'{xml_speaker(aid)}'
        f'<SoloSink Value="false"/><PanMode Value="0"/>'
        f'{xml_param("Pan", "0", "-1", "1", aid, True)}'
        f'{xml_param("SplitStereoPanL", "-1", "-1", "1", aid, True)}'
        f'{xml_param("SplitStereoPanR", "1", "-1", "1", aid, True)}'
        f'{xml_param("Volume", "1", "0.0003162277571", "1.99526238", aid, True)}'
        f'<ViewStateSessionTrackWidth Value="103"/>'
        f'<CrossFadeState><LomId Value="0"/><Manual Value="1"/><AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget><MidiControllerRange><Min Value="0"/><Max Value="2"/></MidiControllerRange></CrossFadeState>'
        f'<SendsListWrapper LomId="0"/>'
        f'<Tempo><LomId Value="0"/><Manual Value="{tempo}"/><MidiControllerRange><Min Value="60"/><Max Value="200"/></MidiControllerRange><AutomationTarget Id="{tempo_auto_id}"><LockEnvelope Value="0"/></AutomationTarget><ModulationTarget Id="{tempo_mod_id}"><LockEnvelope Value="0"/></ModulationTarget></Tempo>'
        f'<TimeSignature><LomId Value="0"/><Manual Value="201"/><AutomationTarget Id="{time_sig_auto_id}"><LockEnvelope Value="0"/></AutomationTarget><MidiControllerRange><Min Value="0"/><Max Value="494"/></MidiControllerRange></TimeSignature>'
        f'{xml_param("GlobalGrooveAmount", "0", "0", "131.25", aid, True)}'
        f'{xml_param("CrossFade", "0", "-1", "1", aid, True)}'
        f'<TempoAutomationViewBottom Value="60"/>'
        f'<TempoAutomationViewTop Value="200"/>'
        f'</Mixer>'
        f'<FreezeSequencer><AudioSequencer Id="0">'
        f'{xml_device_header(aid, pid.next())}'
        f'{xml_clip_slot_list()}'
        f'<MonitoringEnum Value="1"/>'
        f'<KeepRecordMonitoringLatency Value="true"/>'
        f'<Sample><ArrangerAutomation><Events/><AutomationTransformViewState><IsTransformPending Value="false"/><TimeAndValueTransforms/></AutomationTransformViewState></ArrangerAutomation></Sample>'
        f'<VolumeModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></VolumeModulationTarget>'
        f'<TranspositionModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></TranspositionModulationTarget>'
        f'<TransientEnvelopeModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></TransientEnvelopeModulationTarget>'
        f'<GrainSizeModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></GrainSizeModulationTarget>'
        f'<FluxModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></FluxModulationTarget>'
        f'<SampleOffsetModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></SampleOffsetModulationTarget>'
        f'<ComplexProFormantsModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></ComplexProFormantsModulationTarget>'
        f'<ComplexProEnvelopeModulationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></ComplexProEnvelopeModulationTarget>'
        f'<PitchViewScrollPosition Value="-1073741824"/>'
        f'<SampleOffsetModulationScrollPosition Value="-1073741824"/>'
        f'<Recorder><IsArmed Value="false"/><TakeCounter Value="1"/></Recorder>'
        f'</AudioSequencer></FreezeSequencer>'
        f'<DeviceChain><Devices/><SignalModulations/></DeviceChain>'
        f'</DeviceChain>'
        f'</MainTrack>'
    )


# ── PreHearTrack Builder ─────────────────────

def build_prehear_track_xml(aid, pid):
    mix_pointee = pid.next()
    return (
        f'<PreHearTrack SelectedToolPanel="7" SelectedTransformationName="" SelectedGeneratorName="">'
        f'<LomId Value="0"/><LomIdView Value="0"/>'
        f'<IsContentSelectedInDocument Value="false"/>'
        f'<PreferredContentViewMode Value="0"/>'
        f'<TrackDelay><Value Value="0"/><IsValueSampleBased Value="false"/></TrackDelay>'
        f'<Name><EffectiveName Value="0-Main"/><UserName Value=""/><Annotation Value=""/><MemorizedFirstClipName Value=""/></Name>'
        f'<Color Value="-1"/>'
        f'<AutomationEnvelopes><Envelopes/></AutomationEnvelopes>'
        f'<TrackGroupId Value="-1"/>'
        f'<TrackUnfolded Value="false"/>'
        f'<DevicesListWrapper LomId="0"/>'
        f'<ClipSlotsListWrapper LomId="0"/>'
        f'<ArrangementClipsListWrapper LomId="0"/>'
        f'<TakeLanesListWrapper LomId="0"/>'
        f'<ViewData Value="{{}}" />'
        f'<TakeLanes><TakeLanes/><AreTakeLanesFolded Value="true"/></TakeLanes>'
        f'<LinkedTrackGroupId Value="-1"/>'
        f'<DeviceChain>'
        f'<AutomationLanes><AutomationLanes><AutomationLane Id="0"><SelectedDevice Value="0"/><SelectedEnvelope Value="0"/><IsContentSelectedInDocument Value="false"/><LaneHeight Value="85"/></AutomationLane></AutomationLanes><AreAdditionalAutomationLanesFolded Value="false"/></AutomationLanes>'
        f'<ClipEnvelopeChooserViewState><SelectedDevice Value="0"/><SelectedEnvelope Value="0"/><PreferModulationVisible Value="false"/></ClipEnvelopeChooserViewState>'
        f'{xml_routing_main()}'
        f'<Mixer>'
        f'<LomId Value="0"/><LomIdView Value="0"/><IsExpanded Value="true"/><BreakoutIsExpanded Value="false"/>'
        f'{xml_on_bool(aid)}'
        f'<ModulationSourceCount Value="0"/><ParametersListWrapper LomId="0"/>'
        f'<Pointee Id="{mix_pointee}"/>'
        f'<LastSelectedTimeableIndex Value="0"/><LastSelectedClipEnvelopeIndex Value="0"/>'
        f'<LastPresetRef><Value/></LastPresetRef>'
        f'<LockedScripts/>'
        f'<IsFolded Value="false"/><ShouldShowPresetName Value="false"/><UserName Value=""/><Annotation Value=""/>'
        f'<SourceContext><Value/></SourceContext>'
        f'<MpePitchBendUsesTuning Value="true"/>'
        f'<ViewData Value="{{}}" />'
        f'<Sends/>'
        f'{xml_speaker(aid)}'
        f'<SoloSink Value="false"/><PanMode Value="0"/>'
        f'{xml_param("Pan", "0", "-1", "1", aid, True)}'
        f'{xml_param("SplitStereoPanL", "-1", "-1", "1", aid, True)}'
        f'{xml_param("SplitStereoPanR", "1", "-1", "1", aid, True)}'
        f'{xml_param("Volume", "0.5012149811", "0.0003162277571", "1.99526238", aid, True)}'
        f'<ViewStateSessionTrackWidth Value="74"/>'
        f'<CrossFadeState><LomId Value="0"/><Manual Value="1"/><AutomationTarget Id="{aid.next()}"><LockEnvelope Value="0"/></AutomationTarget><MidiControllerRange><Min Value="0"/><Max Value="2"/></MidiControllerRange></CrossFadeState>'
        f'<SendsListWrapper LomId="0"/>'
        f'</Mixer>'
        f'<DeviceChain><Devices/><SignalModulations/></DeviceChain>'
        f'</DeviceChain>'
        f'</PreHearTrack>'
    )


# ── Scenes Builder ───────────────────────────

def build_scenes_xml(tempo):
    scenes = "".join(
        f'<Scene Id="{i}">'
        f'<FollowAction><FollowTime Value="4"/><IsLinked Value="true"/><LoopIterations Value="1"/>'
        f'<FollowActionA Value="4"/><FollowActionB Value="0"/><FollowChanceA Value="100"/>'
        f'<FollowChanceB Value="0"/><JumpIndexA Value="0"/><JumpIndexB Value="0"/>'
        f'<FollowActionEnabled Value="false"/></FollowAction>'
        f'<Name Value=""/><Annotation Value=""/><Color Value="-1"/><Tempo Value="{tempo}"/>'
        f'<IsTempoEnabled Value="false"/><TimeSignatureId Value="201"/>'
        f'<IsTimeSignatureEnabled Value="false"/><LomId Value="0"/><ClipSlotsListWrapper LomId="0"/>'
        f'</Scene>'
        for i in range(8)
    )
    return f"<Scenes>{scenes}</Scenes>"


# ── LiveSet Footer ───────────────────────────

def build_footer_xml():
    return (
        '<Transport>'
        '<PhaseNudgeTempo Value="10"/><LoopOn Value="false"/><LoopStart Value="8"/><LoopLength Value="16"/><LoopIsSongStart Value="false"/><CurrentTime Value="0"/><PunchIn Value="false"/><PunchOut Value="false"/><MetronomeTickDuration Value="0"/><DrawMode Value="false"/>'
        '</Transport>'
        '<SessionScrollPos X="0" Y="0"/>'
        '<SelectedBreakpointValue Value="0"/>'
        '<SignalModulations/>'
        '<GlobalQuantisation Value="4"/>'
        '<AutoQuantisation Value="0"/>'
        '<Grid><FixedNumerator Value="1"/><FixedDenominator Value="16"/><GridIntervalPixel Value="20"/><Ntoles Value="2"/><SnapToGrid Value="true"/><Fixed Value="false"/></Grid>'
        '<ScaleInformation><Root Value="0"/><Name Value="0"/></ScaleInformation>'
        '<InKey Value="false"/>'
        '<SmpteFormat Value="0"/>'
        '<TimeSelection><AnchorTime Value="0"/><OtherTime Value="0"/></TimeSelection>'
        '<SequencerNavigator><BeatTimeHelper><CurrentZoom Value="0.25"/></BeatTimeHelper><ScrollerPos X="0" Y="0"/><ClientSize X="828" Y="227"/></SequencerNavigator>'
        '<IsContentSplitterOpen Value="true"/>'
        '<IsExpressionSplitterOpen Value="true"/>'
        '<ExpressionLanes>'
        '<MidiEditorLaneModel Id="0"><Type Value="5"/><Size Value="41"/><IsMinimized Value="true"/></MidiEditorLaneModel>'
        '<MidiEditorLaneModel Id="1"><Type Value="0"/><Size Value="41"/><IsMinimized Value="false"/></MidiEditorLaneModel>'
        '<MidiEditorLaneModel Id="2"><Type Value="1"/><Size Value="41"/><IsMinimized Value="false"/></MidiEditorLaneModel>'
        '<MidiEditorLaneModel Id="3"><Type Value="2"/><Size Value="41"/><IsMinimized Value="true"/></MidiEditorLaneModel>'
        '<MidiEditorLaneModel Id="4"><Type Value="3"/><Size Value="41"/><IsMinimized Value="true"/></MidiEditorLaneModel>'
        '</ExpressionLanes>'
        '<ContentLanes>'
        '<MidiEditorLaneModel Id="0"><Type Value="2"/><Size Value="41"/><IsMinimized Value="false"/></MidiEditorLaneModel>'
        '<MidiEditorLaneModel Id="2"><Type Value="3"/><Size Value="25"/><IsMinimized Value="true"/></MidiEditorLaneModel>'
        '<MidiEditorLaneModel Id="1"><Type Value="4"/><Size Value="25"/><IsMinimized Value="true"/></MidiEditorLaneModel>'
        '</ContentLanes>'
        '<ViewStateFxSlotCount Value="4"/>'
        '<ViewStateSessionMixerVolumeSectionHeight Value="120"/>'
        '<ViewStateArrangerMixerVolumeSectionHeight Value="120"/>'
        '<ShouldSceneTempoAndTimeSignatureBeVisible Value="false"/>'
        '<WaveformVerticalZoomFactor Value="1"/>'
        '<IsWaveformVerticalZoomActive Value="true"/>'
        '<Locators><Locators/></Locators>'
        '<DetailClipKeyMidis/>'
        '<TracksListWrapper LomId="0"/>'
        '<VisibleTracksListWrapper LomId="0"/>'
        '<ReturnTracksListWrapper LomId="0"/>'
        '<ScenesListWrapper LomId="0"/>'
        '<CuePointsListWrapper LomId="0"/>'
        '<SelectedDocumentViewInMainWindow Value="1"/>'
        '<Annotation Value=""/>'
        '<SoloOrPflSavedValue Value="true"/>'
        '<SoloInPlace Value="true"/>'
        '<CrossfadeCurve Value="2"/>'
        '<LatencyCompensation Value="2"/>'
        '<HighlightedTrackIndex Value="0"/>'
        '<GroovePool><LomId Value="0"/><Grooves/><DefaultGrooveId Value="-1"/><GroovesListWrapper LomId="0"/></GroovePool>'
        '<AutomationMode Value="false"/>'
        '<SnapAutomationToGrid Value="true"/>'
        '<ArrangementOverdub Value="false"/>'
        '<ColorSequenceIndex Value="0"/>'
        '<AutoColorPickerForPlayerAndGroupTracks><NextColorIndex Value="0"/></AutoColorPickerForPlayerAndGroupTracks>'
        '<AutoColorPickerForReturnAndMainTracks><NextColorIndex Value="0"/></AutoColorPickerForReturnAndMainTracks>'
        '<ViewData Value="{}"/>'
        '<ResetNonautomatedMidiControllersOnClipStarts Value="true"/>'
        '<MidiFoldIn Value="false"/>'
        '<MidiFoldMode Value="-99"/>'
        '<MultiClipFocusMode Value="false"/>'
        '<MultiClipLoopBarHeight Value="0"/>'
        '<MidiPrelisten Value="false"/>'
        '<LinkedTrackGroups/>'
        '<NoteSpellingPreference Value="0"/>'
        '<AccidentalSpellingPreference Value="3"/>'
        '<PreferFlatRootNote Value="false"/>'
        '<UseWarperLegacyHiQMode Value="false"/>'
        '<VideoWindowRect Top="-2147483648" Left="-2147483648" Bottom="-2147483648" Right="-2147483648"/>'
        '<ShowVideoWindow Value="true"/>'
        '<TuningSystems/>'
        '<TrackHeaderWidth Value="93"/>'
        '<ViewStateMainWindowClipDetailOpen Value="true"/>'
        '<ViewStateMainWindowHiddenOtherDocViewTypeClipDetailOpen Value="true"/>'
        '<ViewStateMainWindowHiddenOtherDocViewTypeDeviceDetailOpen Value="false"/>'
        '<ViewStateMainWindowDeviceDetailOpen Value="false"/>'
        '<ViewStateSecondWindowClipDetailOpen Value="false"/>'
        '<ViewStateSecondWindowDeviceDetailOpen Value="true"/>'
        '<ViewStates>'
        '<MixerInArrangement Value="0"/><ArrangerMixerIO Value="1"/><ArrangerMixerSends Value="1"/><ArrangerMixerReturns Value="1"/><ArrangerMixerVolume Value="1"/><ArrangerMixerTrackOptions Value="0"/><ArrangerMixerCrossFade Value="0"/><ArrangerMixerTrackPerformanceImpactMeter Value="0"/>'
        '<MixerInSession Value="1"/><SessionIO Value="1"/><SessionSends Value="1"/><SessionReturns Value="1"/><SessionVolume Value="1"/><SessionTrackOptions Value="0"/><SessionCrossFade Value="0"/><SessionTrackPerformanceImpactMeter Value="0"/><SessionShowOverView Value="0"/>'
        '<ArrangerIO Value="1"/><ArrangerReturns Value="1"/><ArrangerVolume Value="1"/><ArrangerTrackOptions Value="0"/><ArrangerShowOverView Value="1"/>'
        '</ViewStates>'
    )


# ── Top-Level ALS Generator ──────────────────

class ALSGenerator:
    def __init__(self, tempo=120):
        self.tempo = tempo
        self.tracks = []

    def add_midi_track(self, name="MIDI", color=19):
        """Add a MIDI track. Returns track index."""
        self.tracks.append({"name": name, "color": color, "clips": []})
        return len(self.tracks) - 1

    def add_clip(self, track_index, clip_start, clip_length, clip_name="",
                 notes=None, loop=True, color=None):
        """
        Add a MIDI clip to a track.
        notes: list of (pitch, time, duration, velocity) tuples
        """
        if notes is None:
            notes = []
        if color is None:
            color = self.tracks[track_index]["color"]

        note_dicts = [
            {"pitch": n[0], "time": n[1], "duration": n[2], "velocity": n[3]}
            for n in notes
        ]
        self.tracks[track_index]["clips"].append({
            "start": clip_start,
            "length": clip_length,
            "name": clip_name,
            "notes": note_dicts,
            "loop": loop,
            "color": color,
        })

    def build_xml(self):
        aid = IDAlloc(1)
        pid = IDAlloc(19700)

        track_xml = ""
        for i, track in enumerate(self.tracks):
            track_xml += build_midi_track_xml(track, 10 + i, aid, pid)

        main_xml = build_main_track_xml(self.tempo, aid, pid)
        prehear_xml = build_prehear_track_xml(aid, pid)
        scenes_xml = build_scenes_xml(self.tempo)
        footer_xml = build_footer_xml()
        next_pointee = pid.peek()

        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<Ableton MajorVersion="5" MinorVersion="12.0_12300" SchemaChangeCount="1" Creator="ALS Generator" Revision="">'
            f'<LiveSet>'
            f'<NextPointeeId Value="{next_pointee}"/>'
            f'<OverwriteProtectionNumber Value="3075"/>'
            f'<LomId Value="0"/>'
            f'<LomIdView Value="0"/>'
            f'<Tracks>{track_xml}</Tracks>'
            f'{main_xml}'
            f'{prehear_xml}'
            f'<SendsPre/>'
            f'{scenes_xml}'
            f'{footer_xml}'
            f'</LiveSet>'
            f'</Ableton>'
        )

    def save(self, filepath):
        xml = self.build_xml()
        with gzip.open(filepath, 'wb') as f:
            f.write(xml.encode('utf-8'))
        print(f"Saved: {filepath} ({len(self.tracks)} tracks, {self.tempo} BPM)")

    @classmethod
    def from_json(cls, json_data):
        """
        Create from JSON: {"tempo": 120, "tracks": [{"name": "...", "color": 19, "clips": [{"start": 0, "length": 4, "name": "...", "notes": [{"pitch": 60, "time": 0, "duration": 0.5, "velocity": 100}]}]}]}
        """
        if isinstance(json_data, str):
            json_data = json.loads(json_data)
        gen = cls(tempo=json_data.get("tempo", 120))
        for td in json_data.get("tracks", []):
            t = gen.add_midi_track(td.get("name", "MIDI"), td.get("color", 19))
            for cd in td.get("clips", []):
                notes = [(n["pitch"], n["time"], n["duration"], n["velocity"]) for n in cd.get("notes", [])]
                gen.add_clip(t, cd.get("start", 0), cd.get("length", 4), cd.get("name", ""), notes, cd.get("loop", True), cd.get("color"))
        return gen


def demo():
    gen = ALSGenerator(tempo=120)
    t1 = gen.add_midi_track("Melody", color=9)
    gen.add_clip(t1, 0, 4, "Melody A", [
        (60, 0.0, 0.5, 100), (64, 0.5, 0.5, 90), (67, 1.0, 1.0, 95),
        (65, 2.0, 0.5, 85), (64, 2.5, 0.5, 80), (62, 3.0, 0.5, 90), (60, 3.5, 0.5, 100),
    ])
    t2 = gen.add_midi_track("Bass", color=7)
    gen.add_clip(t2, 0, 4, "Bass Loop", [
        (36, 0.0, 0.75, 110), (36, 1.0, 0.75, 100), (41, 2.0, 0.75, 105), (43, 3.0, 0.75, 95),
    ])
    t3 = gen.add_midi_track("Drums", color=3)
    gen.add_clip(t3, 0, 4, "Beat", [
        (36, 0.0, 0.25, 120), (36, 1.0, 0.25, 110), (36, 2.0, 0.25, 120), (36, 3.0, 0.25, 110),
        (38, 1.0, 0.25, 100), (38, 3.0, 0.25, 100),
        (42, 0.0, 0.25, 80), (42, 0.5, 0.25, 60), (42, 1.0, 0.25, 80), (42, 1.5, 0.25, 60),
        (42, 2.0, 0.25, 80), (42, 2.5, 0.25, 60), (42, 3.0, 0.25, 80), (42, 3.5, 0.25, 60),
    ])
    return gen


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ALS Generator")
    parser.add_argument("--json", help="JSON input file")
    parser.add_argument("--output", "-o", default="output.als", help="Output .als file")
    parser.add_argument("--demo", action="store_true", help="Generate demo ALS")
    args = parser.parse_args()

    if args.demo:
        gen = demo()
        gen.save(args.output)
    elif args.json:
        with open(args.json) as f:
            data = json.load(f)
        gen = ALSGenerator.from_json(data)
        gen.save(args.output)
    else:
        parser.print_help()
