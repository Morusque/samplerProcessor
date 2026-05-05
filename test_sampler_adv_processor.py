import importlib.util
import copy
import tempfile
import unittest
import wave
import statistics
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).with_name("sampler_adv_processor.py")
SPEC = importlib.util.spec_from_file_location("sampler_adv_processor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeVelocityModel:
    def __init__(self, amplitudes):
        self.zones = []
        self.audio_map = {}
        for index, amplitude in enumerate(amplitudes):
            zone = {
                "RootKey": str(60 + index),
                "KeyRange": {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
                "SelectorRange": {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
                "VelocityRange": {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"},
            }
            self.zones.append(zone)
            samples = MODULE.np.concatenate([
                MODULE.np.zeros(800, dtype=MODULE.np.float32),
                MODULE.np.full(2400, amplitude, dtype=MODULE.np.float32),
                MODULE.np.zeros(400, dtype=MODULE.np.float32),
            ])
            self.audio_map[id(zone)] = SimpleNamespace(samples=samples, sample_rate=48000)

    def zone_count(self):
        return len(self.zones)

    def get_zone(self, index):
        return self.zones[index]

    def read_range(self, zone, tag):
        values = zone[tag]
        return dict(values)

    def write_range(self, zone, tag, vals):
        zone[tag] = dict(vals)


class FakeVelocityAudioCache:
    def __init__(self, model):
        self.model = model

    def get_zone_audio(self, _model, zone):
        return self.model.audio_map[id(zone)]


class FakeRangeModel:
    def __init__(self, ranges):
        self.zones = []
        for index, (key_range, velocity_range, selector_range) in enumerate(ranges):
            zone = {
                "RootKey": str(60 + index),
                "KeyRange": dict(key_range),
                "VelocityRange": dict(velocity_range),
                "SelectorRange": dict(selector_range),
            }
            self.zones.append(zone)

    def zone_count(self):
        return len(self.zones)

    def get_zone(self, index):
        return self.zones[index]

    def read_range(self, zone, tag):
        return dict(zone[tag])

    def write_range(self, zone, tag, vals):
        zone[tag] = dict(vals)

    def validate_range(self, vals, lo, hi):
        mn = MODULE.clamp_int(vals["min"], lo, hi)
        mx = MODULE.clamp_int(vals["max"], lo, hi)
        xmn = MODULE.clamp_int(vals["xfade_min"], lo, hi)
        xmx = MODULE.clamp_int(vals["xfade_max"], lo, hi)
        if mn > mx:
            mn, mx = mx, mn
        xmn = max(mn, min(xmn, mx))
        xmx = max(mn, min(xmx, mx))
        return {
            "min": str(mn),
            "max": str(mx),
            "xfade_min": str(xmn),
            "xfade_max": str(xmx),
        }


class FakeSortableModel:
    def __init__(self, zone_specs):
        self.zones = []
        for spec in zone_specs:
            self.zones.append({
                "Name": spec.get("name", ""),
                "RootKey": str(spec.get("root_key", 60)),
                "SampleStart": str(spec.get("sample_start", 0)),
                "KeyRange": dict(spec.get("key_range", {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"})),
                "VelocityRange": dict(spec.get("velocity_range", {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"})),
                "SelectorRange": dict(spec.get("selector_range", {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"})),
                "_sample_path": spec.get("sample_path", ""),
                "_relative_path": spec.get("relative_path", ""),
            })

    def zone_count(self):
        return len(self.zones)

    def get_zone(self, index):
        return self.zones[index]

    def read_range(self, zone, tag):
        return dict(zone[tag])

    def write_range(self, zone, tag, vals):
        zone[tag] = dict(vals)

    def reorder_zones(self, ordered_indices):
        self.zones = [self.zones[i] for i in ordered_indices]

    def extract_sample_path(self, zone):
        return zone.get("_sample_path", ""), zone.get("_relative_path", "")


class FakeMidiModel:
    def __init__(self, zone_specs, round_robin=False, round_robin_mode="0"):
        self.zones = []
        self.audio_map = {}
        for index, spec in enumerate(zone_specs):
            zone = {
                "Name": spec.get("name", "zone{}".format(index)),
                "RootKey": str(spec.get("root_key", 60)),
                "KeyRange": dict(spec.get("key_range", {"min": "60", "max": "60", "xfade_min": "60", "xfade_max": "60"})),
                "VelocityRange": dict(spec.get("velocity_range", {"min": "100", "max": "100", "xfade_min": "100", "xfade_max": "100"})),
                "SelectorRange": dict(spec.get("selector_range", {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"})),
                "SustainLoop": dict(spec.get("sustain_loop", {"start": "0", "end": "1000", "mode": "0", "crossfade": "0", "detune": "0"})),
                "ReleaseLoop": dict(spec.get("release_loop", {"start": "0", "end": "1000", "mode": "0", "crossfade": "0", "detune": "0"})),
            }
            self.zones.append(zone)
            self.audio_map[id(zone)] = SimpleNamespace(
                zone_start=int(spec.get("zone_start", 0)),
                zone_end=int(spec.get("zone_end", 1000)),
                sample_rate=int(spec.get("sample_rate", 48000)),
            )
        self.summary = {
            "round_robin": "true" if round_robin else "false",
            "round_robin_mode": str(round_robin_mode),
        }

    def zone_count(self):
        return len(self.zones)

    def get_zone(self, index):
        return self.zones[index]

    def read_range(self, zone, tag):
        return dict(zone[tag])

    def read_loop(self, zone, tag):
        return dict(zone[tag])

    def read_global_summary(self):
        return dict(self.summary)


class FakeMidiAudioCache:
    def __init__(self, model):
        self.model = model

    def get_zone_audio(self, _model, zone):
        return self.model.audio_map[id(zone)]


def make_loop_node(tag, start, end, mode="0", crossfade="0", detune="0"):
    loop = MODULE.ET.Element(tag)
    for child_tag, value in (
        ("Start", start),
        ("End", end),
        ("Mode", mode),
        ("Crossfade", crossfade),
        ("Detune", detune),
    ):
        node = MODULE.ET.SubElement(loop, child_tag)
        node.set("Value", str(value))
    return loop


def make_fake_zone_with_loops(sample_count):
    zone = MODULE.ET.Element("MultiSamplePart")
    for tag, value in (
        ("Name", "loop-zone"),
        ("RootKey", "60"),
        ("SampleStart", "0"),
        ("SampleEnd", str(sample_count)),
    ):
        node = MODULE.ET.SubElement(zone, tag)
        node.set("Value", str(value))

    zone.append(make_loop_node("SustainLoop", 0, 1))
    zone.append(make_loop_node("ReleaseLoop", 0, 1))
    return zone


class FakeLoopModel:
    def __init__(self, samples):
        self.zone = make_fake_zone_with_loops(len(samples))
        self.audio = SimpleNamespace(
            samples=samples,
            sample_rate=48000,
            zone_start=0,
            zone_end=len(samples),
        )

    def zone_count(self):
        return 1

    def get_zone(self, index):
        if index != 0:
            raise IndexError(index)
        return self.zone

    def read_loop(self, zone, tag):
        loop = MODULE.child(zone, tag)
        return {
            "start": MODULE.get_value(loop, "Start", ""),
            "end": MODULE.get_value(loop, "End", ""),
            "mode": MODULE.get_value(loop, "Mode", ""),
            "crossfade": MODULE.get_value(loop, "Crossfade", ""),
            "detune": MODULE.get_value(loop, "Detune", ""),
        }

    def write_loop(self, zone, tag, vals):
        loop = MODULE.child(zone, tag)
        MODULE.set_value(loop, "Start", vals["start"])
        MODULE.set_value(loop, "End", vals["end"])
        MODULE.set_value(loop, "Mode", vals["mode"])
        MODULE.set_value(loop, "Crossfade", vals["crossfade"])
        MODULE.set_value(loop, "Detune", vals["detune"])

    def clamp_loops_to_sample_bounds(self, zone):
        sample_start = int(float(MODULE.get_value(zone, "SampleStart", "0")))
        sample_end = int(float(MODULE.get_value(zone, "SampleEnd", "0")))
        for loop_tag in ("SustainLoop", "ReleaseLoop"):
            loop = MODULE.child(zone, loop_tag)
            start_node = MODULE.child(loop, "Start")
            end_node = MODULE.child(loop, "End")
            start_value = max(sample_start, min(int(float(start_node.attrib["Value"])), sample_end - 1))
            end_value = max(sample_start + 1, min(int(float(end_node.attrib["Value"])), sample_end))
            if start_value >= end_value:
                start_value = max(sample_start, end_value - 1)
            start_node.set("Value", str(start_value))
            end_node.set("Value", str(end_value))


class FakeLoopAudioCache:
    def __init__(self, model):
        self.model = model

    def get_zone_audio(self, _model, _zone):
        return self.model.audio


class FakeVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeNormalizeModel:
    def __init__(self, samples, volume="1.0"):
        self.zone = MODULE.ET.Element("MultiSamplePart")
        for tag, value in (
            ("Name", "normalize-zone"),
            ("Volume", volume),
            ("SampleStart", "0"),
            ("SampleEnd", str(len(samples))),
        ):
            node = MODULE.ET.SubElement(self.zone, tag)
            node.set("Value", str(value))
        self.audio = SimpleNamespace(
            samples=samples,
            sample_rate=48000,
            zone_start=0,
            zone_end=len(samples),
        )

    def zone_count(self):
        return 1

    def get_zone(self, index):
        if index != 0:
            raise IndexError(index)
        return self.zone


class FakeNormalizeAudioCache:
    def __init__(self, model):
        self.model = model

    def get_zone_audio(self, _model, _zone):
        return self.model.audio


def write_test_wav(path, frame_count=256, sample_rate=48000):
    path = Path(path)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frame_count)


class SamplerAdvProcessorTests(unittest.TestCase):
    def approved_preset_paths(self):
        root = Path(__file__).with_name("testPresets01 Project") / "adv presets"
        return sorted(root.glob("*.adv"))

    def split_detection_metrics(self, model, sample_data, sample_rate, mode):
        zone_starts = [
            int(MODULE.parse_number_from_text(MODULE.get_value(model.get_zone(i), "SampleStart", "0"), 0))
            for i in range(model.zone_count())
        ]
        zone_ends = [
            int(MODULE.parse_number_from_text(MODULE.get_value(model.get_zone(i), "SampleEnd", "0"), 0))
            for i in range(model.zone_count())
        ]
        zone_start = min(zone_starts)
        zone_end = max(zone_ends)
        samples = sample_data[zone_start:zone_end]
        if mode == "gate":
            onsets = MODULE.AudioAnalysis.detect_gate_onsets(
                samples,
                sample_rate,
                sensitivity=float(MODULE.DEFAULT_GATE_SPLIT_SENSITIVITY),
                min_duration_samples=int(MODULE.DEFAULT_GATE_SPLIT_MIN_DURATION),
                profile_compression_pct=float(MODULE.DEFAULT_GATE_PROFILE_COMPRESSION),
                stop_hysteresis_pct=float(MODULE.DEFAULT_GATE_STOP_HYSTERESIS_PCT),
                start_placement=MODULE.DEFAULT_GATE_START_PLACEMENT,
            )
        else:
            onsets = MODULE.AudioAnalysis.detect_onsets(
                samples,
                sample_rate,
                sensitivity=float(MODULE.DEFAULT_DETECTION_SPLIT_SENSITIVITY),
                min_duration_samples=int(MODULE.DEFAULT_DETECTION_SPLIT_MIN_DURATION),
                profile_compression_pct=float(MODULE.DEFAULT_DETECTION_PROFILE_COMPRESSION),
            )

        predicted = [zone_start + int(onset) for onset in onsets]
        manual = sorted(set(zone_starts))
        remaining = predicted[:]
        errors = []
        for manual_start in manual:
            if not remaining:
                break
            best = min(range(len(remaining)), key=lambda idx: abs(remaining[idx] - manual_start))
            errors.append(remaining.pop(best) - manual_start)
        abs_median = statistics.median([abs(err) for err in errors]) if errors else float("inf")
        return {
            "count_error": abs(len(predicted) - len(manual)),
            "abs_median_error": float(abs_median),
        }

    def load_model(self, filename):
        path = Path(__file__).with_name(filename)
        if not path.exists():
            if filename == "test02.adv":
                return self.build_test02_model()
            if filename == "test03.adv":
                path = Path(__file__).with_name("test01.adv")
        tree = MODULE.AdvCodec.load(path)
        return MODULE.SamplerAdvModel(tree, source_path=path)

    def build_test02_model(self):
        base_path = Path(__file__).with_name("test01.adv")
        tree = MODULE.AdvCodec.load(base_path)
        model = MODULE.SamplerAdvModel(tree, source_path=base_path)
        first_zone = model.get_zone(0)
        root_keys = ("48", "66", "72")
        container = model.sample_parts_container()
        while model.zone_count() > 1:
            container.remove(model.get_zone(model.zone_count() - 1))
            model.refresh()
        for _ in range(len(root_keys) - 1):
            container.append(copy.deepcopy(first_zone))
        model.refresh()
        for index, root_key in enumerate(root_keys):
            zone = model.get_zone(index)
            MODULE.set_value(zone, "RootKey", root_key)
            model.write_range(zone, "KeyRange", {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"})
            model.write_range(zone, "VelocityRange", {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"})
            model.write_range(zone, "SelectorRange", {"min": "0", "max": "0", "xfade_min": "0", "xfade_max": "0"})
        return model

    def test_adv_roundtrip_preserves_zone_count(self):
        model = self.load_model("test01.adv")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "roundtrip.adv"
            MODULE.AdvCodec.write(model.tree, out_path)
            reloaded = MODULE.SamplerAdvModel(MODULE.AdvCodec.load(out_path), source_path=out_path)

        self.assertEqual(reloaded.zone_count(), 1)
        self.assertEqual(reloaded.read_zone_summary(0)["name"], "testSample01")

    def test_hardcoded_scratch_defaults_match_typical_values(self):
        model = MODULE.SamplerAdvModel(MODULE.AdvCodec.load_default_scaffold())
        MODULE.apply_hardcoded_scratch_preset_defaults(model)

        self.assertEqual(model.zone_count(), 1)
        self.assertEqual(model.read_global_summary()["voices"], "32")
        self.assertEqual(MODULE.get_value_by_path(model.root, "Player/InterpolationMode"), "1")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Volume"), "-12")
        self.assertEqual(MODULE.find_first_value_node_by_tag(model.root, "UserName").attrib.get("Value"), "")
        self.assertEqual(model.read_global_summary()["round_robin"], "false")
        self.assertEqual(model.read_global_summary()["env_attack_ms"], "0.2")

    def test_create_model_from_audio_file_uses_hardcoded_scratch_defaults(self):
        gui = MODULE.SamplerAdvGui.__new__(MODULE.SamplerAdvGui)
        gui.model = None
        gui.adv_path = None

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "fresh.wav"
            write_test_wav(wav_path, frame_count=512, sample_rate=44100)

            MODULE.SamplerAdvGui.create_model_from_audio_file(gui, wav_path)

        self.assertIsNotNone(gui.model)
        self.assertEqual(gui.model.zone_count(), 1)
        self.assertEqual(gui.model.read_global_summary()["voices"], "32")
        self.assertEqual(MODULE.get_value_by_path(gui.model.root, "Player/InterpolationMode"), "1")
        self.assertEqual(MODULE.find_first_value_node_by_tag(gui.model.root, "UserName").attrib.get("Value"), "fresh")
        zone = gui.model.get_zone(0)
        self.assertEqual(MODULE.get_value(zone, "Name", ""), "fresh")
        self.assertEqual(MODULE.get_value(zone, "SampleStart", ""), "0")
        self.assertEqual(MODULE.get_value(zone, "SampleEnd", ""), "512")
        self.assertEqual([child.tag for child in gui.model.root], ["MultiSampler"])
        self.assertIsNone(gui.model.root.find("MultiSampler/AuxEnv/Slot/Value/SimplerAuxEnvelope"))
        self.assertIsNone(gui.model.root.find("MultiSampler/Pitch/Envelope/Slot/Value/SimplerPitchEnvelope"))
        self.assertIsNone(gui.model.root.find("MultiSampler/Player/SubOsc/Slot/Value/SimplerSubOsc"))
        self.assertIsNone(gui.model.root.find("MultiSampler/Filter/Slot/Value/SimplerFilter"))
        self.assertIsNone(gui.model.root.find("MultiSampler/AuxLfos.0/Slot/Value/SimplerAuxLfo"))

    def test_templates_ignore_zone_specific_state(self):
        gui = MODULE.SamplerAdvGui.__new__(MODULE.SamplerAdvGui)
        gui.zone_vars = {"name": FakeVar("zone-a"), "root_key": FakeVar("60")}
        gui.range_vars = {"key_min": FakeVar("0")}
        gui.loop_vars = {"sustain_start": FakeVar("10")}
        gui.template_comments_var = FakeVar("keep me")
        gui.global_vars = {"param_split_mode": FakeVar("gate"), "pitch_transpose_key": FakeVar("0")}
        gui.global_update = {"split_zones": FakeVar(False), "pitch_transpose_key": FakeVar(False)}
        gui.processing_update = {"split_zones": FakeVar(False)}
        gui._set_split_mode_visibility = lambda: None
        gui._refresh_visibility_rules = lambda: None
        gui.schedule_waveform_refresh = lambda: None

        data = MODULE.SamplerAdvGui.collect_template(gui)
        self.assertNotIn("zone_values", data)
        self.assertNotIn("range_values", data)
        self.assertNotIn("loop_values", data)
        self.assertEqual(data.get("comments"), "keep me")

        MODULE.SamplerAdvGui.apply_template(
            gui,
            {
                "comments": "useful for recorder fixes",
                "zone_values": {"name": "zone-b", "root_key": "72"},
                "range_values": {"key_min": "24"},
                "loop_values": {"sustain_start": "999"},
                "global_values": {"param_split_mode": "detection", "pitch_transpose_key": "12"},
                "global_update": {"pitch_transpose_key": True},
                "processing_update": {"split_zones": True},
            },
        )

        self.assertEqual(gui.zone_vars["name"].get(), "zone-a")
        self.assertEqual(gui.zone_vars["root_key"].get(), "60")
        self.assertEqual(gui.range_vars["key_min"].get(), "0")
        self.assertEqual(gui.loop_vars["sustain_start"].get(), "10")
        self.assertEqual(gui.template_comments_var.get(), "useful for recorder fixes")
        self.assertEqual(gui.global_vars["param_split_mode"].get(), "detect")
        self.assertEqual(gui.global_vars["pitch_transpose_key"].get(), "12")
        self.assertTrue(gui.global_update["pitch_transpose_key"].get())
        self.assertTrue(gui.processing_update["split_zones"].get())

    def test_scratch_audio_preset_synthesized_nodes_stay_under_multisampler(self):
        model = MODULE.SamplerAdvModel(MODULE.AdvCodec.load_default_scaffold())
        model.apply_global_values(
            {
                "param_lfo_manual::AuxLfos.0/Slot/Value/SimplerAuxLfo/Frequency": "6.25",
                "param_lfo_value::MidiCtrl.7/Feedback": "1",
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Freq": "987.6",
                "param_filter_manual::Shaper/Slot/Value/SimplerShaper/Amount": "23",
                "param_aux_env_manual::AuxEnv/Slot/Value/SimplerAuxEnvelope/AttackTime": "12.5",
                "param_pitch_env_manual::Pitch/Envelope/Slot/Value/SimplerPitchEnvelope/Amount": "-7",
                "param_sub_osc_manual::Player/SubOsc/Slot/Value/SimplerSubOsc/Type": "5",
            },
            {
                "param_lfo_manual::AuxLfos.0/Slot/Value/SimplerAuxLfo/Frequency": True,
                "param_lfo_value::MidiCtrl.7/Feedback": True,
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Freq": True,
                "param_filter_manual::Shaper/Slot/Value/SimplerShaper/Amount": True,
                "param_aux_env_manual::AuxEnv/Slot/Value/SimplerAuxEnvelope/AttackTime": True,
                "param_pitch_env_manual::Pitch/Envelope/Slot/Value/SimplerPitchEnvelope/Amount": True,
                "param_sub_osc_manual::Player/SubOsc/Slot/Value/SimplerSubOsc/Type": True,
            },
        )

        self.assertEqual([child.tag for child in model.root], ["MultiSampler"])
        self.assertIsNone(model.root.find("Lfo"))
        self.assertIsNone(model.root.find("AuxEnv"))
        self.assertIsNone(model.root.find("Pitch"))
        self.assertIsNone(model.root.find("Player"))
        self.assertIsNotNone(model.root.find("MultiSampler/Lfo"))
        self.assertIsNotNone(model.root.find("MultiSampler/AuxEnv"))
        self.assertIsNotNone(model.root.find("MultiSampler/Pitch"))
        self.assertIsNotNone(model.root.find("MultiSampler/Player"))

    def test_spread_key_zones_legacy_one_note_per_key_maps_to_interval_mode(self):
        model = FakeRangeModel([
            ({"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
             {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"},
             {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}),
            ({"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
             {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"},
             {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}),
            ({"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
             {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"},
             {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}),
        ])
        for index, zone in enumerate(model.zones):
            zone["RootKey"] = str(70 + index)

        MODULE.SamplerProcessors.spread_key_zones(
            model,
            {"param_key_spread_mode": "one note per key", "param_key_spread_first_note": "60"},
        )

        ranges = [model.read_range(zone, "KeyRange") for zone in model.zones]
        self.assertEqual(ranges[0]["min"], "0")
        self.assertEqual(ranges[0]["max"], "60")
        self.assertEqual(ranges[1]["min"], "61")
        self.assertEqual(ranges[1]["max"], "61")
        self.assertEqual(ranges[2]["min"], "62")
        self.assertEqual(ranges[2]["max"], "127")

    def test_grid_split_count_matches_expected(self):
        model = self.load_model("test01.adv")

        count = MODULE.SamplerProcessors.split_selected_zone_by_grid(
            model,
            0,
            {
                "param_grid_tempo": "100",
                "param_grid_every_number": "1",
                "param_grid_every_unit": "bar(s)",
                "param_grid_end_after_number": "3",
                "param_grid_end_after_unit": "beat(s)",
            },
        )

        self.assertEqual(count, 38)
        self.assertEqual(model.zone_count(), 38)

    def test_run_enabled_processors_grid_splits_all_zones(self):
        model = self.load_model("test02.adv")

        count = MODULE.SamplerProcessors.run_enabled_processors(
            model,
            None,
            {
                "param_split_mode": "grid",
                "param_grid_tempo": "100",
                "param_grid_every_number": "1",
                "param_grid_every_unit": "bar(s)",
                "param_grid_end_after_number": "3",
                "param_grid_end_after_unit": "beat(s)",
            },
            {"split_zones": True},
        )

        self.assertEqual(count, 114)
        self.assertEqual(model.zone_count(), 114)

    def test_spread_around_root_updates_expected_ranges(self):
        model = self.load_model("test02.adv")

        count = MODULE.SamplerProcessors.spread_around_root(model)
        self.assertEqual(count, 3)

        ranges = [model.read_range(model.get_zone(i), "KeyRange") for i in range(model.zone_count())]
        self.assertEqual(ranges[0]["min"], "0")
        self.assertEqual(ranges[0]["max"], "57")
        self.assertEqual(ranges[1]["min"], "58")
        self.assertEqual(ranges[1]["max"], "69")
        self.assertEqual(ranges[2]["min"], "70")
        self.assertEqual(ranges[2]["max"], "127")

    def test_spread_evenly_updates_expected_ranges(self):
        model = self.load_model("test02.adv")

        count = MODULE.SamplerProcessors.spread_evenly(model, key_min=24, key_max=95)
        self.assertEqual(count, 3)

        ranges = [model.read_range(model.get_zone(i), "KeyRange") for i in range(model.zone_count())]
        self.assertEqual((ranges[0]["min"], ranges[0]["max"]), ("24", "47"))
        self.assertEqual((ranges[1]["min"], ranges[1]["max"]), ("48", "71"))
        self.assertEqual((ranges[2]["min"], ranges[2]["max"]), ("72", "95"))

    def test_spread_one_note_per_key_updates_expected_ranges(self):
        model = self.load_model("test02.adv")

        count = MODULE.SamplerProcessors.spread_one_note_per_key(model)
        self.assertEqual(count, 3)

        ranges = [model.read_range(model.get_zone(i), "KeyRange") for i in range(model.zone_count())]
        roots = [MODULE.get_value(model.get_zone(i), "RootKey", "") for i in range(model.zone_count())]
        self.assertEqual((ranges[0]["min"], ranges[0]["max"]), (roots[0], roots[0]))
        self.assertEqual((ranges[1]["min"], ranges[1]["max"]), (roots[1], roots[1]))
        self.assertEqual((ranges[2]["min"], ranges[2]["max"]), (roots[2], roots[2]))

    def test_spread_first_note_interval_updates_expected_ranges(self):
        model = self.load_model("test02.adv")

        count = MODULE.SamplerProcessors.spread_first_note_interval(model, first_note=36, interval=12)
        self.assertEqual(count, 3)

        ranges = [model.read_range(model.get_zone(i), "KeyRange") for i in range(model.zone_count())]
        self.assertEqual((ranges[0]["min"], ranges[0]["max"]), ("0", "42"))
        self.assertEqual((ranges[1]["min"], ranges[1]["max"]), ("43", "54"))
        self.assertEqual((ranges[2]["min"], ranges[2]["max"]), ("55", "127"))

    def test_spread_first_note_interval_repeat_count_repeats_centers(self):
        full_velocity = {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"}
        full_selector = {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}
        model = FakeRangeModel([
            ({"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}, full_velocity, full_selector),
            ({"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}, full_velocity, full_selector),
            ({"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}, full_velocity, full_selector),
            ({"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}, full_velocity, full_selector),
        ])

        count = MODULE.SamplerProcessors.spread_first_note_interval(model, first_note=36, interval=12, repeat_count=2)
        self.assertEqual(count, 4)

        ranges = [model.read_range(model.get_zone(i), "KeyRange") for i in range(model.zone_count())]
        self.assertEqual((ranges[0]["min"], ranges[0]["max"]), ("0", "42"))
        self.assertEqual((ranges[1]["min"], ranges[1]["max"]), ("0", "42"))
        self.assertEqual((ranges[2]["min"], ranges[2]["max"]), ("43", "127"))
        self.assertEqual((ranges[3]["min"], ranges[3]["max"]), ("43", "127"))

    def test_velocity_distribution_linear_ranges(self):
        model = self.load_model("test02.adv")

        count = MODULE.SamplerProcessors.distribute_velocity_by_play_area(model, gamma=1.0)
        self.assertEqual(count, 3)

        ranges = [model.read_range(model.get_zone(i), "VelocityRange") for i in range(model.zone_count())]
        self.assertEqual((ranges[0]["min"], ranges[0]["max"]), ("1", "42"))
        self.assertEqual((ranges[1]["min"], ranges[1]["max"]), ("43", "85"))
        self.assertEqual((ranges[2]["min"], ranges[2]["max"]), ("86", "127"))

    def test_velocity_ranges_from_scores_uses_detected_gaps(self):
        ranges = MODULE.SamplerProcessors.velocity_ranges_from_scores([0.1, 0.3, 0.8])
        self.assertEqual(ranges, [(1, 18), (19, 82), (83, 127)])

    def test_spread_velocity_single_zone_covers_full_range(self):
        model = FakeVelocityModel([0.15])
        zone = model.get_zone(0)
        model.write_range(zone, "VelocityRange", {"min": "40", "max": "50", "xfade_min": "40", "xfade_max": "50"})

        count = MODULE.SamplerProcessors.distribute_velocity_by_play_area(model, gamma=1.0)

        self.assertEqual(count, 1)
        vel = model.read_range(zone, "VelocityRange")
        self.assertEqual((vel["min"], vel["max"]), ("1", "127"))

    def test_detect_velocity_assigns_lower_ranges_to_quieter_zones(self):
        model = FakeVelocityModel([0.15, 0.35, 0.75])
        audio_cache = FakeVelocityAudioCache(model)

        count = MODULE.SamplerProcessors.detect_velocity_by_play_area(model, audio_cache)

        self.assertEqual(count, 3)
        ranges = [model.read_range(model.get_zone(i), "VelocityRange") for i in range(model.zone_count())]
        self.assertEqual(ranges[0]["min"], "1")
        self.assertEqual(ranges[2]["max"], "127")
        self.assertEqual(int(ranges[0]["max"]) + 1, int(ranges[1]["min"]))
        self.assertEqual(int(ranges[1]["max"]) + 1, int(ranges[2]["min"]))
        self.assertLess(int(ranges[0]["max"]), int(ranges[1]["max"]))
        self.assertLess(int(ranges[1]["max"]), int(ranges[2]["max"]))

    def test_detect_velocity_single_zone_covers_full_range(self):
        model = FakeVelocityModel([0.15])
        zone = model.get_zone(0)
        model.write_range(zone, "VelocityRange", {"min": "40", "max": "50", "xfade_min": "40", "xfade_max": "50"})
        audio_cache = FakeVelocityAudioCache(model)

        count = MODULE.SamplerProcessors.detect_velocity_by_play_area(model, audio_cache)

        self.assertEqual(count, 1)
        vel = model.read_range(zone, "VelocityRange")
        self.assertEqual((vel["min"], vel["max"]), ("1", "127"))

    def test_sort_velocity_spreads_ranges_by_detected_loudness_order(self):
        model = FakeVelocityModel([0.75, 0.15, 0.35])
        audio_cache = FakeVelocityAudioCache(model)

        count = MODULE.SamplerProcessors.sort_velocity_by_play_area(model, audio_cache, gamma=1.0)

        self.assertEqual(count, 3)
        ranges = [model.read_range(model.get_zone(i), "VelocityRange") for i in range(model.zone_count())]
        self.assertEqual((ranges[1]["min"], ranges[1]["max"]), ("1", "42"))
        self.assertEqual((ranges[2]["min"], ranges[2]["max"]), ("43", "85"))
        self.assertEqual((ranges[0]["min"], ranges[0]["max"]), ("86", "127"))

    def test_sort_velocity_single_zone_covers_full_range(self):
        model = FakeVelocityModel([0.15])
        zone = model.get_zone(0)
        model.write_range(zone, "VelocityRange", {"min": "40", "max": "50", "xfade_min": "40", "xfade_max": "50"})
        audio_cache = FakeVelocityAudioCache(model)

        count = MODULE.SamplerProcessors.sort_velocity_by_play_area(model, audio_cache, gamma=1.0)

        self.assertEqual(count, 1)
        vel = model.read_range(zone, "VelocityRange")
        self.assertEqual((vel["min"], vel["max"]), ("1", "127"))

    def test_split_boundaries_from_onsets_can_skip_first_lead_in_zone(self):
        onsets = [1000, 3000, 5000]

        with_first = MODULE.SamplerProcessors.split_boundaries_from_onsets(
            0,
            7000,
            onsets,
            500,
            include_first_zone=True,
        )
        without_first = MODULE.SamplerProcessors.split_boundaries_from_onsets(
            0,
            7000,
            onsets,
            500,
            include_first_zone=False,
        )

        self.assertEqual(with_first, [(0, 1000), (1000, 3000), (3000, 5000), (5000, 7000)])
        self.assertEqual(without_first, [(1000, 3000), (3000, 5000), (5000, 7000)])

    def test_crossfade_between_zones_expands_key_ranges_around_boundaries(self):
        full_velocity = {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"}
        full_selector = {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}
        model = FakeRangeModel([
            ({"min": "0", "max": "57", "xfade_min": "0", "xfade_max": "57"}, full_velocity, full_selector),
            ({"min": "58", "max": "69", "xfade_min": "58", "xfade_max": "69"}, full_velocity, full_selector),
            ({"min": "70", "max": "127", "xfade_min": "70", "xfade_max": "127"}, full_velocity, full_selector),
        ])

        count = MODULE.SamplerProcessors.crossfade_between_zones(
            model,
            {"param_zone_crossfade_mode": "notes", "param_zone_crossfade_amount": "50"},
        )

        self.assertEqual(count, 3)
        ranges = [model.read_range(model.get_zone(i), "KeyRange") for i in range(model.zone_count())]
        self.assertEqual(ranges[0], {"min": "0", "max": "60", "xfade_min": "0", "xfade_max": "54"})
        self.assertEqual(ranges[1], {"min": "55", "max": "72", "xfade_min": "61", "xfade_max": "66"})
        self.assertEqual(ranges[2], {"min": "67", "max": "127", "xfade_min": "73", "xfade_max": "127"})

    def test_crossfade_between_zones_supports_steps_unit(self):
        full_velocity = {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"}
        full_selector = {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}
        model = FakeRangeModel([
            ({"min": "0", "max": "39", "xfade_min": "0", "xfade_max": "39"}, full_velocity, full_selector),
            ({"min": "40", "max": "79", "xfade_min": "40", "xfade_max": "79"}, full_velocity, full_selector),
        ])

        count = MODULE.SamplerProcessors.crossfade_between_zones(
            model,
            {"param_zone_crossfade_mode": "notes", "param_zone_crossfade_amount": "8", "param_zone_crossfade_unit": "steps"},
        )

        self.assertEqual(count, 2)
        ranges = [model.read_range(model.get_zone(i), "KeyRange") for i in range(model.zone_count())]
        self.assertEqual(ranges[0], {"min": "0", "max": "43", "xfade_min": "0", "xfade_max": "35"})
        self.assertEqual(ranges[1], {"min": "36", "max": "79", "xfade_min": "44", "xfade_max": "79"})

    def test_chain_mode_assigns_selector_ranges_by_key_and_velocity_area(self):
        full_key = {"min": "60", "max": "72", "xfade_min": "60", "xfade_max": "72"}
        full_velocity = {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"}
        full_selector = {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"}
        model = FakeRangeModel([
            (full_key, full_velocity, full_selector),
            (full_key, full_velocity, full_selector),
            (full_key, full_velocity, full_selector),
        ])

        count = MODULE.SamplerProcessors.chain_by_play_area(model)

        self.assertEqual(count, 3)
        ranges = [model.read_range(model.get_zone(i), "SelectorRange") for i in range(model.zone_count())]
        self.assertEqual(ranges[0], {"min": "0", "max": "42", "xfade_min": "0", "xfade_max": "42"})
        self.assertEqual(ranges[1], {"min": "43", "max": "84", "xfade_min": "43", "xfade_max": "84"})
        self.assertEqual(ranges[2], {"min": "85", "max": "127", "xfade_min": "85", "xfade_max": "127"})

    def test_auto_volume_velocity_scale_sets_global_amount_from_average_layers(self):
        model = self.load_model("test02.adv")

        count = MODULE.SamplerProcessors.auto_volume_velocity_scale(model)

        self.assertEqual(count, 1)
        self.assertAlmostEqual(float(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/VolumeVelScale")), 1.0 / 3.0, places=6)

    def test_sort_zones_reorders_with_successive_criteria(self):
        model = FakeSortableModel([
            {
                "name": "zone-a",
                "root_key": 60,
                "key_range": {"min": "10", "max": "20", "xfade_min": "10", "xfade_max": "20"},
                "velocity_range": {"min": "40", "max": "50", "xfade_min": "40", "xfade_max": "50"},
                "selector_range": {"min": "10", "max": "20", "xfade_min": "10", "xfade_max": "20"},
                "sample_path": "zeta.wav",
            },
            {
                "name": "zone-b",
                "root_key": 60,
                "key_range": {"min": "0", "max": "9", "xfade_min": "0", "xfade_max": "9"},
                "velocity_range": {"min": "80", "max": "90", "xfade_min": "80", "xfade_max": "90"},
                "selector_range": {"min": "0", "max": "9", "xfade_min": "0", "xfade_max": "9"},
                "sample_path": "beta.wav",
            },
            {
                "name": "zone-c",
                "root_key": 60,
                "key_range": {"min": "10", "max": "20", "xfade_min": "10", "xfade_max": "20"},
                "velocity_range": {"min": "10", "max": "20", "xfade_min": "10", "xfade_max": "20"},
                "selector_range": {"min": "0", "max": "9", "xfade_min": "0", "xfade_max": "9"},
                "sample_path": "alpha.wav",
            },
        ])

        count = MODULE.SamplerProcessors.sort_zones(
            model,
            {
                "param_sort_zones_1": "keys",
                "param_sort_zones_2": "velocity",
                "param_sort_zones_3": "file name",
            },
        )

        self.assertEqual(count, 3)
        self.assertEqual([zone["Name"] for zone in model.zones], ["zone-b", "zone-c", "zone-a"])

    def test_sort_zones_supports_sample_start_timing(self):
        model = FakeSortableModel([
            {"name": "zone-a", "sample_start": 3000},
            {"name": "zone-b", "sample_start": 1000},
            {"name": "zone-c", "sample_start": 2000},
        ])

        count = MODULE.SamplerProcessors.sort_zones(
            model,
            {
                "param_sort_zones_1": "start timing in audio file",
                "param_sort_zones_2": "none",
                "param_sort_zones_3": "none",
            },
        )

        self.assertEqual(count, 3)
        self.assertEqual([zone["Name"] for zone in model.zones], ["zone-b", "zone-c", "zone-a"])

    def test_filename_mapping_applies_p_v_c_d_tokens(self):
        model = FakeSortableModel([
            {
                "name": "zone-a",
                "root_key": 60,
                "key_range": {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
                "velocity_range": {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"},
                "selector_range": {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
                "sample_path": "pad P064 extra V110 foo C001 D-12.wav",
            }
        ])
        zone = model.get_zone(0)
        zone["Detune"] = "0"

        count = MODULE.SamplerProcessors.apply_filename_mapping(model)

        self.assertEqual(count, 1)
        self.assertEqual(zone["RootKey"], "64")
        self.assertEqual(zone["Detune"], "-12")
        self.assertEqual(model.read_range(zone, "VelocityRange"), {"min": "110", "max": "110", "xfade_min": "110", "xfade_max": "110"})
        self.assertEqual(model.read_range(zone, "SelectorRange"), {"min": "1", "max": "1", "xfade_min": "1", "xfade_max": "1"})

    def test_filename_mapping_uses_zone_name_when_paths_are_empty(self):
        model = FakeSortableModel([
            {
                "name": "hit p072 v090 c004 d+7",
                "root_key": 60,
                "key_range": {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
                "velocity_range": {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"},
                "selector_range": {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
                "sample_path": "",
                "relative_path": "",
            }
        ])
        zone = model.get_zone(0)
        zone["Detune"] = "0"

        count = MODULE.SamplerProcessors.apply_filename_mapping(model)

        self.assertEqual(count, 1)
        self.assertEqual(zone["RootKey"], "72")
        self.assertEqual(zone["Detune"], "7")
        self.assertEqual(model.read_range(zone, "VelocityRange")["min"], "90")
        self.assertEqual(model.read_range(zone, "SelectorRange")["min"], "4")

    def test_filename_mapping_clamps_values(self):
        model = FakeSortableModel([
            {
                "name": "zone-b",
                "root_key": 60,
                "key_range": {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
                "velocity_range": {"min": "1", "max": "127", "xfade_min": "1", "xfade_max": "127"},
                "selector_range": {"min": "0", "max": "127", "xfade_min": "0", "xfade_max": "127"},
                "sample_path": "pad p999 v999 c999 d-999.wav",
            }
        ])
        zone = model.get_zone(0)
        zone["Detune"] = "0"

        count = MODULE.SamplerProcessors.apply_filename_mapping(model)

        self.assertEqual(count, 1)
        self.assertEqual(zone["RootKey"], "127")
        self.assertEqual(zone["Detune"], "-50")
        self.assertEqual(model.read_range(zone, "VelocityRange")["min"], "127")
        self.assertEqual(model.read_range(zone, "SelectorRange")["min"], "127")

    def test_run_enabled_processors_spreads_key_before_velocity(self):
        model = self.load_model("test02.adv")

        count = MODULE.SamplerProcessors.run_enabled_processors(
            model,
            None,
            {"param_multiple_notes_mode": "spread velocity", "param_velocity_gamma": "1.0"},
            {"multiple_notes_case": True, "spread_root": True},
        )

        self.assertEqual(count, 6)
        vel_ranges = [model.read_range(model.get_zone(i), "VelocityRange") for i in range(model.zone_count())]
        key_ranges = [model.read_range(model.get_zone(i), "KeyRange") for i in range(model.zone_count())]
        self.assertEqual((vel_ranges[0]["min"], vel_ranges[0]["max"]), ("1", "127"))
        self.assertEqual((vel_ranges[1]["min"], vel_ranges[1]["max"]), ("1", "127"))
        self.assertEqual((vel_ranges[2]["min"], vel_ranges[2]["max"]), ("1", "127"))
        self.assertEqual((key_ranges[0]["min"], key_ranges[0]["max"]), ("0", "57"))
        self.assertEqual((key_ranges[1]["min"], key_ranges[1]["max"]), ("58", "69"))
        self.assertEqual((key_ranges[2]["min"], key_ranges[2]["max"]), ("70", "127"))

    def test_parse_offset_samples_supports_units(self):
        self.assertEqual(MODULE.AudioAnalysis.parse_offset_samples("250 ms", 48000, 10000), 12000)
        self.assertEqual(MODULE.AudioAnalysis.parse_offset_samples("-100 samples", 48000, 10000), -100)
        self.assertEqual(MODULE.AudioAnalysis.parse_offset_samples("10 %", 48000, 5000), 500)

    def test_parse_number_unit_samples_supports_beats(self):
        self.assertEqual(MODULE.AudioAnalysis.parse_number_unit_samples("250", "ms", 48000, 10000), 12000)
        self.assertEqual(MODULE.AudioAnalysis.parse_number_unit_samples("10", "%", 48000, 5000), 500)
        self.assertEqual(MODULE.AudioAnalysis.parse_number_unit_samples("2", "beat(s)", 48000, 5000, tempo_bpm="120"), 48000)

    def test_loop_mode_labels_match_validated_adv_values(self):
        self.assertEqual(MODULE.loop_mode_value_from_label("sustain", "on"), "0")
        self.assertEqual(MODULE.loop_mode_value_from_label("sustain", "loop"), "1")
        self.assertEqual(MODULE.loop_mode_value_from_label("sustain", "back and forth"), "2")
        self.assertEqual(MODULE.loop_mode_value_from_label("release", "on"), "0")
        self.assertEqual(MODULE.loop_mode_value_from_label("release", "loop"), "1")
        self.assertEqual(MODULE.loop_mode_value_from_label("release", "back-and-forth"), "2")
        self.assertEqual(MODULE.loop_mode_value_from_label("release", "off"), "3")
        self.assertEqual(MODULE.loop_mode_value_from_label("sustain", "forward"), "1")
        self.assertEqual(MODULE.loop_mode_value_from_label("release", "forward"), "1")
        self.assertEqual(MODULE.loop_mode_label_from_value("sustain", "0"), "on")
        self.assertEqual(MODULE.loop_mode_label_from_value("sustain", "1"), "loop")
        self.assertEqual(MODULE.loop_mode_label_from_value("sustain", "2"), "back-and-forth")
        self.assertEqual(MODULE.loop_mode_label_from_value("release", "0"), "on")
        self.assertEqual(MODULE.loop_mode_label_from_value("release", "1"), "loop")
        self.assertEqual(MODULE.loop_mode_label_from_value("release", "2"), "back-and-forth")
        self.assertEqual(MODULE.loop_mode_label_from_value("release", "3"), "off")

    def test_loop_mode_labels_match_example_adv_filenames(self):
        examples = {
            "example_sustain_on.adv": ("SustainLoop", "on"),
            "example_sustain_loop.adv": ("SustainLoop", "loop"),
            "example_sustain_back-and-forth.adv": ("SustainLoop", "back-and-forth"),
            "example_release_on.adv": ("ReleaseLoop", "on"),
            "example_release_loop.adv": ("ReleaseLoop", "loop"),
            "example_release_back-and-forth.adv": ("ReleaseLoop", "back-and-forth"),
            "example_release_off.adv": ("ReleaseLoop", "off"),
        }
        for filename, (loop_tag, label) in examples.items():
            with self.subTest(filename=filename):
                if not Path(__file__).with_name(filename).exists():
                    self.skipTest("Loop mode example ADV files are not present in this checkout.")
                model = self.load_model(filename)
                mode = model.read_loop(model.get_zone(0), loop_tag)["mode"]
                prefix = "release" if loop_tag == "ReleaseLoop" else "sustain"
                self.assertEqual(mode, MODULE.loop_mode_value_from_label(prefix, label))

    def test_migrate_loop_write_flags_preserves_old_loop_templates(self):
        processing_update = {
            "loop_write_start": FakeVar(False),
            "loop_write_end": FakeVar(False),
            "loop_write_mode": FakeVar(False),
            "loop_write_crossfade": FakeVar(False),
            "release_loop_write_start": FakeVar(False),
            "release_loop_write_end": FakeVar(False),
            "release_loop_write_mode": FakeVar(False),
            "release_loop_write_crossfade": FakeVar(False),
        }

        MODULE.migrate_loop_write_flags(
            {"processing_update": {"loop_detection": True, "release_loop_detection": True}},
            processing_update,
        )

        self.assertTrue(all(var.get() for var in processing_update.values()))

        processing_update["loop_write_start"].set(False)
        MODULE.migrate_loop_write_flags(
            {"processing_update": {"loop_detection": True, "loop_write_start": False}},
            processing_update,
        )
        self.assertFalse(processing_update["loop_write_start"].get())

    def test_waveform_loop_overlay_flags_show_open_panels_without_write_flags(self):
        gui = MODULE.SamplerAdvGui.__new__(MODULE.SamplerAdvGui)
        gui.processing_update = {
            "split_zones": FakeVar(False),
            "loop_detection": FakeVar(True),
            "release_loop_detection": FakeVar(True),
            "loop_write_start": FakeVar(False),
            "loop_write_end": FakeVar(False),
            "loop_write_crossfade": FakeVar(False),
            "release_loop_write_start": FakeVar(False),
            "release_loop_write_end": FakeVar(False),
            "release_loop_write_crossfade": FakeVar(False),
            "start_end_refine": FakeVar(False),
        }
        gui.global_vars = {"param_split_mode": FakeVar("detect")}

        flags = gui.current_waveform_overlay_flags()

        self.assertTrue(flags["sustain_loop"])
        self.assertTrue(flags["release_loop"])
        self.assertFalse(flags["sustain_loop_predict"])
        self.assertFalse(flags["release_loop_predict"])
        self.assertFalse(flags["sustain_crossfade"])
        self.assertFalse(flags["release_crossfade"])

    def test_frequency_to_midi_parts_respects_diapason(self):
        _midi_float, root_key, cents = MODULE.AudioAnalysis.frequency_to_midi_parts(432.0, diapason_hz=432.0)
        self.assertEqual(root_key, 69)
        self.assertAlmostEqual(cents, 0.0, delta=0.01)
        self.assertAlmostEqual(MODULE.AudioAnalysis.midi_key_to_frequency(69, diapason_hz=432.0), 432.0, delta=0.01)

    def test_detect_zone_pitch_uses_configured_tune_window(self):
        zone = MODULE.ET.Element("MultiSamplePart")
        for tag, value in (
            ("Name", "pitch-window"),
            ("RootKey", "60"),
            ("Detune", "0"),
            ("SampleStart", "0"),
            ("SampleEnd", "1000"),
        ):
            MODULE.ET.SubElement(zone, tag).set("Value", str(value))
        samples = MODULE.np.arange(1000, dtype=MODULE.np.float32)
        audio = SimpleNamespace(samples=samples, sample_rate=1000)

        class PitchWindowModel:
            def zone_count(self_nonlocal):
                return 1

            def get_zone(self_nonlocal, index):
                if index != 0:
                    raise IndexError(index)
                return zone

        class PitchWindowAudioCache:
            def get_zone_audio(self_nonlocal, _model, _zone):
                return audio

        model = PitchWindowModel()
        audio_cache = PitchWindowAudioCache()
        captured = {}
        original = MODULE.AudioAnalysis.detect_pitch_hz

        def fake_detect_pitch_hz(window_samples, sample_rate, min_hz=24.0, max_hz=2000.0, **_kwargs):
            captured["samples"] = MODULE.np.asarray(window_samples).copy()
            captured["sample_rate"] = sample_rate
            return 440.0

        MODULE.AudioAnalysis.detect_pitch_hz = fake_detect_pitch_hz
        try:
            count = MODULE.SamplerProcessors.detect_zone_pitch(
                model,
                {
                    "pitch_detection_root": True,
                    "pitch_detection_detune": False,
                    "param_diapason_hz": "440",
                    "param_pitch_window_start_number": "250",
                    "param_pitch_window_start_unit": "samples",
                    "param_pitch_window_stop_number": "750",
                    "param_pitch_window_stop_unit": "samples",
                },
                audio_cache,
            )
        finally:
            MODULE.AudioAnalysis.detect_pitch_hz = original

        self.assertEqual(count, 1)
        self.assertEqual(captured["sample_rate"], 1000)
        self.assertEqual(len(captured["samples"]), 500)
        self.assertEqual(float(captured["samples"][0]), 250.0)
        self.assertEqual(float(captured["samples"][-1]), 749.0)
        self.assertEqual(MODULE.get_value(zone, "RootKey", ""), "69")

    def test_detect_pitch_hz_corrects_subharmonic_on_flute_zone(self):
        adv_path = Path(__file__).with_name("testPresets01 Project") / "adv presets" / "acoustic wood recorder flute 01.adv"
        wav_path = Path(__file__).with_name("testPresets01 Project") / "Samples" / "Imported" / "2024 12 09 flute 01.wav"
        model = MODULE.SamplerAdvModel(MODULE.AdvCodec.load(adv_path), source_path=adv_path)
        zone = model.get_zone(6)
        audio, sample_rate = MODULE.sf.read(str(wav_path), dtype="float32", always_2d=True)
        mono = audio.mean(axis=1)
        start = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "SampleStart", "0"), 0))
        end = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "SampleEnd", str(len(mono))), len(mono)))
        hz = MODULE.AudioAnalysis.detect_pitch_hz(mono[start:end], sample_rate)
        midi_float, _root, _cents = MODULE.AudioAnalysis.frequency_to_midi_parts(hz, diapason_hz=440.0)
        stored_root = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "RootKey", "0"), 0))
        stored_detune = float(MODULE.parse_number_from_text(MODULE.get_value(zone, "Detune", "0"), 0))
        self.assertLess(abs(midi_float - (stored_root + (stored_detune / 100.0))), 2.0)

    def test_detect_pitch_hz_validated_recorder_flute_corpus_has_no_large_outliers(self):
        corpus = [
            ("adv presets/acoustic wood recorder flute 01.adv", "Samples/Imported/2024 12 09 flute 01.wav"),
            ("adv presets/tenor plastic recorder 01.adv", "Samples/Imported/tenor recorder 01.wav"),
        ]
        project_root = Path(__file__).with_name("testPresets01 Project")
        max_abs_errors = []
        for adv_rel, wav_rel in corpus:
            adv_path = project_root / adv_rel
            wav_path = project_root / wav_rel
            model = MODULE.SamplerAdvModel(MODULE.AdvCodec.load(adv_path), source_path=adv_path)
            audio, sample_rate = MODULE.sf.read(str(wav_path), dtype="float32", always_2d=True)
            mono = audio.mean(axis=1)
            errors = []
            for index in range(model.zone_count()):
                zone = model.get_zone(index)
                start = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "SampleStart", "0"), 0))
                end = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "SampleEnd", str(len(mono))), len(mono)))
                hz = MODULE.AudioAnalysis.detect_pitch_hz(mono[start:end], sample_rate)
                if hz is None:
                    continue
                midi_float, _root, _cents = MODULE.AudioAnalysis.frequency_to_midi_parts(hz, diapason_hz=440.0)
                stored_root = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "RootKey", "0"), 0))
                stored_detune = float(MODULE.parse_number_from_text(MODULE.get_value(zone, "Detune", "0"), 0))
                errors.append(midi_float - (stored_root + (stored_detune / 100.0)))
            max_abs_errors.append(max(abs(err) for err in errors))
        self.assertLess(max(max_abs_errors), 1.25)

    def test_detect_pitch_hz_sustained_validated_examples_avoid_octave_outliers(self):
        corpus = [
            ("cello arco vib backForthLoop MS 01.adv", "standard", None),
            ("shruti box looping MS 01.adv", "extended", {127}),
        ]
        project_root = Path(__file__).with_name("testPresets01 Project") / "adv presets"
        cache = MODULE.ZoneAudioCache()
        for filename, correction, skip_roots in corpus:
            with self.subTest(filename=filename, correction=correction):
                model = MODULE.SamplerAdvModel(MODULE.AdvCodec.load(project_root / filename), source_path=project_root / filename)
                errors = []
                for index in range(model.zone_count()):
                    zone = model.get_zone(index)
                    stored_root = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "RootKey", "0"), 0))
                    if skip_roots and stored_root in skip_roots:
                        continue
                    audio = cache.get_zone_audio(model, zone)
                    hz = MODULE.AudioAnalysis.detect_pitch_hz(
                        audio.samples,
                        audio.sample_rate,
                        harmonic_correction=correction,
                    )
                    if hz is None:
                        continue
                    midi_float, _root, _cents = MODULE.AudioAnalysis.frequency_to_midi_parts(hz, diapason_hz=440.0)
                    stored_detune = float(MODULE.parse_number_from_text(MODULE.get_value(zone, "Detune", "0"), 0))
                    errors.append(midi_float - (stored_root + (stored_detune / 100.0)))
                self.assertTrue(errors)
                self.assertLess(max(abs(err) for err in errors), 0.75)

    def test_find_loop_points_snaps_flute_zone_to_zero_crossings(self):
        adv_path = Path(__file__).with_name("testPresets01 Project") / "adv presets" / "acoustic wood recorder flute 01.adv"
        wav_path = Path(__file__).with_name("testPresets01 Project") / "Samples" / "Imported" / "2024 12 09 flute 01.wav"
        model = MODULE.SamplerAdvModel(MODULE.AdvCodec.load(adv_path), source_path=adv_path)
        audio, sample_rate = MODULE.sf.read(str(wav_path), dtype="float32", always_2d=True)
        mono = audio.mean(axis=1)
        found = False
        for zone_index in range(model.zone_count()):
            zone = model.get_zone(zone_index)
            zone_start = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "SampleStart", "0"), 0))
            zone_end = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "SampleEnd", str(len(mono))), len(mono)))
            slice_samples = mono[zone_start:zone_end]
            loop_vals = model.read_loop(zone, "SustainLoop")
            target_start = int(loop_vals["start"]) - zone_start
            target_end = int(loop_vals["end"]) - zone_start
            search_range = int((target_end - target_start) * 0.10)
            loop_info = MODULE.AudioAnalysis.find_loop_points(
                slice_samples,
                sample_rate,
                target_start_sample=target_start,
                target_end_sample=target_end,
                search_range_samples=search_range,
                fade_policy="No fade",
                fade_custom_number="0",
                fade_custom_unit="%",
            )
            if loop_info is None:
                continue
            start_cross = MODULE.AudioAnalysis.nearest_zero_crossing(slice_samples, loop_info["start"])
            end_cross = MODULE.AudioAnalysis.nearest_zero_crossing(slice_samples, loop_info["end"] - 1)
            if start_cross is None or end_cross is None:
                continue
            self.assertLessEqual(start_cross["distance"], 1.0)
            self.assertLessEqual(end_cross["distance"], 1.0)
            found = True
            break
        self.assertTrue(found)

    def test_gate_detection_beats_detection_on_approved_single_sample_presets(self):
        cache = MODULE.ZoneAudioCache()
        better_or_equal = []
        for adv_path in self.approved_preset_paths():
            model = MODULE.SamplerAdvModel(MODULE.AdvCodec.load(adv_path), source_path=adv_path)
            sample_paths = {
                str(model.resolve_sample_file(model.get_zone(i)))
                for i in range(model.zone_count())
            }
            if len(sample_paths) != 1:
                continue
            zone_audio = cache.get_zone_audio(model, model.get_zone(0))
            detection_metrics = self.split_detection_metrics(model, zone_audio.audio, zone_audio.sample_rate, "detection")
            gate_metrics = self.split_detection_metrics(model, zone_audio.audio, zone_audio.sample_rate, "gate")
            better_or_equal.append(
                gate_metrics["count_error"] <= detection_metrics["count_error"]
                and gate_metrics["abs_median_error"] <= detection_metrics["abs_median_error"]
            )
        self.assertTrue(better_or_equal)
        self.assertTrue(all(better_or_equal))

    def test_build_midi_test_plan_repeats_non_random_round_robin_and_uses_selector_cc(self):
        model = FakeMidiModel(
            [
                {
                    "name": "rr_a",
                    "key_range": {"min": "60", "max": "60", "xfade_min": "60", "xfade_max": "60"},
                    "velocity_range": {"min": "40", "max": "40", "xfade_min": "40", "xfade_max": "40"},
                    "selector_range": {"min": "10", "max": "10", "xfade_min": "10", "xfade_max": "10"},
                },
                {
                    "name": "rr_b",
                    "key_range": {"min": "60", "max": "60", "xfade_min": "60", "xfade_max": "60"},
                    "velocity_range": {"min": "40", "max": "40", "xfade_min": "40", "xfade_max": "40"},
                    "selector_range": {"min": "10", "max": "10", "xfade_min": "10", "xfade_max": "10"},
                },
                {
                    "name": "other",
                    "key_range": {"min": "62", "max": "62", "xfade_min": "62", "xfade_max": "62"},
                    "velocity_range": {"min": "90", "max": "90", "xfade_min": "90", "xfade_max": "90"},
                    "selector_range": {"min": "80", "max": "80", "xfade_min": "80", "xfade_max": "80"},
                },
            ],
            round_robin=True,
            round_robin_mode="0",
        )
        plan = MODULE.build_midi_test_plan(model, FakeMidiAudioCache(model), tempo_bpm=100.0, selector_cc=1)
        self.assertTrue(plan["use_selector_cc"])
        self.assertFalse(plan["round_robin_random"])
        self.assertEqual(len(plan["events"]), 3)
        self.assertEqual([(item["note"], item["velocity"], item["selector"]) for item in plan["events"]], [(60, 40, 10), (60, 40, 10), (62, 90, 80)])

    def test_build_midi_test_plan_uses_root_note_clamped_inside_key_range(self):
        model = FakeMidiModel(
            [
                {
                    "name": "zone",
                    "root_key": 72,
                    "key_range": {"min": "60", "max": "67", "xfade_min": "60", "xfade_max": "67"},
                    "velocity_range": {"min": "80", "max": "100", "xfade_min": "80", "xfade_max": "100"},
                    "selector_range": {"min": "0", "max": "0", "xfade_min": "0", "xfade_max": "0"},
                }
            ]
        )
        plan = MODULE.build_midi_test_plan(model, FakeMidiAudioCache(model), tempo_bpm=100.0, selector_cc=1)
        self.assertEqual(len(plan["events"]), 1)
        self.assertEqual(plan["events"][0]["note"], 67)

    def test_write_midi_file_creates_valid_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "midi_test.mid"
            events = MODULE.build_midi_test_events(
                [
                    {"note": 60, "velocity": 90, "selector": 10, "hold_seconds": 0.25, "tail_seconds": 0.10, "use_selector_cc": True},
                    {"note": 62, "velocity": 100, "selector": 80, "hold_seconds": 0.25, "tail_seconds": 0.10, "use_selector_cc": True},
                ],
                tempo_bpm=100.0,
                selector_cc=1,
            )
            MODULE.write_midi_file(out_path, events, tempo_bpm=100.0, track_name="MIDI_test")
            data = out_path.read_bytes()

        self.assertTrue(data.startswith(b"MThd"))
        self.assertIn(b"MTrk", data)

    def test_parse_filename_mapping_tokens_is_case_insensitive_and_last_token_wins(self):
        tokens = MODULE.SamplerProcessors.parse_filename_mapping_tokens("take_p064-V110_c001 d+12 other P065")
        self.assertEqual(tokens, {"P": 65, "V": 110, "C": 1, "D": 12})

    def test_detect_onsets_finds_multiple_bursts(self):
        sr = 48000
        gap = MODULE.np.zeros(sr // 4, dtype=MODULE.np.float32)
        burst = 0.7 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * MODULE.np.arange(sr // 8) / sr)
        samples = MODULE.np.concatenate([gap, burst, gap, burst, gap, burst, gap]).astype(MODULE.np.float32)

        onsets = MODULE.AudioAnalysis.detect_onsets(samples, sr, sensitivity=0.3, min_duration_samples=sr // 8)

        self.assertGreaterEqual(len(onsets), 2)

    def test_detect_onsets_profile_compression_reaches_quieter_triggers(self):
        sr = 48000
        gap = MODULE.np.zeros(sr // 6, dtype=MODULE.np.float32)
        burst_len = sr // 14

        def make_burst(amplitude):
            t = MODULE.np.arange(burst_len, dtype=MODULE.np.float32) / sr
            return (amplitude * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)

        samples = MODULE.np.concatenate([
            gap,
            make_burst(0.95),
            gap,
            make_burst(0.16),
            gap,
            make_burst(0.38),
            gap,
        ]).astype(MODULE.np.float32)

        linear_onsets = MODULE.AudioAnalysis.detect_onsets(
            samples,
            sr,
            sensitivity=0.45,
            min_duration_samples=sr // 10,
            profile_compression_pct=0.0,
        )
        log_onsets = MODULE.AudioAnalysis.detect_onsets(
            samples,
            sr,
            sensitivity=0.45,
            min_duration_samples=sr // 10,
            profile_compression_pct=100.0,
        )

        self.assertGreater(len(log_onsets), len(linear_onsets))

    def test_detect_gate_onsets_ignores_internal_sustain_motion(self):
        sr = 48000
        samples = MODULE.np.zeros(26000, dtype=MODULE.np.float32)

        note1_len = 8000
        note1 = 0.45 + (0.08 * MODULE.np.sin(MODULE.np.linspace(0, 16 * MODULE.np.pi, note1_len, dtype=MODULE.np.float32)))
        samples[4000:4000 + note1_len] = note1

        note2_len = 5000
        note2 = 0.38 + (0.05 * MODULE.np.sin(MODULE.np.linspace(0, 10 * MODULE.np.pi, note2_len, dtype=MODULE.np.float32)))
        samples[17000:17000 + note2_len] = note2

        onsets = MODULE.AudioAnalysis.detect_gate_onsets(samples, sr, sensitivity=0.35, min_duration_samples=1000)

        self.assertEqual(len(onsets), 2)
        self.assertTrue(abs(onsets[0] - 4000) < 1500)
        self.assertTrue(abs(onsets[1] - 17000) < 1500)

    def test_detect_gate_onsets_local_attack_starts_later_than_threshold(self):
        sr = 48000
        samples = MODULE.np.zeros(18000, dtype=MODULE.np.float32)

        ramp_start = 4000
        ramp_len = 1600
        hold_len = 700
        attack_start = ramp_start + ramp_len + hold_len
        ramp = MODULE.np.linspace(0.0, 0.28, ramp_len, dtype=MODULE.np.float32)
        samples[ramp_start:ramp_start + ramp_len] = ramp
        samples[ramp_start + ramp_len:attack_start] = 0.30
        t = MODULE.np.arange(3600, dtype=MODULE.np.float32) / sr
        samples[attack_start:attack_start + len(t)] = 0.75 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)

        threshold_onsets = MODULE.AudioAnalysis.detect_gate_onsets(
            samples,
            sr,
            sensitivity=0.20,
            min_duration_samples=1000,
            start_placement="threshold",
        )
        attack_onsets = MODULE.AudioAnalysis.detect_gate_onsets(
            samples,
            sr,
            sensitivity=0.20,
            min_duration_samples=1000,
            start_placement="local attack",
        )

        self.assertEqual(len(threshold_onsets), 1)
        self.assertEqual(len(attack_onsets), 1)
        self.assertGreater(attack_onsets[0], threshold_onsets[0] + 300)
        self.assertTrue(abs(attack_onsets[0] - attack_start) < 1500)

    def test_detect_gate_onsets_stop_hysteresis_changes_region_split(self):
        sr = 48000
        samples = MODULE.np.zeros(26000, dtype=MODULE.np.float32)
        start = 4000
        samples[start:start + 5000] = 0.60
        samples[start + 5000:start + 7600] = 0.15
        samples[start + 7600:start + 12200] = 0.58

        loose_onsets = MODULE.AudioAnalysis.detect_gate_onsets(
            samples,
            sr,
            sensitivity=0.35,
            min_duration_samples=1200,
            stop_hysteresis_pct=20.0,
        )
        tight_onsets = MODULE.AudioAnalysis.detect_gate_onsets(
            samples,
            sr,
            sensitivity=0.35,
            min_duration_samples=1200,
            stop_hysteresis_pct=90.0,
        )

        self.assertEqual(len(loose_onsets), 1)
        self.assertGreaterEqual(len(tight_onsets), 2)

    def test_detect_activity_bounds_keeps_tail_but_stops_before_next_activity(self):
        sr = 8000
        samples = MODULE.np.concatenate([
            MODULE.np.zeros(800, dtype=MODULE.np.float32),
            MODULE.np.full(800, 0.4, dtype=MODULE.np.float32),
            MODULE.np.zeros(500, dtype=MODULE.np.float32),
            MODULE.np.full(220, 0.12, dtype=MODULE.np.float32),
            MODULE.np.zeros(800, dtype=MODULE.np.float32),
        ])

        start, end = MODULE.AudioAnalysis.detect_activity_bounds(
            samples,
            release_threshold=0.05,
            tail_margin_samples=260,
            next_activity_threshold=0.10,
            quiet_hold_samples=140,
        )

        second_activity_start = 800 + 800 + 500
        self.assertGreaterEqual(start, 700)
        self.assertLessEqual(start, 900)
        self.assertGreater(end, 1600)
        self.assertLessEqual(end, second_activity_start)

    def test_suggest_onset_sensitivity_returns_midrange_value(self):
        sr = 48000
        base = MODULE.np.zeros(sr * 2, dtype=MODULE.np.float32)
        rng = MODULE.np.random.default_rng(0)
        noise = rng.normal(0.0, 0.002, size=base.shape[0]).astype(MODULE.np.float32)
        samples = base + noise

        for offset, amp in [(sr // 3, 0.08), (sr, 0.03), (sr + sr // 3, 0.12)]:
            tone = amp * MODULE.np.sin(2.0 * MODULE.np.pi * 330.0 * MODULE.np.arange(sr // 10) / sr)
            samples[offset:offset + len(tone)] += tone.astype(MODULE.np.float32)

        suggestion = MODULE.AudioAnalysis.suggest_onset_sensitivity(samples, sr)

        self.assertIsNotNone(suggestion)
        self.assertGreater(suggestion["quietest_clear"], suggestion["noise_floor"])
        self.assertGreaterEqual(suggestion["sensitivity"], 0.02)
        self.assertLess(suggestion["sensitivity"], 0.95)

    def test_detect_pitch_hz_reports_440ish(self):
        sr = 48000
        duration = 1.0
        t = MODULE.np.arange(int(sr * duration), dtype=MODULE.np.float64) / sr
        samples = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 440.0 * t)

        freq_hz = MODULE.AudioAnalysis.detect_pitch_hz(samples, sr)
        _midi_float, root_key, cents = MODULE.AudioAnalysis.frequency_to_midi_parts(freq_hz)

        self.assertIsNotNone(freq_hz)
        self.assertAlmostEqual(freq_hz, 440.0, delta=2.0)
        self.assertEqual(root_key, 69)
        self.assertAlmostEqual(cents, 0.0, delta=5.0)

    def test_estimate_loop_detune_info_uses_loop_length_for_short_loops(self):
        sr = 48000
        duration = 1.0
        t = MODULE.np.arange(int(sr * duration), dtype=MODULE.np.float64) / sr
        zone_samples = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 440.0 * t)
        loop_samples = zone_samples[:100]

        info = MODULE.AudioAnalysis.estimate_loop_detune_info(zone_samples, loop_samples, sr, fallback_root_key=69)

        self.assertIsNotNone(info)
        self.assertEqual(info["method"], "loop_length")
        self.assertAlmostEqual(info["loop_hz"], 480.0, delta=0.5)
        self.assertAlmostEqual(info["detune_cents"], -151.32, delta=3.0)

    def test_estimate_loop_detune_info_uses_autocorr_for_long_loops(self):
        sr = 48000
        duration = 1.0
        t = MODULE.np.arange(int(sr * duration), dtype=MODULE.np.float64) / sr
        zone_samples = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 440.0 * t)
        loop_samples = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 460.0 * t)

        info = MODULE.AudioAnalysis.estimate_loop_detune_info(zone_samples, loop_samples, sr, fallback_root_key=69)

        self.assertIsNotNone(info)
        self.assertEqual(info["method"], "autocorr")
        self.assertAlmostEqual(info["loop_hz"], 460.0, delta=3.0)
        self.assertAlmostEqual(info["detune_cents"], -76.96, delta=5.0)

    def test_find_loop_points_returns_candidate_for_periodic_audio(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)

        loop_info = MODULE.AudioAnalysis.find_loop_points(samples, sr, start_pct=20, end_pct=80, shift_pct=10)

        self.assertIsNotNone(loop_info)
        self.assertLess(loop_info["start"], loop_info["end"])

    def test_find_loop_points_zero_search_range_stays_on_targets(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)

        loop_info = MODULE.AudioAnalysis.find_loop_points(
            samples,
            sr,
            start_pct=20,
            end_pct=80,
            search_range_samples=0,
            fade_policy="No fade",
        )

        self.assertIsNotNone(loop_info)
        self.assertEqual(loop_info["start"], int(len(samples) * 0.20))
        self.assertEqual(loop_info["end"], int(len(samples) * 0.80))

    def test_loop_candidate_score_prefers_same_direction_zero_crossings(self):
        values = MODULE.np.array([
            -0.3, -0.1, 0.1, 0.3, 0.2, 0.1, 0.0, -0.1, -0.3,
            -0.2, -0.1, 0.1, 0.3, 0.2, 0.1, 0.0, -0.1, -0.3,
        ], dtype=MODULE.np.float64)
        same_dir = MODULE.AudioAnalysis.loop_candidate_score(values, 2, 12, 4, fade_samples=0)
        opposite_dir = MODULE.AudioAnalysis.loop_candidate_score(values, 2, 8, 4, fade_samples=0)

        self.assertIsNotNone(same_dir)
        self.assertIsNotNone(opposite_dir)
        self.assertLess(same_dir, opposite_dir)

    def test_find_loop_points_accepts_direct_sample_targets(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)

        loop_info = MODULE.AudioAnalysis.find_loop_points(
            samples,
            sr,
            target_start_sample=12000,
            target_end_sample=36000,
            search_range_samples=0,
            fade_policy="No fade",
        )

        self.assertIsNotNone(loop_info)
        self.assertEqual(loop_info["start"], 12000)
        self.assertEqual(loop_info["end"], 36000)

    def test_clamp_loop_crossfade_limits_to_available_pre_roll(self):
        self.assertEqual(MODULE.clamp_loop_crossfade(1000, 1100, 2100, 500), 100)

    def test_apply_zone_values_clamps_loop_detune_and_crossfade(self):
        model = self.load_model("test01.adv")
        summary = model.read_zone_summary(0)
        ranges = {}
        for prefix in ("key", "vel", "sel"):
            for sub in ("min", "max", "xfade_min", "xfade_max"):
                ranges[f"{prefix}_{sub}"] = summary[{"key": "key_range", "vel": "velocity_range", "sel": "selector_range"}[prefix]][sub]
        loops = {}
        for prefix, src in (("sustain", summary["sustain_loop"]), ("release", summary["release_loop"])):
            for sub in ("start", "end", "mode", "crossfade", "detune"):
                loops[f"{prefix}_{sub}"] = src[sub]
        zone = model.get_zone(0)
        sample_start = int(MODULE.get_value(zone, "SampleStart", "0"))
        loops["sustain_start"] = str(sample_start + 20)
        loops["sustain_end"] = str(sample_start + 200)
        loops["sustain_crossfade"] = "500"
        loops["sustain_detune"] = "2400"
        zone_values = {
            "name": summary["name"],
            "volume_db": summary["volume_db"],
            "root_key": summary["root_key"],
            "detune": "80",
            "tune_scale": summary["tune_scale"],
            "sample_start": summary["sample_start"],
            "sample_end": summary["sample_end"],
        }
        model.apply_zone_values(0, zone_values, ranges, loops)
        self.assertEqual(MODULE.get_value(zone, "Detune", "0"), "50")
        sustain = model.read_loop(zone, "SustainLoop")
        self.assertEqual(sustain["crossfade"], "20")
        self.assertEqual(sustain["detune"], "1200")

    def test_zone_detune_is_direct_signed_cents(self):
        model = self.load_model("test01.adv")
        zone = model.get_zone(0)
        MODULE.set_value(zone, "Detune", 0)
        summary = model.read_zone_summary(0)
        self.assertEqual(summary["detune"], "0")

        range_values = {}
        for prefix, source_key in (("key", "key_range"), ("vel", "velocity_range"), ("sel", "selector_range")):
            for sub in ("min", "max", "xfade_min", "xfade_max"):
                range_values[f"{prefix}_{sub}"] = summary[source_key][sub]
        loop_values = {}
        for prefix, source_key in (("sustain", "sustain_loop"), ("release", "release_loop")):
            for sub in ("start", "end", "mode", "crossfade", "detune"):
                loop_values[f"{prefix}_{sub}"] = summary[source_key][sub]

        zone_values = {
            "name": summary["name"],
            "volume_db": summary["volume_db"],
            "root_key": summary["root_key"],
            "detune": "11",
            "tune_scale": summary["tune_scale"],
            "sample_start": summary["sample_start"],
            "sample_end": summary["sample_end"],
        }
        model.apply_zone_values(0, zone_values, range_values, loop_values)
        self.assertEqual(MODULE.get_value(model.get_zone(0), "Detune", ""), "11")

    def test_resolve_crossfade_samples_supports_new_policies(self):
        sr = 48000
        loop_length = 12000
        self.assertEqual(MODULE.AudioAnalysis.resolve_crossfade_samples(sr, loop_length, "No fade", "25", "%", pitch_hz=220.0), 0)
        self.assertAlmostEqual(
            MODULE.AudioAnalysis.resolve_crossfade_samples(sr, loop_length, "One waveform", "25", "%", pitch_hz=240.0),
            200,
            delta=1,
        )
        self.assertEqual(MODULE.AudioAnalysis.resolve_crossfade_samples(sr, loop_length, "Longest possible", "25", "%", pitch_hz=220.0), loop_length // 2)

    def test_normalize_zone_volumes_respects_amount_parameter(self):
        samples = MODULE.np.full(4096, 0.2, dtype=MODULE.np.float32)
        model = FakeNormalizeModel(samples, volume="1.0")
        audio_cache = FakeNormalizeAudioCache(model)

        count = MODULE.SamplerProcessors.normalize_zone_volumes(
            model,
            {"param_normalize_mode": "peak", "param_normalize_amount_pct": "50"},
            audio_cache,
        )

        self.assertEqual(count, 1)
        new_volume = float(MODULE.get_value(model.get_zone(0), "Volume", "0"))
        self.assertAlmostEqual(new_volume, 2.95, places=2)

    def test_normalize_zone_volumes_supports_lufs_mode(self):
        sr = 48000
        t = MODULE.np.arange(sr, dtype=MODULE.np.float64) / sr
        samples = (0.08 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeNormalizeModel(samples, volume="1.0")
        audio_cache = FakeNormalizeAudioCache(model)

        count = MODULE.SamplerProcessors.normalize_zone_volumes(
            model,
            {"param_normalize_mode": "LUFS", "param_normalize_amount_pct": "100"},
            audio_cache,
        )

        self.assertEqual(count, 1)
        self.assertGreater(float(MODULE.get_value(model.get_zone(0), "Volume", "0")), 1.0)

    def test_detect_zone_loops_updates_sustain_and_release(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loops(
            model,
            {
                "loop_detection": True,
                "release_loop_detection": True,
                "param_sustain_loop_start_pct": "20",
                "param_sustain_loop_end_pct": "80",
                "param_sustain_loop_search_number": "10",
                "param_sustain_loop_search_unit": "%",
                "param_sustain_crossfade_policy": "Custom",
                "param_sustain_crossfade_custom_number": "25",
                "param_sustain_crossfade_custom_unit": "%",
                "param_release_loop_start_pct": "20",
                "param_release_loop_search_number": "10",
                "param_release_loop_search_unit": "%",
                "param_release_crossfade_policy": "Custom",
                "param_release_crossfade_custom_number": "25",
                "param_release_crossfade_custom_unit": "%",
            },
            audio_cache,
        )

        self.assertEqual(count, 1)
        sustain = model.read_loop(model.get_zone(0), "SustainLoop")
        release = model.read_loop(model.get_zone(0), "ReleaseLoop")
        self.assertNotEqual(sustain["start"], release["start"])
        self.assertEqual(int(release["end"]), len(samples))
        self.assertEqual(sustain["mode"], MODULE.SUSTAIN_MODE_VALUES["loop"])
        self.assertEqual(release["mode"], MODULE.RELEASE_MODE_VALUES["loop"])
        self.assertGreater(int(sustain["end"]), int(sustain["start"]))

    def test_detect_zone_loops_respects_loop_mode_labels(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loops(
            model,
            {
                "loop_detection": True,
                "release_loop_detection": True,
                "param_sustain_loop_start_pct": "20",
                "param_sustain_loop_end_pct": "80",
                "param_sustain_loop_search_number": "10",
                "param_sustain_loop_search_unit": "%",
                "param_sustain_crossfade_policy": "Custom",
                "param_sustain_crossfade_custom_number": "25",
                "param_sustain_crossfade_custom_unit": "%",
                "param_sustain_loop_mode": "back and forth",
                "param_release_loop_start_pct": "20",
                "param_release_loop_search_number": "10",
                "param_release_loop_search_unit": "%",
                "param_release_crossfade_policy": "Custom",
                "param_release_crossfade_custom_number": "25",
                "param_release_crossfade_custom_unit": "%",
                "param_release_loop_mode": "off",
            },
            audio_cache,
        )

        self.assertEqual(count, 1)
        zone = model.get_zone(0)
        self.assertEqual(model.read_loop(zone, "SustainLoop")["mode"], MODULE.SUSTAIN_MODE_VALUES["back-and-forth"])
        self.assertEqual(model.read_loop(zone, "ReleaseLoop")["mode"], MODULE.RELEASE_MODE_VALUES["off"])

    def test_detect_zone_loops_respects_per_field_write_flags(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loops(
            model,
            {
                "loop_detection": True,
                "loop_write_start": False,
                "loop_write_end": False,
                "loop_write_mode": True,
                "loop_write_crossfade": False,
                "param_sustain_loop_start_pct": "20",
                "param_sustain_loop_end_pct": "80",
                "param_sustain_loop_search_number": "10",
                "param_sustain_loop_search_unit": "%",
                "param_sustain_crossfade_policy": "Custom",
                "param_sustain_crossfade_custom_number": "25",
                "param_sustain_crossfade_custom_unit": "%",
                "param_sustain_loop_mode": "back and forth",
            },
            audio_cache,
        )

        self.assertEqual(count, 1)
        sustain = model.read_loop(model.get_zone(0), "SustainLoop")
        self.assertEqual(sustain["start"], "0")
        self.assertEqual(sustain["end"], "1")
        self.assertEqual(sustain["mode"], MODULE.SUSTAIN_MODE_VALUES["back-and-forth"])
        self.assertEqual(sustain["crossfade"], "0")

    def test_detect_zone_loops_ignores_unchecked_parameter_values(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        zone = model.get_zone(0)
        sustain_loop = MODULE.child(zone, "SustainLoop")
        MODULE.set_value(sustain_loop, "Start", 12000)
        MODULE.set_value(sustain_loop, "End", 36000)
        MODULE.set_value(sustain_loop, "Mode", "1")
        MODULE.set_value(sustain_loop, "Crossfade", "123")
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loops(
            model,
            {
                "loop_detection": True,
                "loop_write_start": False,
                "loop_write_end": False,
                "loop_write_mode": False,
                "loop_write_crossfade": False,
                "param_sustain_loop_start_pct": "99",
                "param_sustain_loop_end_pct": "100",
                "param_sustain_loop_search_number": "0",
                "param_sustain_loop_search_unit": "%",
                "param_sustain_crossfade_policy": "Longest possible",
                "param_sustain_loop_mode": "back-and-forth",
            },
            audio_cache,
        )

        self.assertEqual(count, 0)
        sustain = model.read_loop(zone, "SustainLoop")
        self.assertEqual(sustain["start"], "12000")
        self.assertEqual(sustain["end"], "36000")
        self.assertEqual(sustain["mode"], "1")
        self.assertEqual(sustain["crossfade"], "123")

    def test_detect_zone_loops_keeps_locked_anchors_when_only_crossfade_is_checked(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        zone = model.get_zone(0)
        sustain_loop = MODULE.child(zone, "SustainLoop")
        MODULE.set_value(sustain_loop, "Start", 12000)
        MODULE.set_value(sustain_loop, "End", 36000)
        MODULE.set_value(sustain_loop, "Crossfade", "0")
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loops(
            model,
            {
                "loop_detection": True,
                "loop_write_start": False,
                "loop_write_end": False,
                "loop_write_mode": False,
                "loop_write_crossfade": True,
                "param_sustain_loop_start_pct": "99",
                "param_sustain_loop_end_pct": "100",
                "param_sustain_loop_search_number": "50",
                "param_sustain_loop_search_unit": "%",
                "param_sustain_crossfade_policy": "Custom",
                "param_sustain_crossfade_custom_number": "25",
                "param_sustain_crossfade_custom_unit": "%",
            },
            audio_cache,
        )

        self.assertEqual(count, 1)
        sustain = model.read_loop(zone, "SustainLoop")
        self.assertEqual(sustain["start"], "12000")
        self.assertEqual(sustain["end"], "36000")
        self.assertGreater(int(sustain["crossfade"]), 0)

    def test_detect_release_loops_keeps_locked_stop_when_only_crossfade_is_checked(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        zone = model.get_zone(0)
        release_loop = MODULE.child(zone, "ReleaseLoop")
        MODULE.set_value(release_loop, "Start", 12000)
        MODULE.set_value(release_loop, "End", 36000)
        MODULE.set_value(release_loop, "Crossfade", "0")
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loops(
            model,
            {
                "release_loop_detection": True,
                "release_loop_write_start": False,
                "release_loop_write_end": False,
                "release_loop_write_mode": False,
                "release_loop_write_crossfade": True,
                "param_release_loop_start_pct": "99",
                "param_release_loop_start_unit": "%",
                "param_release_loop_search_number": "50",
                "param_release_loop_search_unit": "%",
                "param_release_crossfade_policy": "Custom",
                "param_release_crossfade_custom_number": "25",
                "param_release_crossfade_custom_unit": "%",
                "param_release_threshold": "0.08",
                "param_next_activity_threshold": "0.08",
            },
            audio_cache,
        )

        self.assertEqual(count, 1)
        release = model.read_loop(zone, "ReleaseLoop")
        self.assertEqual(release["start"], "12000")
        self.assertEqual(release["end"], "36000")
        self.assertGreater(int(release["crossfade"]), 0)

    def test_detect_release_loops_prefers_stable_tail_after_note_end(self):
        sr = 48000
        note_t = MODULE.np.arange(sr, dtype=MODULE.np.float64) / sr
        tail_t = MODULE.np.arange(sr // 2, dtype=MODULE.np.float64) / sr
        note = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * note_t)
        tail = 0.04 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * tail_t)
        samples = MODULE.np.concatenate([note, tail]).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loops(
            model,
            {
                "release_loop_detection": True,
                "param_release_loop_start_pct": "20",
                "param_release_loop_search_number": "10",
                "param_release_loop_search_unit": "%",
                "param_release_crossfade_policy": "Custom",
                "param_release_crossfade_custom_number": "25",
                "param_release_crossfade_custom_unit": "%",
                "param_release_threshold": "0.08",
                "param_next_activity_threshold": "0.08",
            },
            audio_cache,
        )

        self.assertEqual(count, 1)
        release = model.read_loop(model.get_zone(0), "ReleaseLoop")
        self.assertGreaterEqual(int(release["start"]), sr)
        self.assertEqual(int(release["end"]), len(samples))

    def test_detect_release_loops_supports_negative_offset_from_note_end(self):
        sr = 48000
        note_t = MODULE.np.arange(sr, dtype=MODULE.np.float64) / sr
        tail_t = MODULE.np.arange(sr // 2, dtype=MODULE.np.float64) / sr
        note = 0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * note_t)
        tail = 0.04 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * tail_t)
        samples = MODULE.np.concatenate([note, tail]).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loops(
            model,
            {
                "release_loop_detection": True,
                "param_release_loop_start_reference": "offset from note end",
                "param_release_loop_start_pct": "-80",
                "param_release_loop_start_unit": "ms",
                "param_release_loop_search_number": "0",
                "param_release_loop_search_unit": "%",
                "param_release_crossfade_policy": "No fade",
                "param_release_threshold": "0.08",
                "param_next_activity_threshold": "0.08",
            },
            audio_cache,
        )

        self.assertEqual(count, 1)
        release = model.read_loop(model.get_zone(0), "ReleaseLoop")
        self.assertLess(int(release["start"]), sr)
        self.assertEqual(int(release["end"]), len(samples))

    def test_optimize_zone_crossfades_updates_release_loop_too(self):
        sr = 48000
        t = MODULE.np.arange(sr * 2, dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        zone = model.get_zone(0)
        for loop_tag in ("SustainLoop", "ReleaseLoop"):
            loop = MODULE.child(zone, loop_tag)
            MODULE.set_value(loop, "Start", 9600)
            MODULE.set_value(loop, "End", 38400)
            MODULE.set_value(loop, "Mode", "1")
            MODULE.set_value(loop, "Crossfade", "0")
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.optimize_zone_crossfades(
            model,
            {
                "loop_detection": True,
                "release_loop_detection": True,
                "crossfade_optimization": True,
                "release_crossfade_optimization": True,
                "param_sustain_crossfade_min_number": "500",
                "param_sustain_crossfade_min_unit": "samples",
                "param_sustain_crossfade_max_number": "50",
                "param_sustain_crossfade_max_unit": "%",
                "param_sustain_crossfade_penalty": "0.35",
                "param_release_crossfade_min_number": "500",
                "param_release_crossfade_min_unit": "samples",
                "param_release_crossfade_max_number": "50",
                "param_release_crossfade_max_unit": "%",
                "param_release_crossfade_penalty": "0.35",
            },
            audio_cache,
        )

        self.assertEqual(count, 1)
        sustain = model.read_loop(zone, "SustainLoop")
        release = model.read_loop(zone, "ReleaseLoop")
        self.assertGreater(int(sustain["crossfade"]), 0)
        self.assertEqual(sustain["crossfade"], release["crossfade"])

    def test_optimize_zone_crossfades_clamps_to_loop_start_preroll(self):
        sr = 48000
        t = MODULE.np.arange(sr, dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 220.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        zone = model.get_zone(0)
        sustain_loop = MODULE.child(zone, "SustainLoop")
        MODULE.set_value(sustain_loop, "Start", 100)
        MODULE.set_value(sustain_loop, "End", 2000)
        MODULE.set_value(sustain_loop, "Crossfade", "0")
        audio_cache = FakeLoopAudioCache(model)
        original_optimizer = MODULE.AudioAnalysis.optimize_crossfade_samples
        MODULE.AudioAnalysis.optimize_crossfade_samples = staticmethod(lambda *args, **kwargs: 500)
        try:
            count = MODULE.SamplerProcessors.optimize_zone_crossfades(
                model,
                {
                    "loop_detection": True,
                    "crossfade_optimization": True,
                    "param_sustain_crossfade_min_number": "500",
                    "param_sustain_crossfade_min_unit": "samples",
                    "param_sustain_crossfade_max_number": "500",
                    "param_sustain_crossfade_max_unit": "samples",
                },
                audio_cache,
            )
        finally:
            MODULE.AudioAnalysis.optimize_crossfade_samples = original_optimizer

        self.assertEqual(count, 1)
        sustain = model.read_loop(zone, "SustainLoop")
        self.assertEqual(sustain["crossfade"], "100")

    def test_detect_zone_loop_detunes_updates_sustain_and_release(self):
        sr = 48000
        duration = 1.0
        t = MODULE.np.arange(int(sr * duration), dtype=MODULE.np.float64) / sr
        samples = (0.4 * MODULE.np.sin(2.0 * MODULE.np.pi * 440.0 * t)).astype(MODULE.np.float32)
        model = FakeLoopModel(samples)
        zone = model.get_zone(0)
        sustain = MODULE.child(zone, "SustainLoop")
        release = MODULE.child(zone, "ReleaseLoop")
        MODULE.set_value(sustain, "Start", 0)
        MODULE.set_value(sustain, "End", 100)
        MODULE.set_value(release, "Start", len(samples) - 100)
        MODULE.set_value(release, "End", len(samples))
        audio_cache = FakeLoopAudioCache(model)

        count = MODULE.SamplerProcessors.detect_zone_loop_detunes(
            model,
            {"loop_detune_detection": True, "release_loop_detune_detection": True},
            audio_cache,
        )

        self.assertEqual(count, 1)
        self.assertNotEqual(model.read_loop(zone, "SustainLoop")["detune"], "0")
        self.assertNotEqual(model.read_loop(zone, "ReleaseLoop")["detune"], "0")

    def test_apply_global_values_updates_loop_modes_and_envelope(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "param_default_loop_mode": "loop",
                "param_default_release_loop_mode": "back and forth",
                "param_env_attack_ms": "12.5",
                "param_env_decay_ms": "345",
                "param_env_sustain": "0.8",
                "param_env_release_ms": "67",
                "param_env_attack_shape": "25",
                "param_env_decay_shape": "-50",
                "param_env_release_shape": "75",
            },
            {
                "default_loop_mode": True,
                "default_release_loop_mode": True,
                "planned_envelope_time": True,
                "planned_envelope_shape": True,
            },
        )

        zone = model.get_zone(0)
        self.assertEqual(model.read_loop(zone, "SustainLoop")["mode"], MODULE.SUSTAIN_MODE_VALUES["loop"])
        self.assertEqual(model.read_loop(zone, "ReleaseLoop")["mode"], MODULE.RELEASE_MODE_VALUES["back-and-forth"])
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/AttackTime"), "12.5")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/DecayTime"), "345")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/SustainLevel"), "0.8")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/ReleaseTime"), "67")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/AttackSlope"), "0.25")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/DecaySlope"), "-0.5")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/ReleaseSlope"), "0.75")

    def test_apply_global_values_updates_generic_lfo_manual_nodes(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "param_lfo_manual::Lfo/IsOn": "false",
                "param_lfo_manual::Lfo/Slot/Value/SimplerLfo/Frequency": "7.5",
                "param_lfo_manual::AuxLfos.0/IsOn": "true",
                "param_lfo_value::VelDst/ModConnections.0/Amount": "77",
                "param_lfo_value::MidiCtrl.0/Feedback": "1",
            },
            {
                "param_lfo_manual::Lfo/IsOn": True,
                "param_lfo_manual::Lfo/Slot/Value/SimplerLfo/Frequency": True,
                "param_lfo_manual::AuxLfos.0/IsOn": True,
                "param_lfo_value::VelDst/ModConnections.0/Amount": True,
                "param_lfo_value::MidiCtrl.0/Feedback": True,
            },
        )

        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Lfo/IsOn"), "false")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Lfo/Slot/Value/SimplerLfo/Frequency"), "7.5")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "AuxLfos.0/IsOn"), "true")
        self.assertEqual(MODULE.get_value_by_path(model.root, "VelDst/ModConnections.0/Amount"), "77")
        self.assertEqual(MODULE.get_value_by_path(model.root, "MidiCtrl.0/Feedback"), "1")

    def test_apply_global_values_creates_aux_lfo_but_skips_optional_missing_routing_nodes(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "param_lfo_manual::AuxLfos.0/Slot/Value/SimplerAuxLfo/Frequency": "6.25",
                "param_lfo_value::AuxLfos.0/Slot/Value/SimplerAuxLfo/ModDst/ModConnections.0/Amount": "17",
                "param_lfo_value::MidiCtrl.7/Feedback": "1",
            },
            {
                "param_lfo_manual::AuxLfos.0/Slot/Value/SimplerAuxLfo/Frequency": True,
                "param_lfo_value::AuxLfos.0/Slot/Value/SimplerAuxLfo/ModDst/ModConnections.0/Amount": True,
                "param_lfo_value::MidiCtrl.7/Feedback": True,
            },
        )

        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "AuxLfos.0/Slot/Value/SimplerAuxLfo/Frequency"), "6.25")
        self.assertIsNone(MODULE.get_value_by_path(model.root, "AuxLfos.0/Slot/Value/SimplerAuxLfo/ModDst/ModConnections.0/Amount"))
        self.assertIsNone(MODULE.get_value_by_path(model.root, "MidiCtrl.7/Feedback"))

    def test_apply_global_values_updates_generic_midi_routing_nodes(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "param_midi_value::KeyDst/ModConnections.0/Connection": "Off",
                "param_midi_value::VelDst/ModConnections.0/Connection": "Sample Selector (M)",
                "param_midi_value::MidiCtrl.0/Feedback": "1",
            },
            {
                "param_midi_value::KeyDst/ModConnections.0/Connection": True,
                "param_midi_value::VelDst/ModConnections.0/Connection": True,
                "param_midi_value::MidiCtrl.0/Feedback": True,
            },
        )

        self.assertEqual(MODULE.get_value_by_path(model.root, "KeyDst/ModConnections.0/Connection"), "0")
        self.assertEqual(MODULE.get_value_by_path(model.root, "VelDst/ModConnections.0/Connection"), "1")
        self.assertEqual(MODULE.get_value_by_path(model.root, "MidiCtrl.0/Feedback"), "1")

    def test_friendly_parameter_label_simplifies_internal_paths(self):
        self.assertEqual(
            MODULE.friendly_parameter_label("Filter/Slot/Value/SimplerFilter/Type", "Filter"),
            "Filter type",
        )
        self.assertEqual(
            MODULE.friendly_parameter_label("Filter/Slot/Value/SimplerFilter/Envelope/AttackTime", "Filter"),
            "Envelope attack time",
        )
        self.assertEqual(
            MODULE.friendly_parameter_label("KeyDst/ModConnections.0/Connection", "KeyDst"),
            "Mod connection 0 connection",
        )

    def test_apply_global_values_updates_generic_filter_manual_nodes(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "param_filter_manual::Filter/IsOn": "false",
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Freq": "1234.5",
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Envelope/Amount": "0.25",
                "param_filter_manual::Shaper/Slot/Value/SimplerShaper/Amount": "42",
            },
            {
                "param_filter_manual::Filter/IsOn": True,
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Freq": True,
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Envelope/Amount": True,
                "param_filter_manual::Shaper/Slot/Value/SimplerShaper/Amount": True,
            },
        )

        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Filter/IsOn"), "false")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Filter/Slot/Value/SimplerFilter/Freq"), "1234.5")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Filter/Slot/Value/SimplerFilter/Envelope/Amount"), "0.25")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Shaper/Slot/Value/SimplerShaper/Amount"), "42")

    def test_apply_global_values_synthesizes_missing_filter_and_shaper_nodes(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Freq": "987.6",
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Envelope/Amount": "12",
                "param_filter_manual::Shaper/Slot/Value/SimplerShaper/Amount": "23",
            },
            {
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Freq": True,
                "param_filter_manual::Filter/Slot/Value/SimplerFilter/Envelope/Amount": True,
                "param_filter_manual::Shaper/Slot/Value/SimplerShaper/Amount": True,
            },
        )

        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Filter/Slot/Value/SimplerFilter/Freq"), "987.6")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Filter/Slot/Value/SimplerFilter/Envelope/Amount"), "12")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Shaper/Slot/Value/SimplerShaper/Amount"), "23")

    def test_apply_global_values_updates_default_preset_simple_fields(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "player_loopmod_sample_start": "0.25",
                "player_loopmod_loop_on": True,
                "player_reverse": True,
                "pitch_transpose_key": "12",
                "pitch_transpose_fine": "-7",
                "globals_pitch_bend_range": "3",
                "globals_mpe_pitch_bend_range": "24",
                "amp_panorama": "0.4",
                "env_attack_level": "0.5",
                "oneshot_sustain_mode": "1",
                "globals_portamento_time": "120",
                "globals_env_include_attack": False,
                "mmap_load_in_ram": True,
                "mmap_layer_crossfade": "0.35",
                "preset_user_name": "renamed preset",
                "preset_creator": "Codex Test",
            },
            {
                "player_loopmod_sample_start": True,
                "player_loopmod_loop_on": True,
                "player_reverse": True,
                "pitch_transpose_key": True,
                "pitch_transpose_fine": True,
                "globals_pitch_bend_range": True,
                "globals_mpe_pitch_bend_range": True,
                "amp_panorama": True,
                "env_attack_level": True,
                "oneshot_sustain_mode": True,
                "globals_portamento_time": True,
                "globals_env_include_attack": True,
                "mmap_load_in_ram": True,
                "mmap_layer_crossfade": True,
                "preset_user_name": True,
                "preset_creator": True,
            },
        )

        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Player/LoopModulators/SampleStart"), "0.25")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Player/LoopModulators/LoopOn"), "true")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Player/Reverse"), "true")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Pitch/TransposeKey"), "12")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Pitch/TransposeFine"), "-7")
        self.assertEqual(MODULE.get_value_by_path(model.root, "Globals/PitchBendRange"), "3")
        self.assertEqual(MODULE.get_value_by_path(model.root, "Globals/MpePitchBendRange"), "24")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Panorama"), "0.4")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/AttackLevel"), "0.5")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/OneShotEnvelope/SustainMode"), "1")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "AuxEnv/IsOn"), "false")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Globals/PortamentoTime"), "120")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Globals/EnvScale/EnvTimeIncludeAttack"), "false")
        self.assertEqual(MODULE.get_value_by_path(model.root, "MultiSampleMap/LoadInRam"), "true")
        self.assertEqual(MODULE.get_value_by_path(model.root, "MultiSampleMap/LayerCrossfade"), "0.35")
        self.assertEqual(MODULE.find_first_value_node_by_tag(model.root, "UserName").attrib.get("Value"), "renamed preset")
        self.assertEqual(model.creator(), "Codex Test")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Player/SubOsc/IsOn"), "false")

    def test_apply_global_values_updates_individual_envelope_parameters(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "param_env_attack_ms": "3.5",
                "param_env_decay_ms": "999",
                "param_env_sustain": "0.25",
                "param_env_release_ms": "44",
                "param_env_attack_shape": "25",
                "param_env_decay_shape": "-50",
                "param_env_release_shape": "75",
            },
            {
                "param_env_attack_ms": True,
                "param_env_decay_ms": False,
                "param_env_sustain": True,
                "param_env_release_ms": False,
                "param_env_attack_shape": True,
                "param_env_decay_shape": False,
                "param_env_release_shape": True,
            },
        )

        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/AttackTime"), "3.5")
        self.assertNotEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/DecayTime"), "999")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/SustainLevel"), "0.25")
        self.assertNotEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/ReleaseTime"), "44")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/AttackSlope"), "0.25")
        self.assertNotEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/DecaySlope"), "-0.5")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "VolumeAndPan/Envelope/ReleaseSlope"), "0.75")

    def test_rewrite_relative_sample_paths_recomputes_relative_path(self):
        model = self.load_model("test01.adv")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            adv_dir = tmp / "preset_dir"
            adv_dir.mkdir()
            sample_dir = tmp / "samples"
            sample_dir.mkdir()
            sample_path = sample_dir / "sample.wav"
            sample_path.write_bytes(b"RIFFTEST")
            model.source_path = adv_dir / "preset.adv"
            model.set_zone_sample_reference(model.get_zone(0), absolute_path=str(sample_path), relative_path="")

            count = MODULE.SamplerProcessors.rewrite_relative_sample_paths(model, {})

            self.assertEqual(count, 1)
            self.assertEqual(
                model.extract_sample_path(model.get_zone(0))[1],
                MODULE.os.path.relpath(str(sample_path), str(adv_dir)).replace("\\", "/"),
            )

    def test_relink_samples_from_folder_matches_by_basename(self):
        model = self.load_model("test01.adv")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            adv_dir = tmp / "preset_dir"
            adv_dir.mkdir()
            old_dir = tmp / "old"
            old_dir.mkdir()
            new_dir = tmp / "new"
            new_dir.mkdir()
            old_path = old_dir / "sample.wav"
            new_path = new_dir / "sample.wav"
            old_path.write_bytes(b"OLD")
            new_path.write_bytes(b"NEW")
            model.source_path = adv_dir / "preset.adv"
            model.set_zone_sample_reference(model.get_zone(0), absolute_path=str(old_path), relative_path="")

            count = MODULE.SamplerProcessors.relink_samples_from_folder(
                model,
                {"param_sample_relink_folder": str(new_dir), "param_sample_relink_relative": True},
            )

            self.assertEqual(count, 1)
            self.assertEqual(model.extract_sample_path(model.get_zone(0))[0], str(new_path.resolve()))

    def test_copy_rename_relink_samples_copies_and_updates_reference(self):
        model = self.load_model("test01.adv")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            adv_dir = tmp / "preset_dir"
            adv_dir.mkdir()
            source_dir = tmp / "source"
            source_dir.mkdir()
            out_dir = tmp / "copied"
            sample_path = source_dir / "tone.wav"
            sample_path.write_bytes(b"TONE")
            model.source_path = adv_dir / "preset.adv"
            model.set_zone_sample_reference(model.get_zone(0), absolute_path=str(sample_path), relative_path="")

            count = MODULE.SamplerProcessors.copy_rename_relink_samples(
                model,
                {
                    "param_sample_copy_folder": str(out_dir),
                    "param_sample_copy_pattern": "[preset]_[sample]",
                    "param_sample_copy_relative": True,
                },
            )

            self.assertEqual(count, 1)
            abs_path, rel_path = model.extract_sample_path(model.get_zone(0))
            self.assertTrue(Path(abs_path).exists())
            self.assertTrue(Path(abs_path).name.endswith(".wav"))
            self.assertIn("tone", Path(abs_path).stem.lower())
            self.assertTrue(rel_path)

    def test_zone_summary_and_apply_zone_values_support_tune_scale(self):
        model = self.load_model("test01.adv")
        summary = model.read_zone_summary(0)
        self.assertNotEqual(summary["tune_scale"], "")

        zone_values = {
            "name": summary["name"],
            "volume_db": "{:.4f}".format(summary["volume_db"]),
            "root_key": summary["root_key"],
            "detune": summary["detune"],
            "tune_scale": "87.5",
            "sample_start": summary["sample_start"],
            "sample_end": summary["sample_end"],
        }
        range_values = {}
        for prefix, source_key in (("key", "key_range"), ("vel", "velocity_range"), ("sel", "selector_range")):
            for sub in ("min", "max", "xfade_min", "xfade_max"):
                range_values["{}_{}".format(prefix, sub)] = summary[source_key][sub]
        loop_values = {}
        for prefix, source_key in (("sustain", "sustain_loop"), ("release", "release_loop")):
            for sub in ("start", "end", "mode", "crossfade", "detune"):
                loop_values["{}_{}".format(prefix, sub)] = summary[source_key][sub]

        model.apply_zone_values(0, zone_values, range_values, loop_values)

        self.assertEqual(MODULE.get_value(model.get_zone(0), "TuneScale", ""), "87.5")

    def test_read_global_summary_and_apply_global_values_support_globals_num_voices(self):
        model = self.load_model("test01.adv")

        self.assertEqual(model.read_global_summary()["voices"], "7")

        model.apply_global_values({"voices": "9"}, {"voices": True})

        self.assertEqual(MODULE.get_value_by_path(model.root, "Globals/NumVoices"), "9")

    def test_apply_global_values_updates_interpolation_and_pitch_bend_ranges(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "player_interpolation_mode": "1",
                "globals_pitch_bend_range": "24",
                "globals_mpe_pitch_bend_range": "48",
            },
            {
                "player_interpolation_mode": True,
                "globals_pitch_bend_range": True,
                "globals_mpe_pitch_bend_range": True,
            },
        )

        self.assertEqual(MODULE.get_value_by_path(model.root, "Player/InterpolationMode"), "1")
        self.assertEqual(MODULE.get_value_by_path(model.root, "Globals/PitchBendRange"), "24")
        self.assertEqual(MODULE.get_value_by_path(model.root, "Globals/MpePitchBendRange"), "48")

    def test_apply_global_values_updates_default_tune_scale_for_all_zones(self):
        model = self.load_model("test02.adv")

        model.apply_global_values(
            {"param_default_tune_scale": "-200"},
            {"default_tune_scale": True},
        )

        values = [MODULE.get_value(model.get_zone(i), "TuneScale", "") for i in range(model.zone_count())]
        self.assertEqual(values, ["-200", "-200", "-200"])

    def test_apply_global_values_synthesizes_aux_env_pitch_env_and_sub_osc_nodes(self):
        model = self.load_model("test01.adv")

        model.apply_global_values(
            {
                "param_aux_env_manual::AuxEnv/Slot/Value/SimplerAuxEnvelope/AttackTime": "12.5",
                "param_aux_env_value::AuxEnv/Slot/Value/SimplerAuxEnvelope/ModDst/ModConnections.0/Amount": "33",
                "param_pitch_env_manual::Pitch/Envelope/Slot/Value/SimplerPitchEnvelope/Amount": "-7",
                "param_sub_osc_manual::Player/SubOsc/Slot/Value/SimplerSubOsc/Type": "5",
            },
            {
                "param_aux_env_manual::AuxEnv/Slot/Value/SimplerAuxEnvelope/AttackTime": True,
                "param_aux_env_value::AuxEnv/Slot/Value/SimplerAuxEnvelope/ModDst/ModConnections.0/Amount": True,
                "param_pitch_env_manual::Pitch/Envelope/Slot/Value/SimplerPitchEnvelope/Amount": True,
                "param_sub_osc_manual::Player/SubOsc/Slot/Value/SimplerSubOsc/Type": True,
            },
        )

        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "AuxEnv/Slot/Value/SimplerAuxEnvelope/AttackTime"), "12.5")
        self.assertEqual(MODULE.get_value_by_path(model.root, "AuxEnv/Slot/Value/SimplerAuxEnvelope/ModDst/ModConnections.0/Amount"), "33")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Pitch/Envelope/Slot/Value/SimplerPitchEnvelope/Amount"), "-7")
        self.assertEqual(MODULE.get_manual_value_by_path(model.root, "Player/SubOsc/Slot/Value/SimplerSubOsc/Type"), "5")

        self.assertEqual(model.root.find("MultiSampler/AuxEnv/Slot/Value/SimplerAuxEnvelope").attrib.get("Id"), "0")
        self.assertEqual(model.root.find("MultiSampler/Pitch/Envelope/Slot/Value/SimplerPitchEnvelope").attrib.get("Id"), "0")
        self.assertEqual(model.root.find("MultiSampler/Player/SubOsc/Slot/Value/SimplerSubOsc").attrib.get("Id"), "0")


if __name__ == "__main__":
    unittest.main()
