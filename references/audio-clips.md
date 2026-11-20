# Audio clips (canonical)

Warp, warp markers, sample references, clip gain, fades, placing many one-shots, and how clips go on the arrangement.
ID rules are in `format.md`, checks in `qa-gates.md`, stock devices in `native-devices.md`.

## Warp mode: decide first

| Goal | WarpMode | How to write it |
|---|---|---|
| **Keep the original speed** (pass-through: one-shots, beats, songs in a DJ mix) | **Beats** (`WarpMode Value="0"`. `scripts/build_als.py` writes it intending Beats, and the sets opened. Whether Live's screen shows "Beats" is not verified.) | Write the warp markers at the original speed (see "Keeping the original speed" below). Complex does not pass audio through unchanged (confirmed in a DJ mix, 2026-10-10). |
| **Stretch to another tempo** (fit a loop to the set's tempo; polyrhythm) | **Complex Pro** (`WarpMode=4`; used in a loop-arrangement pipeline) | Stretch the markers' BeatTime. Add the block of Complex Pro parameters (below). |

Common to both: `IsWarped / Sync / HiQ = true`.
Extra Complex Pro parameters: `GranularityTones=30, GranularityTexture=65, FluctuationTexture=25, TransientResolution=6, TransientLoopMode=2, TransientEnvelope=100, ComplexProFormants=100, ComplexProEnvelope=128`
(the same block is also present in the Beats clips of `scripts/build_als.py`; the values do not change).

## Warp markers: three points (two are not enough)

An anchor just past the end of the loop is required at the end. `file_dur_sec = num_frames / sample_rate`.

| Id | SecTime | BeatTime |
|---|---|---|
| 0 | 0 | 0 |
| 1 | `file_dur_sec` | `loop_session_beats` (for the original speed, `file_dur_sec x tempo / 60`) |
| 2 | the two ways below | `loop_session_beats + 1/32` |

There are two ways to write the SecTime of the end anchor (Id 2). **Both opened in Live.**
- **Loop-arrangement pipeline**: `file_dur_sec + 591/sample_rate` (about 591 samples), BeatTime `+0.03125` (= 1/32 beat).
- **One-shot pipeline** (`scripts/build_als.py`): `file_dur_sec + (1/32) x 60 / tempo`, BeatTime `+ 1/32` beat (1/32 beat is the number of seconds that passes at the original speed, so the **original speed is kept** across the whole clip).

To play at the original speed, use the second way (`clip_xml` in `scripts/build_als.py`; BeatTime = SecTime x tempo / 60).
The first way is the value used for clips stretched with Complex Pro.

## Polyrhythm (without re-rendering the audio)

`loop_session_beats = native_beats x den/num` (speed_ratio is a `Fraction`, `native_beats = loop_bars*4`).
Scaling the markers' BeatTime by this ratio **is** the time stretch; the audio file is not touched (Live stretches it). 4/3, 3/2 ... are just multipliers of BeatTime.
Start rotation: `Loop/StartRelative = (native_offset_beats x den/num) mod loop_session_beats` (scale the offset by the playback ratio and wrap by the clip's loop length).

## Sample references (if wrong, Live re-analyses or drops the file)

Inside `SampleRef/FileRef`:
- `RelativePathType=3`, `RelativePath="Samples/Imported/<name>.wav"`, an absolute `Path`, `Type=2`. Copy the wav to `<Project>/Samples/Imported/` (deduplicate by name).
- `OriginalFileSize` = byte length of the wav.
- `OriginalCrc` = **`zlib.crc32(bytes) & 0xFFFF`**, a **16-bit** CRC (mask with 0xFFFF; left as 32 bits it differs and triggers a rescan).
- `DefaultDuration = num_frames`, `DefaultSampleRate = sample_rate` (read with `wave`).

## Clip gain

`SampleVolume = 10**(clip_gain_db/20)` (linear amplitude). For the track volume range see the mixer values in `format.md`.

## Fades (seconds)

`Fades/FadeOutLength` is in **seconds** = `fade_out_bars x (4*60/bpm)`, kept within the clip length.
Fading each voice out over about one bar (leaving the attack alone, so kicks stay tight) gives **the same sound** as a 2-channel mix rendered from the ALS.
`ClipFadesAreInitialized=true`, `IsDefaultFadeOut=false`.

## Placing many one-shots (2026-11-20, one-shot pipeline)

Audio one-shots were placed on the Arrangement one hit at a time, **1,341 clips** (opened in Live 12.4.16; the sound was not checked on Live's screen):
- Warp on, WarpMode Beats, three warp markers at the original speed, no loop (`LoopOn false`), end markers (`OutMarker`, `HiddenLoopEnd`) set to the sounding length.
- A per-clip fade-out of **5 ms** (`FADE_OUT_SEC = 0.005`, kept within the clip length).
- **Seamless loop clips** (textures where the next clip starts exactly at the end of the previous one) get **fade 0** (without 0, the level dips at every join).
- Implementation: `scripts/build_als.py`.

## Placing clips on the arrangement

- Clips go in `MainSequencer/Sample/ArrangerAutomation/Events/AudioClip` (Arrangement View). The Session View `ClipSlotList` has all slots empty.
- `Time` and `CurrentStart` / `CurrentEnd` are in **beats** = `(bar-1)*4` / `bar*4`.
- `TakeId=-1` (for AudioClip), `MonitoringEnum=2` (the AudioTrack's MainSequencer).
- `LoopEnd` = the nearest multiple of 4 beats (4 bars = 16 beats). `SavedPlayingSlot="-1"` (no Session playback). The default is 64 bars (changeable with `arrangement_bars`).

```
<MainSequencer>
  <ClipSlotList> (all slots empty) </ClipSlotList>
  <Sample>
    <ArrangerAutomation>
      <Events>
        <AudioClip Id="0" Time="0">
          <CurrentStart Value="0"/>
          <CurrentEnd Value="256"/>  <- 64 bars = 256 beats
          <Loop>
            <LoopEnd Value="16"/>    <- 4-bar loop
            <LoopOn Value="true"/>
          </Loop>
          ...
        </AudioClip>
      </Events>
    </ArrangerAutomation>
  </Sample>
</MainSequencer>
```

For video clips (not stretched) see `format.md`.

## Minimal AudioClip (with warp and fade; the Complex Pro stretch pattern)

```xml
<AudioClip Id="0" Time="32">
  <CurrentStart Value="32"/><CurrentEnd Value="40"/>
  <Loop><LoopStart Value="0"/><LoopEnd Value="16"/><StartRelative Value="0"/>
        <LoopOn Value="true"/><OutMarker Value="16"/></Loop>
  <Name Value="my_loop_id"/>
  <IsWarped Value="true"/><WarpMode Value="4"/>
  <SampleRef><FileRef>
    <RelativePathType Value="3"/><RelativePath Value="Samples/Imported/x.wav"/>
    <Path Value="/abs/.../Samples/Imported/x.wav"/><Type Value="2"/>
    <OriginalFileSize Value="..."/><OriginalCrc Value="...(crc32 & 0xFFFF)"/>
  </FileRef><DefaultDuration Value="N_frames"/><DefaultSampleRate Value="48000"/></SampleRef>
  <Sync Value="true"/><HiQ Value="true"/><Fade Value="true"/>
  <Fades><FadeInLength Value="0"/><FadeOutLength Value="1.5"/>
         <ClipFadesAreInitialized Value="true"/></Fades>
  <SampleVolume Value="0.7244"/>          <!-- 10**(-2.8dB/20) -->
  <WarpMarkers>
    <WarpMarker Id="0" SecTime="0"      BeatTime="0"/>
    <WarpMarker Id="1" SecTime="2.0"    BeatTime="16"/>
    <WarpMarker Id="2" SecTime="2.01231" BeatTime="16.03125"/>  <!-- +591/sr, +1/32 -->
  </WarpMarkers>
</AudioClip>
```
For the complete element (including Loop, Fades, WarpMarkers and SampleRef) see `clip_xml` in `scripts/build_als.py`.
