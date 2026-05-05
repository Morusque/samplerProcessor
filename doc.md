# Sampler ADV Processor Documentation

This document is split into two parts:

- User documentation: how to use the tool and what the controls mean.
- Internal ADV notes: implementation details and reverse-engineered Ableton Sampler `.adv` findings.

## User Documentation

### Purpose

Sampler ADV Processor is a desktop tool for inspecting and batch-editing Ableton Sampler `.adv` presets. It is aimed at sampling workflows where a long recording or a rough preset needs to become a structured Sampler instrument.

Common uses:

- Split one long sample into several zones.
- Refine zone start and end points.
- Detect root notes and detune values.
- Detect sustain and release loop points.
- Spread, sort, or remap key, velocity, and chain ranges.
- Apply common Sampler defaults across a preset.
- Edit hidden or hard-to-reach Sampler parameters faster than in Live.

### Basic Workflow

1. Open an existing `.adv`, or drop an audio file to create a new preset from the scaffold.
2. Select the zone you want to inspect, if needed.
3. Open only the processing panels you need.
4. Check the individual parameters you want to write.
5. Click `Apply`.
6. Save with `Save as...`, or use `Overwrite + backup` when you intentionally want to replace the current preset.

Unchecked parameters are left as they are in the `.adv`.

### Templates

Templates are JSON files stored in `templates/`.

Templates save:

- Global parameter values.
- Global write checkboxes.
- Processing panel state.
- Template comments.

Templates do not save selected-zone edits, loop editor state, or range editor state. This is intentional so a template can be reused on different presets without carrying zone-specific data.

The default template is loaded from `templates/default values 01.json` when present.

### Opening Existing ADV Files

Opening an existing `.adv` preserves the preset structure and reads values from the file. Generic parameter panels use the current ADV content when available, and synthesize known missing groups only when a checked parameter needs to be written.

Validated example ADV files in `testPresets01 Project/adv presets` are useful references for:

- Root note placement.
- Start and end detection.
- Typical Sampler metadata.

They should not be treated as perfect references for:

- Exact detune values.
- Exact loop point positions.
- Zero-crossing or similarity-optimized loop positions.

### Creating a Preset From Audio

Dropping an audio file creates a new ADV from `test01.adv`, then rewrites the first zone to point at the dropped sample.

The tool writes:

- Zone name from the audio file stem.
- `SampleStart = 0`.
- `SampleEnd = last valid sample index`.
- `DefaultDuration = actual frame count`.
- Initial sustain and release loop bounds across the zone.
- Sample path metadata.

This matters because Live-authored ADV files use `SampleEnd` as the last valid frame index, not as the total frame count.

### Split Zones

`Split zones` replaces the current zone set with multiple zones.

Modes:

- `detect`: sustained-note level gating. This is the main split mode for sampled notes.
- `grid`: tempo/grid-based splitting.

Important controls:

- `Trigger threshold`: level threshold for detecting note starts.
- `Linear -> log %`: changes the detection profile so quieter notes can become easier to detect.
- `Stop hysteresis %`: stop threshold relative to the start threshold.
- `Start placement`: chooses whether split starts are written at the threshold crossing or at the strongest local attack inside the gated region.
- `Include first zone from start`: creates an initial slice from the original zone start to the first detected note.

`Start placement` only affects split/gate detection and split preview. If `Split zones` is off, it has no processing effect.

### Start / End Refinement

Start/end refinement adjusts each zone’s sample start and sample end without creating new zones.

Useful controls:

- `Stop when release goes under threshold`: detects where the useful release ends.
- `Next activity threshold`: prevents one zone from extending into the next detected activity.
- `Shift start by` / `Shift stop by`: offsets refined boundaries after detection.

Offsets can use units such as samples, milliseconds, seconds, percent, beat units, or wavecycles depending on the row.

### Loop and Release Loop

The `Loop` and `Release loop` panels are expanders. Opening the panel shows preview overlays, but individual checkbox rows decide which ADV values are written.

Loop rows:

- `Start`: writes loop start.
- `Stop`: writes loop stop.
- `Crossfade`: writes loop crossfade according to the selected policy.
- `Loop-point search range`: controls how far the detector may search around the target.
- `Type`: writes loop mode.

Release loop rows are similar, except release loop stop is the sample stop.

Loop types:

- Sustain loop: `off`, `loop`, `back-and-forth`.
- Release loop: `off`, `loop`, `back-and-forth`.

Crossfade policies:

- `No fade`: writes zero crossfade.
- `Longest possible`: writes the largest valid crossfade.
- `One waveform`: writes roughly one waveform period when pitch is known.
- `Custom`: writes the requested custom amount.

The largest valid loop crossfade is limited by both loop length and available audio before the loop start:

```text
max crossfade = min(loop length, loop start - sample start)
```

### Pitch Detection

Pitch detection can write root note and/or detune.

Controls:

- `Detect root note`: writes `RootKey`.
- `Detect detune`: writes zone detune in signed cents.
- `Diapason Hz`: reference tuning, usually 440.
- Pitch window start/stop: limits the audio region used for pitch detection.
- Extended harmonic correction: optional correction for sustained pitched material.

The current pitch detection is based on autocorrelation-style analysis with harmonic correction logic. It works best on clear sustained pitch and can be unreliable on untuned percussion, noisy attacks, bells, or sounds with strong ambiguous partials.

### Mapping, Velocity, Chain, and Sorting

Mapping tools operate on zone ranges.

Common tools:

- `Spread key zones`: spreads zones by root key or selected strategy.
- `Set key / velo / chain / detune from filename`: parses permissive filename tokens.
- `Multiple notes case`: handles several zones sharing the same playback area.
- `Crossfade between zones`: expands key, velocity, or chain ranges around boundaries.
- `Sort zones`: reorders zones using selected criteria.

Filename mapping is permissive and intended for structured names. It is best tested on copies before applying to a large preset.

### Default Preset Settings

These settings write preset-wide or shared Sampler values.

Main groups:

- `Preset basics`: tune scale, voice count, round robin settings.
- `Envelope`: global amplitude envelope timing and shape.
- `LFO parameters`: LFO 1, LFO 2, LFO 3, and their related parameters.
- `MIDI parameters`: pitch bend ranges and modulation routing.
- `Filter settings`: filter and shaper parameters.
- `Aux envelope parameters`: auxiliary envelope and modulation destinations.
- `Pitch envelope parameters`: pitch envelope parameters.
- `Osc parameters`: oscillator/sub-oscillator parameters.
- Collapsed sections such as Player, Global Pitch, Amp/Pan, Envelope Extras, Aux Envelope, Multisample Map, and Bonus.

Bonus contains parameters that appear hidden, legacy, uncertain, duplicated elsewhere, or less central to normal Live UI workflows.

### File Operations

Current file operations include:

- `Save as...`: writes a new `.adv`.
- `Overwrite + backup`: writes a backup first, then overwrites the current `.adv`.
- Sample path tools such as relative path rewrite or relink/copy workflows.

File operations can affect external sample paths. Use `Save as...` or keep backups when testing path changes.

### Preview and Responsiveness

The waveform preview updates after a short debounce. This means fast typing waits briefly before recomputing the preview, instead of recomputing on every digit.

Debouncing is time-based. Hysteresis is value-threshold-based. Debouncing is used here because text input naturally produces temporary invalid or incomplete intermediate values.

## Internal ADV Notes

### File Format

Ableton `.adv` files are gzip-compressed XML.

The tool reads them with `gzip`, parses XML with `xml.etree.ElementTree`, and writes gzip output again.

### Root Structure

The expected root contains a `MultiSampler` element. Most Sampler data lives under that node.

Important branches include:

- `Player`
- `Player/MultiSampleMap`
- `Player/MultiSampleMap/SampleParts`
- `VolumeAndPan`
- `Globals`
- `Lfo`
- `AuxLfos.*`
- `Filter`
- `AuxEnv`
- `Pitch/Envelope`

### Sample Zone Metadata

Each zone is usually a `MultiSamplePart`.

Important fields:

- `SampleStart`
- `SampleEnd`
- `RootKey`
- `Detune`
- `TuneScale`
- `SustainLoop`
- `ReleaseLoop`
- `SampleRef`

Observed convention:

- `SampleRef/DefaultDuration` is the total frame count.
- `SampleEnd` is the last valid frame index.
- A full-file zone with `DefaultDuration = N` should use `SampleStart = 0` and `SampleEnd = N - 1`.

This was confirmed by the scaffold and validated presets. The audio-created path now follows this convention.

### Loop Metadata

Loop fields:

- `Start`
- `End`
- `Mode`
- `Crossfade`
- `Detune`

Observed loop mode values:

- Sustain `off = 0`
- Sustain `loop = 1`
- Sustain `back-and-forth = 2`
- Release `off = 0`
- Release `loop = 3`
- Release `back-and-forth = 2`

The release loop uses `3` for normal loop in observed Live 12 files.

Loop crossfade is constrained by available audio before the loop start. The tool uses:

```text
max crossfade = min(loop length, loop start - sample start)
```

`Longest possible` now means that maximum. Earlier versions used half loop length, which made the visual result look like 50% of the possible fade.

### Routing Connections

Routing connection values are direct integer enums.

Confirmed:

- `0 = Off`

The routing list then continues with modulation destinations such as Sample Selector, Sample Offset, Loop Start, Loop Length, Release Loop, Pitch, Filter, Volume, Panorama, and LFO-related targets.

`test01.adv` was updated with routing connections set to Off and confirmed that Live writes `Connection Value="0"` for Off.

### Filter Enums

Observed / implemented filter mappings:

- Filter type: lowpass, highpass, bandpass, notch, morph.
- LP/HP circuit: Clean, OSR, MS2, SMP, PRD.
- BP/NoMo circuit: Clean, OSR.
- Slope: 12 or 24, represented by boolean values.

`LegacyType` is treated as hidden.

### Envelope Loop Mode Enum

Envelope loop modes use:

- `none`
- `loop`
- `beat`
- `sync`
- `trigger`

This enum is used for:

- Volume envelope loop mode.
- Aux envelope loop mode.
- Pitch envelope loop mode.
- Sub oscillator envelope loop mode.
- Filter envelope loop mode.

### LFO Structure

Observed structure:

- `Lfo` corresponds to Live’s LFO 1.
- `AuxLfos.0` corresponds to LFO 2.
- `AuxLfos.1` corresponds to LFO 3.

The tool exposes all three LFO panels even for scratch presets. Some LFO 1 parameters such as smooth, attack, retrigger, and width appear hidden or not visible in the main Live LFO 1 UI, so they are grouped as bonus parameters.

### MIDI Pitch Bend

Pitch bend ranges are stored under:

- `Globals/PitchBendRange`
- `Globals/MpePitchBendRange`

They are shown in the MIDI section because they are MIDI behavior, not Global Pitch modulation.

### Hidden / Bonus Parameters

The tool keeps uncertain or hidden parameters accessible but out of the primary workflow.

Examples:

- Player loop modulators.
- Reverse / Snap.
- Interpolation mode.
- Volume/Pan LFO amount duplicates.
- One-shot envelope fields.
- Env include attack.
- Layer crossfade.
- Round robin seed.
- Filter LegacyQ, X, ModByPitch, ModByVelocity, ModByLfo.

These are not necessarily unsafe. They are just not yet validated as normal user-facing controls.

### Templates and Synthesized Nodes

Some ADV nodes are absent until Live creates them. The tool can synthesize known parameter groups from templates when a checked parameter needs to be written.

Known synthesized groups include:

- LFOs.
- Filter.
- Aux envelope.
- Pitch envelope.
- Oscillator/sub-oscillator.
- MIDI routing values.

Unchecked parameters should not create or overwrite ADV values.

### Validated Preset Use

Validated presets are considered good examples for:

- Root note.
- Start detection.
- End detection.
- General Sampler metadata conventions.

They are not considered authoritative for:

- Fine detune.
- Exact loop points.
- Zero crossing quality.
- Similarity-optimized loops.

Known exceptions:

- Mostly untuned percussion can have no meaningful root note.
- Bell-like sounds can have subjective or partial-dominated root notes.

### Known Uncertainties

Open areas that need careful testing:

- Exact visible/hidden status of some Live UI parameters.
- Full routing enum alignment beyond confirmed `0 = Off`.
- File operation UX and safety rules.
- Threading/cancellation behavior for long processing runs.
- Exported audio-created ADV behavior after the SampleEnd fix should be tested in Live.

