# als-generator

Generate Ableton Live Sets (`.als`) from Python, using only the standard library.

An `.als` file is gzip-compressed XML. This repository holds verified code and notes for writing the sets Live 12 opens: audio tracks with Arrangement clips, MIDI clips, returns, stock-device chains taken from Live's own presets, sidechains, locators, tempo and odd time signatures such as 13/16, plus a structural checker.

It is also written as an AI agent skill (`SKILL.md` plus `references/`), so Claude Code, Codex and similar agents can use it.

Ableton and Ableton Live are trademarks of Ableton AG. This project is not affiliated with or endorsed by Ableton. No Ableton files are included; device presets are read from your own Live installation at build time.

## Why this exists

A comparison on 2026-11-20: the same model (Claude Sonnet) writing an `.als` from memory, without this skill, crashed Live 12.4.16 twice even for a simple set with no devices, and the set with devices was refused as "corrupt". Generating with this skill, three sets opened on the first try (12 to 16 audio tracks, up to 1,341 arrangement clips, 4/4 and 13/16).

From memory, only the rough skeleton comes out right. The model wrote Live 11's `MasterTrack` and could write only about half of the element types Live 12 uses. The details that matter (ID rules, list-member Ids, dangling references, warp markers, sample CRCs) are what this repository records.

## Quick start

Requirements: Python 3 and Ableton Live 12 installed (the scripts read stock presets from its Core Library). The scripts never start Live.

```bash
git clone https://github.com/daitomanabe/als-generator
cd als-generator
python3 examples/make_example.py
```

This synthesizes five short WAV files, writes two score files, builds `Example 4-4.als` and `Example 13-16.als` under `examples/out/Example Project/`, and runs the checker on both. Save your current Live set first, then open the `.als` files yourself.

Core Library lookup: the `ABLETON_CORE_LIBRARY` environment variable if set, otherwise `/Applications/Ableton Live 12*.app/Contents/App-Resources/Core Library`. Suite, Standard, Intro and Lite are all searched. The presets used here were checked on a Suite installation; some editions may not ship every preset, and the build then stops with a "preset not found" error.

## score.json

`scripts/build_als.py` turns a score into a set:

```json
{
  "title": "My Set", "tempo": 120.0, "bars": 8, "time_signature": [4, 4],
  "samples_dir": "path/to/Project/Samples/Imported",
  "locators": [{"beat": 0.0, "name": "Intro"}],
  "tracks": [
    {"name": "Kick", "role": "kick", "volume_db": -3.0, "pan": 0.0,
     "send_a_db": -12.0, "send_b_db": -70.0, "send_c_db": -70.0,
     "clips": [{"sample": "kick.wav", "beat": 0.0, "length_beats": 16, "gain_db": 0.0}]}
  ]
}
```

```bash
python3 scripts/build_als.py score.json --out "Project/My Set.als"
python3 scripts/check_als.py "Project/My Set.als" score.json
```

- Beats are quarter notes; a 13/16 bar is 3.25 beats. `samples_dir` is relative to the repository root, or absolute.
- Each `role` (kick, snare, hats, sub, pad, strike, bass, ...) picks a colour, a high-pass frequency and sidechain settings from the tables at the top of `build_als.py`. They are examples: edit them to fit your piece, and keep `check_als.py` in step.
- The output has Arrangement clips (Beats warp at the file's own speed, no loop, 5 ms fade-out), three returns (reverb, delay, saturator and redux), and a master chain (EQ Eight, Bass Mono, Limiter).

## MIDI-only sets

`references/als_generator.py` builds sets with MIDI tracks and clips:

```python
from als_generator import ALSGenerator

gen = ALSGenerator(tempo=120)
t = gen.add_midi_track("Bass", color=7)
gen.add_clip(t, clip_start=0, clip_length=4, clip_name="Loop", notes=[(36, 0.0, 0.5, 100), (38, 2.0, 0.25, 110)])
gen.save("output.als")
```

## Hard QA gates

A set is not delivered unless these pass (details in `references/qa-gates.md`; `scripts/check_als.py` implements them):

1. gzip is intact, and 2. the XML parses.
3. `NextPointeeId` is above every Id in the file.
4. Ids in the Pointee namespace (Pointee, AutomationTarget, ModulationTarget, ControllerTargets) are unique.
5. Every member of every list (Devices, Tracks, Events, WarpMarkers, ...) has an `Id`.
6. No dangling references: GrooveId, PointeeId and routing targets all resolve inside the set.

Passing them is not a Live readback.

## Use as an agent skill

The repository root is the skill folder, so it installs by cloning:

```bash
git clone https://github.com/daitomanabe/als-generator ~/.claude/skills/als-generator
```

For Codex or another agent, clone it into the skills folder that agent reads. `SKILL.md` is short and points to `references/` for the details.

## What was verified, and limits

- Environment: macOS, Ableton Live 12.4.16 Suite, Python 3.
- Sets built with `scripts/build_als.py` opened in Live 12.4.16. That the structure loads was confirmed; the sound and the meaning of some values (Reverb wet, Delay sync, sidechain effect, how a 13/16 signature is displayed) were not checked on Live's screen. Such items are marked "not verified" in `references/`. The two example sets from `examples/make_example.py` pass the checker but have not themselves been opened in Live.
- Opening in Live is a manual step. A malformed set can crash Live itself, not just show a "corrupt" dialog, so save your current set before opening a generated one.
- Plugin (VST/AU) devices need a template saved by hand; see `references/plugin-devices.md`.

## License

MIT. See `LICENSE`. Ableton and Ableton Live are trademarks of Ableton AG. This project is not affiliated with or endorsed by Ableton. No Ableton files are included; device presets are read from your own Live installation at build time.
