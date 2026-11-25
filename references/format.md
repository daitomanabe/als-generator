# General shape of an .als

File format, XML hierarchy, IDs, tracks, locators, time signature, tempo, and how to use Live's bundled sets as templates.
Audio clips are in `audio-clips.md`, stock devices in `native-devices.md`, plugins in `plugin-devices.md`, checks in `qa-gates.md`.

## File format

- `.als` = gzip( XML ). Compatible with Ableton Live 12. Most generated sets were written with `MinorVersion="12.0_12300"` (Live's bundled sets use `12.0_12402`. `12.0_12300` = documents of Live 12.3.x, `12.0_12402` = Live 12.4.x. A 12402 .adv preset embedded in a 12300 set opens only when the device's class exists at 12300; a class that entered with 12.4, such as `Erosion2`, gives `Unknown class`: see `native-devices.md`, "Versions and classes").
- Dependencies: the Python 3 standard library only (gzip, wave, zlib, xml). The output is an `.als` file plus a project folder.
- Always gzip the final XML and save it as `.als`.

```
<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12300" SchemaChangeCount="1"
         Creator="Ableton Live 12.3.5" Revision="">
  <LiveSet>
    <NextPointeeId Value="..." />
    <OverwriteProtectionNumber Value="3075" />
    <Tracks>
      <MidiTrack Id="...">           <- may repeat
        <Name> ... </Name>
        <DeviceChain>
          <Mixer> ... </Mixer>
          <MainSequencer>
            <ClipSlotList> ... </ClipSlotList>        <- Session View clips
            <ArrangerAutomation>
              <Events>
                <MidiClip Id="..." Time="...">        <- Arrangement clips
                  <Notes>
                    <KeyTracks>
                      <KeyTrack Id="...">
                        <Notes>
                          <MidiNoteEvent Time="..." Duration="..." Velocity="..." ... />
                        </Notes>
                        <MidiKey Value="..." />       <- MIDI note number
                      </KeyTrack>
                    </KeyTracks>
                  </Notes>
                </MidiClip>
              </Events>
            </ArrangerAutomation>
          </MainSequencer>
        </DeviceChain>
      </MidiTrack>
    </Tracks>
    <MainTrack> ... </MainTrack>
    <PreHearTrack> ... </PreHearTrack>
    <Scenes> ... </Scenes>
    <Transport>
      <LoopOn Value="false" />
      <CurrentTime Value="..." />
    </Transport>
  </LiveSet>
</Ableton>
```

## MIDI note representation

Notes of the same pitch go into one `KeyTrack`:
```xml
<KeyTrack Id="0">
  <Notes>
    <MidiNoteEvent Time="0" Duration="0.25" Velocity="100" OffVelocity="64" NoteId="1" />
    <MidiNoteEvent Time="1" Duration="0.5" Velocity="80" OffVelocity="64" NoteId="2" />
  </Notes>
  <MidiKey Value="60" />   <!-- C3 -->
</KeyTrack>
```
- Time/Duration are in **beats** (not bars). In 4/4 one bar = 4.0 beats, a sixteenth = 0.25, an eighth = 0.5, a quarter = 1.0.
- NoteId is a sequential number unique within the clip (from 1). `NoteIdGenerator.NextId` = the last NoteId + 1.

## ID management (this section is canonical; other documents point here)

| ID kind | Use | Rule |
|---|---|---|
| `MidiTrack Id` | track identity | unique sequence |
| `KeyTrack Id` | key track identity | sequence within the clip (from 0) |
| `MidiClip Id` | clip identity | sequence within the track (from 0) |
| `MidiNoteEvent NoteId` | note identity | sequence within the clip (from 1) |
| `AutomationTarget Id` | automation | globally unique sequence |
| `Pointee Id` | internal references | globally unique sequence |
| `NextPointeeId` | next free ID | largest used value + 1 |

There are three ID rules (checks: gates 3, 4 and 5 in `qa-gates.md`).

### 1. NextPointeeId must be above every Id in the set

`NextPointeeId` is not just "the next value of the `Pointee Id` counter". Ableton checks it against the `Id`-type attributes of the whole XML, so it must exceed the maximum of at least all of these:
- `AutomationTarget Id`, `ModulationTarget Id`, `ControllerTargets.* Id`, `Pointee Id`, `PointeeId Value`
- `MidiTrack Id` / `AudioTrack Id` / `ReturnTrack Id`
- `ClipSlot Id` / `Scene Id` / `MidiClip Id` / `AudioClip Id`

Do not deliver a set with `NextPointeeId <= max_xml_id`. Ableton reports `corrupt and cannot be loaded (NextPointeeId is too low: X must be bigger than Y)`.
Do not rely on `pid.peek()` alone.

Be especially careful with many tracks. Even an empty `MidiTrack` creates a large number of `AutomationTarget` / `ModulationTarget` Ids (Mixer, MainSequencer, FreezeSequencer, MIDI controllers), so the largest `AutomationTarget Id` is far above the next `Pointee` value. Example: with 999 empty MIDI tracks the next `Pointee` value is about 22700, but the largest XML ID is 151886, so `NextPointeeId` must be at least 151887.
A device template for one plugin uses hundreds of Ids, so a 30-track set with several plugins puts the main allocator in the tens of thousands.

### 2. Do not duplicate Ids in the Pointee namespace

Treat the following as one namespace and never duplicate within it:
- `Pointee Id`, `AutomationTarget Id`, `ModulationTarget Id`, `*ModulationTarget Id` (for example `VolumeModulationTarget Id`), `ControllerTargets.* Id`

A single duplicate gives `corrupt (non-unique Pointee IDs)` in Ableton.
With separate counters such as `aid = IDAlloc(1)` and `pid = IDAlloc(19700)`, many tracks make `AutomationTarget Id=19700` collide with `Pointee Id=19700`.
**Issue Ids from one shared allocator**, or compute ranges that cannot overlap in advance (for example two ranges: 1 upward for devices and 2_000_000 upward for track structure, then `NextPointeeId = max(both) + 1`; `scripts/build_als.py` does this).
In devices taken from an .adv, the Ids of every `AutomationTarget` / `*ModulationTarget` / `Pointee` are 0, so renumber them from the shared allocator (see `native-devices.md`).

`PointeeId Value` is a reference to an existing target, so it is not part of the duplicate check. It does count in the `NextPointeeId > max_xml_id` maximum.

### 3. Every member of a list carries its own Id

Elements inside lists such as `Devices`, `Tracks`, `Envelopes`, `Events`, `ClipSlotList`, `Scenes`, `WarpMarkers`, `TimeSignatures`, `Sends` and `SendsPre` all have an `Id`.
When one is missing: `The document "...als" is corrupt and cannot be loaded. (Not all list members have Ids. (at line 2, column N))`.
The typical cause is putting a device taken from an .adv into `<Devices>` without an `Id` (a sequence within the chain: 0, 1, 2...).
This actually happened on 2026-10-10 in six DJ-mix sets (the IDs were renumbered but `dev.set("Id", ...)` was missing; column N was right after `<Devices><FilterEQ3>`).
Going through `DeviceBuilder.finish()` in `references/native_device_chain.py` adds it. When embedding by hand, add it too, and check that `list_ids(root)` is empty after writing.

### Where track Ids start

In two production pipelines the AudioTrack Id (db-id) started at 8 (`8+index`, then return / main / prehear), and in a third it started at 10.
**Whether either is required has not been verified.** (Sets were built with both.)

## Track colours

Live colour indexes (0-69):
```
0: salmon/pink    1: orange-red    2: orange
3: gold           4: yellow-green  5: green
6: teal           7: cyan          8: blue
9: purple         10: violet       11: magenta
12-13: red tones  14-15: warm      16-17: yellow
18-19: green      20-21: blue-green 22-24: blue
25-27: purple     ...
```

## AudioTrack vs MidiTrack

| Item | MidiTrack | AudioTrack |
|---|---|---|
| Tag | `<MidiTrack>` | `<AudioTrack>` |
| Sequencer | MainSequencer + ClipTimeable | MainSequencer + Sample |
| Clip | `<MidiClip>` (Notes/KeyTracks) | `<AudioClip>` (SampleRef/WarpMarkers) |
| Session clip | inside ClipTimeable | inside ClipSlotList |
| Controllers | MidiControllers (131 of them) | none |
| Tail | ReWireDeviceMidiTargetId, PitchbendRange, etc. | IsTuned only |

### ControllerTargets mapping in MidiControllers (verified 2026-07-07)

In `ControllerTargets.{i}`, **i=0 is Pitch Bend, i=1 is Channel Pressure, i>=2 is CC (i-2)**.
**To automate CC n with a clip envelope, put the Id of `ControllerTargets.(n+2)` in `ClipEnvelope/EnvelopeTarget/PointeeId`** (example: CC74 -> `ControllerTargets.76`).
Confirmed on a set saved by Live 12.4.2: the track automating CC20 references `.22`, CC85 references `.87`, CC102 references `.104`.
Mistaking "index = CC number" reaches a CC two below the intended one (it does not corrupt the set, so it is easy to miss). `LockEnvelope` is 0 everywhere in the real defaults.

Values and anchor of a CC clip envelope (confirmed on a set saved by Live 12.4, 2026-09-28):
`FloatEvent Value` is the **raw CC value 0-127** (writing 0-1 is read as 0-1 out of 127 steps and has almost no effect; this does not corrupt the set either).
The first `FloatEvent` is an **anchor at `Time="-63072000"`** holding the initial value. After `</Automation>` comes
`<LoopSlot><Value/></LoopSlot><ScrollerTimePreserver><LeftTime Value="0"/><RightTime Value="0"/></ScrollerTimePreserver>`.
One implementation took a 0-1 input and rounded it to 0-127.

### ReturnTrack structure (important)

A ReturnTrack has no AudioSequencer:
```
ReturnTrack
└── DeviceChain
    ├── Mixer
    ├── DeviceChain (Devices)
    └── FreezeSequencer
```
A ClipSlotList with 0 slots inside the ReturnTrack's FreezeSequencer is normal in Arrangement-only sets (the structure used in production). Session View sets require every ClipSlotList to match (`qa-gates.md`).
The number of Sends must equal the number of ReturnTracks (2 ReturnTracks = 2 Sends on each track).

### Mixer values

- Track fader: `AudioTrack/DeviceChain/Mixer/Volume/Manual` = linear (-6 dB = 0.5012, -8 dB = 0.3981).
- The `MidiControllerRange` of the Volume automation target is **Min 0.0003162277571, Max 1.99526238** (= -inf ... +6 dB). Normalize and check volume envelopes in this range (not 0..1).
- -inf is `Volume/Manual = 0.0003162277571`; mute is `Speaker/Manual = false`.

## Notes for generation

1. **AutomationTarget IDs are globally unique.** Each track consumes about 320. Manage them centrally in an ID-manager class.
2. **The number of Sends equals the number of ReturnTracks** (above).
3. **Number of Scenes = number of ClipSlots.** To use Session View, every track's `ClipSlotList` needs slots for all scenes.
4. **MidiClip CurrentEnd** is the end position on the arrangement (for a loop: CurrentStart + number of loops x LoopEnd).
5. **Empty DeviceChain**: even without an instrument the DeviceChain structure is required (devices can be added later in Live).
6. **ReturnTracks** can be omitted, but with them Send effects are available.
7. **gzip**: always gzip the final XML and save it as .als.
8. For IDs, follow "ID management" above.

## Locators

One `Locators/Locators/Locator` per section: `Time` (in beats = `(bar-1)*4`) plus `Name`.
Insert them by string-replacing the empty `<Locators><Locators/></Locators>` in the footer.
In Live 12.4 an element has `Id`, `LomId`, `Time` (beats), `Name`, `Annotation` and `IsSongStart`.

## Automation (general)

- `AutomationEnvelopes/Envelopes/AutomationEnvelope` (Id unique within the track) -> `EnvelopeTarget/PointeeId` = the Id of the target parameter's `AutomationTarget` -> `Automation/Events/FloatEvent`.
- The first `FloatEvent` is an anchor at `Time="-63072000"` (about -2 years of beats). Without it Live ignores the envelope. The remaining times are in beats, ascending.
- **One `<AutomationEnvelopes>` block per track** (number the envelope Ids across all devices; do not split per device).
- Units of stock-device values are in `native-devices.md`; plugin values (normalized 0-1) are in `plugin-devices.md`.

## Time signature

The MainTrack time signature is written as a code: **`(numerator - 1) + 99 * i`** (denominator 1, 2, 4, 8, 16 -> i = 0 to 4). 4/4 = 201, 13/16 = 408, maximum 494.
(2026-11-20: a 13/16 set opened in Live 12.4.16. Whether the display shows 13/16 is not verified.)
**Keep three places in agreement**: the MainTrack's `TimeSignature/Manual`, its envelope's `EnumEvent`, and every clip's `RemoteableTimeSignature`.

## Tempo

Write the MainTrack `Tempo/Manual` (`MainTrack/DeviceChain/Mixer/Tempo/Manual`) **and** the first value (`FloatEvent`) of the MainTrack `AutomationEnvelope` that points at its `AutomationTarget`.
`MidiControllerRange` is Min 60 / Max 200 (a value written by the production pipeline that opened as it was; it is not the range in which Live can place a tempo).
Sets with a fractional tempo (138.24) were built. **Whether they opened in Live is not verified.**

## Using Live 12.4 bundled sets as templates

A pattern used on 2026-11-13 in a visualization demo. Copying elements that Live saved is more reliable than writing XML from scratch.
The templates are inside the Core Library of your Live installation (`<Live app>/Contents/App-Resources/Core Library/`; all are `MinorVersion="12.0_12402"`; the paths below are from Live 12 Suite and may differ in other editions):

| Use | File | Contents |
|---|---|---|
| Set base | `Lessons/Sets/Playing Software Instruments.als` | one empty AudioTrack, MidiTrack and ReturnTrack each, no devices, no clips, empty GroovePool |
| Audio clip template | `Lessons/Sets/Driver Error Compensation.als` | one AudioClip (GrooveId -1) |
| MIDI clip template | `Templates/Quick Start Song.als` | 10 Session MidiClips. **They point at GrooveId 0** (set it to -1 when copying) |

When copying an element (clip, track, device) from another set, **remove every reference that points at the source**: set `GrooveSettings/GrooveId` to -1 (if you also need the groove, copy the `Groove` element itself into `GroovePool`), empty the clip's `Envelopes`, renumber the Pointee-namespace Ids and reattach the `PointeeId`s, and rewrite `SampleRef`.
Forget this and Live will not open the set even when every structural check passes (the Quick Start Song MidiClip left at GrooveId 0 -> `GroovePool corrupted`, 2026-11-13; gate 6 in `qa-gates.md`).

Procedure:
- Copy the base track to get the number of tracks you need, renumber every Pointee-namespace `Id`, and reattach the `PointeeId`s inside tracks. `LomId` and `LomIdView` are 0.
- After copying a clip template, set: `Id`, `Time`, `CurrentStart/End`, `Loop`, `Name`, `Color`, `TakeId` (arrangement examples use a positive number such as 1; empty TakeLanes are fine), **`GrooveSettings/GrooveId = -1`**, empty `Envelopes`, empty `Onsets` and `SavedWarpMarkersForStretched`, and rewrite `SampleRef`.
- Audio clips go in `MainSequencer/Sample/ArrangerAutomation/Events`, MIDI clips in `MainSequencer/ClipTimeable/ArrangerAutomation/Events`.
- Locators, tempo and volume: see the sections above.

## Video clips

Confirmed against an example saved by Live 12.4.16: there is no special element; it is an ordinary `AudioClip` whose `SampleRef/FileRef/Path` points at a .mov or .mp4.
- Not stretched (`IsWarped=false`). **For an unwarped clip, `Loop` (LoopEnd, OutMarker, HiddenLoopEnd) is in seconds.** `CurrentStart/End` are in beats.
- `DefaultDuration` is the number of audio samples in the video (48 kHz x seconds), `DefaultSampleRate` is 48000. The WarpMarkers are the same three points as for a stretched clip (seconds <-> beats; see `audio-clips.md`).
- The set has `VideoWindowRect` and `ShowVideoWindow` (true shows the video window). Keep an audio stream in the video (every example had one).

## The MIDI generator (`als_generator.py`)

```python
from als_generator import ALSGenerator

gen = ALSGenerator(tempo=120)
track_id = gen.add_midi_track("Bass", color=7)
# notes = [(pitch, time_in_clip, duration, velocity), ...]
gen.add_clip(track_id, clip_start=0, clip_length=4, clip_name="Bass Loop", notes=[
    (36, 0.0, 0.5, 100),    # C1 at beat 0
    (36, 1.0, 0.5, 90),
    (38, 2.0, 0.25, 110),
    (41, 3.0, 0.75, 85),
])
gen.save("output.als")
```
CLI:
```bash
python3 als_generator.py --demo --output my_project.als            # 3 tracks, 120 BPM
python3 als_generator.py --json input.json --output my_project.als
# shape of input.json (notes are nested under clips):
# {"tempo":120,"tracks":[{"name":"Bass","color":7,
#   "clips":[{"start":0,"length":4,"name":"Loop",
#     "notes":[{"pitch":36,"time":0,"duration":0.5,"velocity":100}]}]}]}
```
`als_generator.py` has no `--tempo` / `--tracks` flags (set the tempo and track count in the `--json` input or with `ALSGenerator(tempo=...)`).
