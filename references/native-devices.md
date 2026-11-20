# Stock device chains: reusing Core Library .adv presets

> Verified 2026-07-09 on Live 12 Suite (12.0_12402 .adv files embedded into 12.0_12300 ALS files; three mix sets confirmed to load on a real Live).
> Implementation: `native_device_chain.py` (same folder; helper used in production).

## Principle

An Ableton stock-device preset **.adv is gzip XML**, and `root[0]` is a device element that can be embedded directly into an ALS
`DeviceChain/DeviceChain/Devices`. You do not have to write device XML from scratch, and no hand-saved template .als is needed.

```
<Live app>/Contents/App-Resources/Core Library/
  Devices/Audio Effects/<device name>/<preset name>.adv
```
(In Live 12 Suite this is `/Applications/Ableton Live 12 Suite.app/...`.) **Do not copy these files into your repository**: read them from your own Live installation at build time.
The scripts here find the folder through the `ABLETON_CORE_LIBRARY` environment variable, or by globbing `/Applications/Ableton Live 12*.app`.
The presets referenced here were checked against a Suite installation; **other editions may not ship every preset**, so a build can fail with "preset not found" on them.

## Embedding procedure (three required steps)

1. **Add an `Id` attribute.** The device element in an .adv has no Id. Give it its sequence number within the chain (0, 1, 2...).
   **If you forget, Live refuses to open the set with the `Not all list members have Ids` corrupt error** (this really happened on 2026-10-10; symptoms and check
   -> "ID management 3" in format.md). Going through `DeviceBuilder.finish()` adds it. When embedding by hand, always add it, and after writing check that
   `native_device_chain.list_ids(root)` is empty.
2. **Renumber IDs.** In an .adv the Ids of every `AutomationTarget` / `*ModulationTarget` / `Pointee` are 0.
   Renumber all of them from the **shared allocator** (duplicates in the Pointee namespace = corrupt; -> "ID management 2" in format.md).
3. **Parameters are `<tag>/Manual@Value`**: `dev.find(param + "/Manual").set("Value", v)`.

```python
def renumber(dev, aid):
    for e in dev.iter():
        if e.tag == "AutomationTarget" or e.tag.endswith("ModulationTarget") or e.tag == "Pointee":
            if "Id" in e.attrib:
                e.set("Id", str(aid.next()))
```

Paths from Ableton's build machine inside `LastPresetRef` are harmless. Leave them.
A MinorVersion mismatch (12402 -> 12300) is also fine.

## Sidechain routing (Compressor2)

```
SideChain/OnOff/Manual                       = "true"
SideChain/RoutedInput/Routable/Target        = "AudioIn/Track.{track db-id}/TrackOut"
SideChain/RoutedInput/Routable/UpperDisplayString = "1-Drums"   (display only, Live regenerates it)
SideChain/RoutedInput/Routable/LowerDisplayString = "Post Mixer"
```

`AudioIn/Track.{id}/TrackOut` = the Post Mixer tap. The track db-id is the Id attribute of the AudioTrack
(starting at 8; -> "Where track Ids start" in format.md). **Confirmed to load on a real Live.**

2026-11-20, one-shot pipeline: a Compressor2 sidechain with the **key EQ off** opened in Live 12.4.16 (`AudioIn/Track.N/TrackOut`).
The effect was not checked on Live's screen.

## Verified enum values and unit tables

### EQ Eight (`Eq8`): Band Mode (set on Bands.0 to 7, both ParameterA and ParameterB)
| Value | Meaning |
|---|---|
| 0 | Low Cut 48dB/oct |
| 1 | Low Cut 12dB/oct |
| 2 | Low Shelf |
| 3 | Bell |
| 4 | Notch |
| 5 | High Shelf |
| 6 | High Cut 12dB/oct |
| 7 | High Cut 48dB/oct |

(Reverse-engineered from the Core Library presets "Lo-Hi Shelf", "Cheesy Speaker" and "Center Kill".)
Even when you use only one high-pass band, **set IsOn to false on the other seven bands** and do not forget GlobalGain=0.

### Compressor2
| Parameter | Unit |
|---|---|
| Threshold | **linear amplitude** (0.45 is about -6.9 dB, 0.32 is about -9.9 dB) |
| Ratio | the multiplier as is (inf = 3.4e38) |
| Attack / Release | ms |
| Gain | dB |
| Model | 0 = Peak, 1 = RMS-like |
| SideChainEq_Mode | **6 values, 0 to 5, unlike the 8-value EQ Eight table** (the .adv MidiControllerRange is 0 to 5; fixed 2026-11-11). Inferred from about 50 Core Library presets: **3 = low-pass** (Kick Reducer: 115 Hz, Q 2.7, gain 0), 4 = Peak (the default; Vocal Strip: +15 dB @ 6 kHz), 0 = Low Shelf (Mix Gel: +4 dB @ 195 Hz, Acoustic: +6.7 dB @ 205 Hz), 1 and 5 = one of high-pass, band-pass or notch (De-esser is 1 @ 6 kHz, Q 3; most drum kits are 5 @ 80 to 371 Hz; both with gain 0), 2 not observed. Gain only has an effect for 0 and 4 (and probably 2). The key that reacts to a kick is 3 (low-pass). Glue Compressor's `SideChainEq/Mode` is also 0 to 5. **Not yet verified on Live's screen** |

### Saturator
| Parameter | Content |
|---|---|
| Type | 0 = Analog Clip, 1 = Soft Sine (then in UI order) |
| PreDrive | dB (= the Drive knob) |
| PostDrive | dB (output compensation) |
| DryWet | 0..1 |
| ColorOn/BaseDrive/ColorDepth | colour section. To disable: ColorOn=false, BaseDrive=0, ColorDepth=0 |
| Hi-Quality | **does not exist as an XML parameter** (it is a context-menu option). Ask the user to switch it on by hand |

Values written that opened in Live 12.4.16 (2026-11-20, one-shot pipeline; the kick insert and return C): `Type` 0, `PreDrive` and `PostDrive` (dB), `DryWet` 1,
`ColorOn` false, `BaseDrive` 0, `ColorDepth` 0. What the values mean (the sound) was not checked on Live's screen.

### Reverb (`Reverb/Hall/Dark Hall.adv`) and Redux (`Redux/New Mirage.adv`) (2026-11-20, one-shot pipeline; the returns' Reverb and Redux)
- Reverb: use `Reverb/Hall/Dark Hall.adv`, write `MixDirect` 1.0 and `DecayTime` 5500, and it opened in Live 12.4.16. Put it on a return (see "Three returns" below).
- Redux: `Redux/New Mirage.adv`. The device tag is **`Redux2`**. It opened **untouched** (the preset as is).
- The Reverb's wet effect and the Redux sound were not checked on Live's screen.

### Three returns (2026-11-20, one-shot pipeline, opened in Live 12.4.16)
A = `Reverb/Hall/Dark Hall.adv` -> Eq8, B = `Defaults/Delay.adv` -> Eq8, C = Saturator -> `Redux/New Mirage.adv` -> Eq8.
Each track has 3 `Sends` and 3 `SendsPre` (number of Sends = number of ReturnTracks; -> ReturnTrack in format.md).
Master is Eq8 -> Utility `Bass Mono.adv` -> Limiter. The Delay sync and the Reverb wet were not checked on Live's screen.
Implementation: `scripts/build_als.py`.

### Drum Buss (`DrumBuss`)
| Parameter | Range |
|---|---|
| DriveAmount / CrunchAmount | **0..1** (normalized UI %) |
| DriveType | 0 = Soft, 1 = Medium, 2 = Hard |
| TransientShaping | **-1..+1** (0 = centre; UI +-100%) |
| BoomAmount / BoomFrequency / BoomDecay | Boom section. With material that is strong in the low end, Boom=0 is recommended |
| InputTrim / OutputGain | linear (0.708 is about -3 dB) |

### Utility (`StereoGain`)
`Utility/Bass Mono.adv` is "BassMono=true / BassMonoFrequency=120" as it is. Usable without modification.

### Limiter
Ceiling / Gain = dB. Lookahead = enum (0/1/2 = 1/3/6 ms).

### Spectrum
`Spectrum/Master.adv` -> the device tag is `SpectrumAnalyzer`. No setup needed.

### EQ Three (`FilterEQ3`): a 3-band DJ EQ (2026-10-10)
`EQ Three/<preset>.adv` (Defaults has none, so use a preset under Devices and rewrite the values).
The child element tags were confirmed to match the FilterEQ3 in a set saved by Live 12.4.2. Ranges from the .adv MidiControllerRange:

| Parameter | Value | Note |
|---|---|---|
| GainLo / GainMid / GainHi | linear 0.000316 to 1.995 | 1.0 = 0 dB, 0.000316 = -70 dB (kill), +6 dB maximum |
| FreqLo / FreqHi | Hz 50 to 5000 / 200 to 18000 | defaults 250 / about 1767. Used 250 / 2500 for DJing |
| LowOn / MidOn / HighOn | bool | kill switches |
| Slope | 0 to 1 | default 1 |

### Delay (`Delay`): a beat-synced echo (2026-10-10)
`Defaults/Audio Effects/Delay.adv`. Ranges from the .adv MidiControllerRange:

| Parameter | Value | Note |
|---|---|---|
| DryWet | 0 to 1 | output mix (0 on an insert is pass-through) |
| Feedback | 0 to 0.95 | |
| DelayLine_Link / SyncL / SyncR | bool | |
| DelayLine_SyncedSixteenthL / R | 0 to 7 | 2 was used as a dotted eighth (3/16) (default L=2, R=3). **The meaning of the value is not verified on Live's screen** |
| DelayLine_PingPong | bool | ping-pong (echo bouncing left and right). The DJ-mix Delay has been on since 2026-10-10 |
| Filter_On / Filter_Frequency / Filter_Bandwidth | bool / 50 to 18000 Hz / 0.5 to 9 | |

### Limiter (`Limiter`): master safety (2026-10-10)
`Defaults/Audio Effects/Limiter.adv`. Ranges from the .adv MidiControllerRange:

| Parameter | Value | Note |
|---|---|---|
| Gain | dB -24 to 24 | 0 means no lift |
| Ceiling | dB -24 to 0 | default -0.3. -1 in the DJ mix |
| Release | ms 0.01 to 3000 | automatic when AutoRelease is on |
| AutoRelease | bool | follows the music (on Live's side) |
| Lookahead / Mode | 0 to 2 / 0 to 2 | meaning not verified (left at default 0) |
| Maximize / MaximizeThreshold / MaximizeOutput | bool / dB / dB | |

To insert into the MainTrack, append to `LiveSet/MainTrack/DeviceChain/DeviceChain/Devices` (Id = 0; renumbering IDs is the same as for the others).

### Stock-device automation (2026-10-10)
- In the track's `AutomationEnvelopes/Envelopes` add `<AutomationEnvelope Id="k">` (unique within the track);
  `EnvelopeTarget/PointeeId` = the Id of that parameter's `AutomationTarget` (the value after renumbering; `finish_with_targets()` returns it).
- `FloatEvent` `Value` is **in the parameter's own units** (EQ Three Gain is linear, DryWet is 0 to 1; different from the plugin's 0-1 normalization).
  The first point is `Time="-63072000"` (the default value), times are in beats, ascending. For a step change use two points 1/64 beat apart.
- A track volume envelope goes in the same Envelopes.

### Two-deck DJ mix (2026-10-10)
Songs are placed alternately on Deck A and Deck B, with EQ Three -> Delay on each track. Over a 16-bar overlap:
the incoming song enters with bass killed, mid -6, high -8 and volume -6 dB, and brings high back over 4 bars, mid over 8 bars and volume over 12 bars, with a one-beat bass swap at bar 8.
The outgoing song has its bass killed at bar 8 and lowers mid, high and volume (-12 dB over 16 bars; never let both songs play at full level at once), and in the last 2 bars does an
echo-out with Delay Feedback 0.7 and DryWet 0.4. Clip Warp is Beats (at the original tempo it passes through; Complex does not pass through unchanged; -> "Warp mode" in audio-clips.md).

## Other points

- **Inserting devices into the MainTrack**: append to `MainTrack/DeviceChain/DeviceChain/Devices` (easy in ElementTree post-processing).
- **Track fader**: -> "Mixer values" in format.md (linear, Min 0.000316 / Max 1.995).
- **Sharing with another builder**: pass `devices_xml` as a string and share the allocator with the .adv renumbering.
- **QA gate relaxation**: a ReturnTrack FreezeSequencer ClipSlotList with 0 slots is normal in
  Arrangement-only sets. Only Session View sets need every list to match (-> ReturnTrack in format.md, qa-gates.md).
- **How to decode enum values** (applies to unknown devices): dump a few Core Library presets whose purpose is obvious from the name
  (De-esser, Lo-Hi Shelf, Analog Clip, ...) and match values to meanings.
  One preset cannot resolve degenerate cases such as 12 dB/48 dB slopes, so always cross-check with several.

## Records of sets that opened in Live

| Date | Set | Contents | Live |
|---|---|---|---|
| 2026-07-09 | three mix sets | EQ8 / Saturator / Compressor2 sidechain / Utility / DrumBuss / Limiter (12.0_12402 .adv embedded in a 12.0_12300 set) | Live 12 Suite |
| 2026-11-20 | three one-shot sets (`scripts/build_als.py`) | 1,341 one-shots (-> audio-clips.md), 3 returns, Reverb Dark Hall, Redux New Mirage, Saturator values, Compressor2 sidechain, master Eq8 -> Bass Mono -> Limiter, 13/16 time signature (-> "Time signature" in format.md) | Live 12.4.16 (confirmed by the user) |

Only that they loaded was confirmed. The sound and the meaning of values (Reverb wet, Delay sync, sidechain effect) were not checked on Live's screen.
