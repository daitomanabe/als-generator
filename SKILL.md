---
name: als-generator
description: Generates Ableton Live Sets (.als, gzip XML) with valid IDs, stock-device chains, MIDI/audio clips and structural QA. Use when asked to create or modify a Live Set programmatically.
---

# ALS Generator

Generate gzip/XML Live Sets (Live 12.x) with the bundled Python resources and references. Preserve media paths, the requested tempo and Session/Arrangement semantics.

## Scope
- In scope: building `.als` files (tracks, clips, tempo, time signature, locators, stock devices, plugin devices, automation) and checking their structure.
- Out of scope: Max for Live devices (.amxd); Ableton's Extensions SDK (code that runs inside Live, not .als files).

## Core rules (details in references/)
- **Do not write the XML from memory.** Build from verified code and Live's bundled .adv files. 2026-11-20 comparison: a set written from memory crashed Live 12.4.16 twice (`std::out_of_range map::at`) and another was corrupt; memory gets only the rough skeleton right (it wrote Live 11's `MasterTrack` and about half of Live 12's element types).
- **Three ID rules**: `NextPointeeId` above every Id in the file; Pointee-namespace Ids unique (shared allocator); every list member has its own `Id` (including devices copied from .adv). See `format.md`.
- **Dangling references**: anything copied from another set (including Live's templates) must lose every reference pointing outside the new set (GrooveId, clip Envelopes, PointeeId, SampleRef). See `format.md`, `qa-gates.md` gate 6.
- **Structural checks are not a Live readback.** A set that passes every gate can still be refused by Live. Run `scripts/check_als.py`, then have the user open it.
- **Ask the user to save first, then open the generated set themselves.** A malformed set can crash Live outright; never open it in a Live that is running the user's set.
- **Stock presets come from the user's own Live** (`ABLETON_CORE_LIBRARY` or `/Applications/Ableton Live 12*.app`). Never copy Ableton files into a repository; some editions lack some presets.

## Which reference to read
| Work | Read |
|---|---|
| .als structure, IDs, tracks, tempo, time signature, locators, templates, video clips, MIDI generator | `references/format.md` |
| Audio clips: warp mode, warp markers, sample refs, fades, one-shots | `references/audio-clips.md` |
| Stock devices from the Core Library (.adv), enum/unit tables, returns | `references/native-devices.md` + `references/native_device_chain.py` |
| VST/AU plugin devices and their automation | `references/plugin-devices.md` |
| Checks before delivery | `references/qa-gates.md` |
| MIDI-only sets | `references/als_generator.py` (usage in `format.md`) |

## Implementation to copy
`scripts/build_als.py` (score.json to a Live 12.4.16-verified set) and `scripts/check_als.py` (its QA). Adapt the role tables to the piece. A runnable demo is `python3 examples/make_example.py`.
