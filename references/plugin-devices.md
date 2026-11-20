# VST/AU plugin devices

How to copy a plugin device (`PluginDevice`) from a template you saved by hand, and how to automate its parameters.
Stock (bundled) devices can be built from .adv files, see `native-devices.md`. ID rules are in `format.md`.

## Copy from a template: never write the device XML from scratch

For a plugin device, parse a **`template.als` saved by hand** (with the group, return and plugin slots in it), take the Ids and device chain from it, and inject clips and automation.
Generating a plugin `<Device>` block from scratch breaks the set (corrupt).

How to copy (the approach of one production pipeline's `extract_device_template` / `load_device`):
1. Find the `<PluginDevice Id="...">...</PluginDevice>` block with **a scan that counts nested closing tags** (PluginDevice can nest, so do not grab the first `</PluginDevice>` with a regex).
2. Replace the `Id` of every element that carries an Id with a placeholder such as `__ID_<n>__`. The element kinds that carry an Id are
   **PluginDevice, AutomationTarget, ModulationTarget, Pointee, MidiCCOnOffThresholds**.
3. Build a map of `parameter name -> placeholder number` by scanning
   `<PluginFloatParameter><ParameterName Value="..."/> ... <AutomationTarget Id="__ID_n__">`
   (VST3 **reserves 128 parameter slots in advance**; the ones with names are the real parameters, the rest are empty).
4. Instantiate: replace each `__ID_n__` with a newly allocated Id.
   **So read the PointeeId of the automation from the template; do not allocate it yourself.**

## Plugin parameter automation (baking envelopes)

`AutomationEnvelopes/Envelopes/AutomationEnvelope` -> `EnvelopeTarget/PointeeId` (the Id of the parameter's AutomationTarget obtained from the template above) -> `Automation/Events/FloatEvent`.
The anchor (`Time="-63072000"`) and the one-block-per-track rule are in the automation section of `format.md`. In addition:
- The remaining event times are `Time = (bar-1)*4`.
- **VST3 automation values are in plain units** (degrees, dB, beats ...). Before writing to FloatEvent, **normalize to 0-1** per parameter with the plugin manifest's `plain_min` / `plain_max`
  (usually `ableton_val = native_val / param_max`, or `(native_val - min) / (max - min)` for those with an offset).
- **PluginFloatParameter metadata is required**: without `ParameterName`, `ParameterId` (the VST3 hash) and `VisualIndex`, Live does not recognize the automation (confirmed with one synth plugin).
- The same method can bake a **track Volume** envelope: point `PointeeId` at the Id of the track Volume's `AutomationTarget` (noted when the mixer was written), and use the Volume range from `format.md`.
- Stock-device automation values differ from the plugin's 0-1 normalization: they are in the parameter's own units (`native-devices.md`).

Shape of the envelope XML:
```xml
<AutomationEnvelopes>
  <Envelopes>
    <AutomationEnvelope Id="0">
      <EnvelopeTarget>
        <PointeeId Value="5" />           <- the Id of the parameter's AutomationTarget
      </EnvelopeTarget>
      <Automation>
        <Events>
          <FloatEvent Id="0" Time="-63072000" Value="0.035" />  <- initial-value anchor
          <FloatEvent Id="1" Time="0" Value="0.035" />
          <FloatEvent Id="2" Time="0.25" Value="0.036" />
          ...
        </Events>
      </Automation>
    </AutomationEnvelope>
  </Envelopes>
</AutomationEnvelopes>
```
