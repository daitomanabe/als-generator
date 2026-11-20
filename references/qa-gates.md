# Structural checks (QA gates)

**A structural check and confirming that Live can open the set are different things.** Even when every check of gzip, XML, Ids, NextPointeeId and list Ids passes, Live may not open the set
(2026-11-13: a dangling GroovePool reference). Once the checks pass, the last step is to open it in Live and see.
When Live has the user's set open and running, do not open anything from here (it would replace the current set). **Ask the user to save, then open it themselves**
(a broken set can take down Live itself instead of showing a corrupt dialog. 2026-11-20: a set written from memory crashed Live 12.4.16 twice with `std::out_of_range map::at`).

The rules for IDs, list Ids and dangling references are in `format.md` (ID management, using bundled sets as templates). This file is the checking procedure.
Reference implementation of the checks: `scripts/check_als.py` (below).

## Hard QA Gates for All ALS

To prevent Ableton's `corrupt and cannot be loaded`, the following are mandatory whether the set is Session or Arrangement.

1. **gzip integrity**: `gzip -t file.als` succeeds.
2. **XML syntax**: `gzip -dc file.als > check.xml` and `xmllint --noout check.xml`, or a Python XML parser reads it to the end.
3. **NextPointeeId**: scan the maximum `Id` / `PointeeId Value` in the XML and satisfy `NextPointeeId > max_xml_id`.
4. **Pointee namespace duplicates**: the `Id`s of `Pointee`, `AutomationTarget`, `ModulationTarget`, `*ModulationTarget` and `ControllerTargets.*` must not repeat.
5. **List-member Ids** (added 2026-10-10): every element inside `Devices`, `Tracks`, `Envelopes`, `Events`, `ClipSlotList`, `Scenes`, `WarpMarkers`,
   `TimeSignatures`, `Sends`, `SendsPre` (and the inner `Locators`, `AutomationLanes`) has an `Id`.
   Ableton reports `corrupt and cannot be loaded. (Not all list members have Ids. (at line L, column C))`.
   Typical cause: putting an .adv device into `<Devices>` without an `Id`. `list_ids(root)` in `references/native_device_chain.py` must be empty
   (0 false positives on three sets saved by Live 12.4; four devices detected in a broken als).
6. **Dangling references** (added 2026-11-13): a value that points at something by Id must point at something inside the same set.
   - `GrooveSettings/GrooveId` of an `AudioClip` / `MidiClip` is `-1` or one of the `Id`s in `LiveSet/GroovePool/Grooves/Groove`.
     If not: `corrupt and cannot be loaded. (GroovePool corrupted)`. Clips in bundled templates (Quick Start Song.als and others)
     may point at a groove, so set it to `-1` after copying (if you need the groove, copy the `Groove` element into `GroovePool`).
   - `PointeeId Value` is one of the Pointee-namespace `Id`s in the set (the set from check 4 above). After copying clips or tracks and renumbering Ids,
     the clip's `Envelopes` (`ClipEnvelope/EnvelopeTarget/PointeeId`) point at the source track, so empty them or repoint them.
   - The `Track.N` in a routing `Target` (such as `AudioIn/Track.N/TrackOut`) is the `Id` of a track in the set.
   Even if 1 to 5 all pass, Live will not open the set if 6 fails. With 6 also passing, the last step is still to open it in Live
   (when Live has the user's set open and running, do not open it from here. Opening replaces the current set. Ask the user to open it).

Example check:

```python
import gzip
from xml.etree import ElementTree as ET

max_xml_id = 0
next_pointee = None
pointee_ids = set()
duplicate_pointee_ids = []

def is_pointee_namespace_id_tag(tag):
    return (
        tag == "Pointee"
        or tag == "AutomationTarget"
        or tag.endswith("ModulationTarget")
        or tag.startswith("ControllerTargets.")
    )

with gzip.open("set.als", "rb") as f:
    for _, elem in ET.iterparse(f, events=("end",)):
        for attr in ("Id", "LomId", "LomIdView"):
            value = elem.attrib.get(attr)
            if value is not None:
                max_xml_id = max(max_xml_id, int(value))
        if elem.tag == "PointeeId":
            max_xml_id = max(max_xml_id, int(elem.attrib["Value"]))
        if elem.tag == "NextPointeeId":
            next_pointee = int(elem.attrib["Value"])
        if elem.attrib.get("Id") is not None and is_pointee_namespace_id_tag(elem.tag):
            pointee_id = int(elem.attrib["Id"])
            if pointee_id in pointee_ids:
                duplicate_pointee_ids.append(pointee_id)
            pointee_ids.add(pointee_id)
        elem.clear()

assert next_pointee is not None
assert next_pointee > max_xml_id
assert not duplicate_pointee_ids

# 5: list-member Ids
import sys; sys.dont_write_bytecode = True        # do not create __pycache__ in the skill folder
from native_device_chain import list_ids          # put references/ on sys.path
root = ET.fromstring(gzip.open("set.als").read())
assert not list_ids(root)

# 6: dangling references (GrooveId and PointeeId)
grooves = {g.get("Id") for g in root.findall("LiveSet/GroovePool/Grooves/Groove")}
for clip in root.iter():
    if clip.tag in ("AudioClip", "MidiClip") and clip.find("GrooveSettings/GrooveId") is not None:
        gid = clip.find("GrooveSettings/GrooveId").get("Value")
        assert gid == "-1" or gid in grooves, ("GrooveId", gid)
pointee = {e.get("Id") for e in root.iter() if e.get("Id") is not None and is_pointee_namespace_id_tag(e.tag)}
assert not ({e.get("Value") for e in root.iter("PointeeId")} - pointee)
```

## Hard QA Gates for Session View ALS

To never produce Ableton's `corrupt and cannot be loaded` / `Slot count mismatch`, the following are mandatory stop conditions for an ALS that places clips in Session View.

1. **Check every `ClipSlotList`**: not only the target AudioTracks but every element found by `.//ClipSlotList` (FreezeSequencer, ReturnTrack, MainTrack, PreHearTrack ...). If even one differs from the number of Scenes, fail.
2. **Do not leave a fixed 8 slots**: if a helper's `xml_clip_slot_list()` or the Return/PreHear/Freeze parts generate 8 slots or an empty `ClipSlotList`, a Session View ALS must replace them with as many empty slots as there are Scenes.
3. **Number of Scenes = number of slots everywhere**: `len(./LiveSet/Scenes/Scene) == expected_clips` and, for every `.//ClipSlotList`, `len(./ClipSlot) == len(Scenes)`.
4. **Do not mix Session-only and Arrangement-only**: a Session View set puts `AudioClip` under `ClipSlotList/ClipSlot/ClipSlot/Value/AudioClip` and has 0 `Sample/ArrangerAutomation/Events/AudioClip`. An Arrangement View set is the reverse, and check that explicitly.
5. **Check warp on every clip**: Session View `AudioClip`s as well as Arrangement ones must all have `IsWarped=true`, a `WarpMarkers` element, and a `BeatTime` that corresponds to the intended number of bars.
6. **Run gzip/XML/structure checks before delivery**: besides `gzip -dc file.als > check.xml` and `xmllint --noout check.xml`, check with Python/XML the number of Scenes, all ClipSlotLists, Session/Arrangement clips, WarpMarkers and sample references. Do not deliver on any mismatch.

Example check:

```python
import gzip
from xml.etree import ElementTree as ET

with gzip.open("set.als", "rb") as f:
    root = ET.fromstring(f.read())

scenes = root.findall("./LiveSet/Scenes/Scene")
for csl in root.findall(".//ClipSlotList"):
    assert len(csl.findall("./ClipSlot")) == len(scenes)

session_clips = root.findall(".//ClipSlotList/ClipSlot/ClipSlot/Value/AudioClip")
arrangement_clips = root.findall(".//Sample/ArrangerAutomation/Events/AudioClip")
assert len(session_clips) == len(scenes)
assert len(arrangement_clips) == 0

for clip in session_clips:
    assert clip.find("IsWarped").get("Value") == "true"
    markers = clip.findall("./WarpMarkers/WarpMarker")
    assert len(markers) >= 2
```

---

## Self-check before delivery

Assert with gunzip + ElementTree: number of clips == expected, every clip span satisfies `0 <= start < end <= bars*4`, every `FileRef/RelativePath` exists on disk,
the master's `MainTrack//Tempo/Manual` matches, number of locators == number of sections, `NextPointeeId` > the largest Id in the file. Do not deliver an ALS that fails
(one production pipeline ran this as `als.self_check`).

## What `scripts/check_als.py` implements

`python3 scripts/check_als.py <set.als> [score.json]` (prints PASS/FAIL, exit 1 on any FAIL). Correspondence with the gates above:
- 1 gzip, 2 XML, 3 NextPointeeId, 4 Pointee namespace, 5 list-member Ids, 6 dangling references (6a GrooveId, 6b PointeeId, 6c unique track Ids, 6d `Track.N` in routing, 6e ClipSlot count per track == number of scenes)
- With a `score.json` (items matched to the output of `build_als.py`): existence of `RelativePath`, `OriginalFileSize`, CRC, `DefaultDuration`, `DefaultSampleRate`, loop off and WarpMode Beats,
  3 returns and their device order (Reverb, Delay, Saturator -> Redux2), `SendsPre` 3, Sends 3 on each track, no solo, returns' FreezeSequencer empty,
  sidechain targets, master devices (Eq8 -> StereoGain -> Limiter), time signature and tempo, track names and order, clip positions, lengths and samples matching the score (1e-6 beat), no overlaps within a track, locators
- The Session View gates (above) are not implemented (`build_als.py` makes Arrangement sets)
