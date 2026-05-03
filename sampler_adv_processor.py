#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Standalone Tkinter tool for post-processing Ableton Sampler .adv files."""


import gzip
import json
import math
import os
import shutil
import traceback
import copy
import re
import wave
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import numpy as np
except Exception:
    np = None

try:
    import soundfile as sf
except Exception:
    sf = None

try:
    from scipy import signal
except Exception:
    signal = None

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False


# =============================================================================
# Constants / mappings
# =============================================================================

APP_TITLE = "Sampler ADV Processor V1.6.0"
TEMPLATE_LIBRARY_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_ADV_SCAFFOLD_PATH = Path(__file__).resolve().parent / "test01.adv"
DEFAULT_TOOL_TEMPLATE_PATH = TEMPLATE_LIBRARY_DIR / "default values 01.json"
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".flac", ".ogg", ".mp3", ".m4a", ".caf"}


def load_default_tool_template():
    try:
        if DEFAULT_TOOL_TEMPLATE_PATH.exists():
            return json.loads(DEFAULT_TOOL_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


DEFAULT_TOOL_TEMPLATE = load_default_tool_template()
DEFAULT_TOOL_TEMPLATE_GLOBAL_VALUES = (DEFAULT_TOOL_TEMPLATE or {}).get("global_values", {})
DEFAULT_TOOL_TEMPLATE_GLOBAL_UPDATE = (DEFAULT_TOOL_TEMPLATE or {}).get("global_update", {})
DEFAULT_TOOL_TEMPLATE_PROCESSING_UPDATE = (DEFAULT_TOOL_TEMPLATE or {}).get("processing_update", {})

SCRATCH_PRESET_GLOBAL_VALUES = {
    "param_default_tune_scale": "100",
    "voices": "32",
    "rr": False,
    "rr_mode": "forward",
    "rr_reset": "none",
    "rr_seed": "-1501161561",
    "param_env_attack_ms": "0.200000003",
    "param_env_decay_ms": "4999.99951",
    "param_env_sustain": "1",
    "param_env_release_ms": "30",
    "param_env_attack_shape": "0",
    "param_env_decay_shape": "0",
    "param_env_release_shape": "100",
}

SCRATCH_PRESET_GLOBAL_UPDATES = {
    "default_tune_scale": True,
    "voices": True,
    "rr": True,
    "rr_mode": True,
    "rr_reset": True,
    "rr_seed": True,
    "planned_envelope_time": True,
    "planned_envelope_shape": True,
}

DEFAULT_REFINE_RELEASE_THRESHOLD = "0.0005"
DEFAULT_REFINE_TAIL_NUMBER = "2000"
DEFAULT_REFINE_TAIL_UNIT = "ms"
DEFAULT_REFINE_NEXT_ACTIVITY_THRESHOLD = "0.0003"
DEFAULT_REFINE_SHIFT_START_NUMBER = "0"
DEFAULT_REFINE_SHIFT_START_UNIT = "ms"
DEFAULT_REFINE_SHIFT_START_TEMPO = "120"
DEFAULT_REFINE_SHIFT_STOP_NUMBER = "0"
DEFAULT_REFINE_SHIFT_STOP_UNIT = "ms"
DEFAULT_REFINE_SHIFT_STOP_TEMPO = "120"

DEFAULT_DETECTION_SPLIT_SENSITIVITY = "0.5"
DEFAULT_DETECTION_SPLIT_MIN_DURATION = "1000"
DEFAULT_DETECTION_PROFILE_COMPRESSION = "100"
DEFAULT_GATE_SPLIT_SENSITIVITY = "0.5"
DEFAULT_GATE_SPLIT_MIN_DURATION = "10000"
DEFAULT_GATE_PROFILE_COMPRESSION = "100"
DEFAULT_GATE_STOP_HYSTERESIS_PCT = "60"
DEFAULT_GATE_START_PLACEMENT = "local attack"
DEFAULT_DIAPASON_HZ = "440"
DEFAULT_PITCH_WINDOW_START_NUMBER = "0"
DEFAULT_PITCH_WINDOW_START_UNIT = "ms"
DEFAULT_PITCH_WINDOW_STOP_NUMBER = "100"
DEFAULT_PITCH_WINDOW_STOP_UNIT = "%"
WAVEFORM_PREVIEW_LOOP_SEARCH_CAP_SECONDS = 2.0

SUSTAIN_MODE_VALUES = {
    "on": "1",
    "loop": "2",
    "back and forth": "3",
}

RELEASE_MODE_VALUES = {
    "off": "0",
    "on": "1",
    "loop": "2",
    "back and forth": "3",
}

LEGACY_MODE_LABEL_ALIASES = {
    "no": "off",
    "No": "off",
    "forward": "on",
    "Forward": "on",
    "back-and-forth": "back and forth",
    "Back-and-forth": "back and forth",
}

LOOP_CROSSFADE_POLICY_LABELS = [
    "No fade",
    "One waveform",
    "Longest possible",
    "Custom",
]

ROUND_ROBIN_MODE_LABEL_TO_VALUE = {
    "forward": "0",
    "backward": "1",
    "other": "2",
    "random": "3",
}
ROUND_ROBIN_MODE_VALUE_TO_LABEL = {v: k for k, v in ROUND_ROBIN_MODE_LABEL_TO_VALUE.items()}

ROUND_ROBIN_RESET_LABEL_TO_VALUE = {
    "none": "0",
    "1/4": "1",
    "1/2": "2",
    "1 bar": "3",
    "2 bars": "4",
    "4 bars": "5",
}
ROUND_ROBIN_RESET_VALUE_TO_LABEL = {v: k for k, v in ROUND_ROBIN_RESET_LABEL_TO_VALUE.items()}

VOICE_COUNT_CHOICES = ["1", "2", "3", "4", "5", "6", "7", "8", "10", "12", "14", "16", "20", "24", "32"]
FILENAME_MAPPING_PATTERN = re.compile(r"(?i)(?:^|[^A-Za-z])([PVCD])\s*([+-]?\d+)")


def build_enum_maps(labels, values=None):
    if values is None:
        values = [str(i) for i in range(len(labels))]
    label_to_value = {str(label): str(value) for label, value in zip(labels, values)}
    value_to_label = {str(value): str(label) for label, value in zip(labels, values)}
    return {
        "choices": list(labels),
        "label_to_value": label_to_value,
        "value_to_label": value_to_label,
    }


ENUM_MAPS = {
    "voices": build_enum_maps(VOICE_COUNT_CHOICES, VOICE_COUNT_CHOICES),
    "interpolation_mode": build_enum_maps(["no", "normal", "good", "best"]),
    "portamento_mode": build_enum_maps(["off", "portamento", "glide"]),
    "envelope_loop_mode": build_enum_maps(["none", "loop", "beat", "sync", "trigger"]),
    "lfo_type": build_enum_maps(["sine", "square", "triangle", "sawtooth down", "sawtooth up", "sample & hold"]),
    "lfo_rate_type": build_enum_maps(["Hz", "Tempo"]),
    "lfo_stereo_mode": build_enum_maps(["phase", "spin"]),
    "filter_type": build_enum_maps(["lowpass", "highpass", "bandpass", "notch", "morph"]),
    "filter_slope": build_enum_maps(["12", "24"], ["false", "true"]),
    "filter_circuit": build_enum_maps(["Clean", "OSR", "MS2", "SMP", "PRD"]),
    "shaper_type": build_enum_maps(["soft", "hard", "sine", "4bit"]),
    "sub_osc_mode": build_enum_maps(["FM", "AM"]),
    "sub_osc_type": build_enum_maps([
        "Sine",
        "Sine 4 bit",
        "Sine 8 bit",
        "Sw 3",
        "Sw 4",
        "Sw 8",
        "Sw 16",
        "Sw 32",
        "Sw 64",
        "Sw D",
        "Sq 3",
        "Sq 4",
        "Sq 8",
        "Sq 16",
        "Sq 32",
        "Sq 64",
        "Sq D",
        "Tri",
        "Noise",
    ]),
    "routing_connection": build_enum_maps([
        "Sample Selector (M)",
        "Sample Offset (M)",
        "Loop Start (M)",
        "Loop Length (M)",
        "Release Loop (M)",
        "Pitch (M)",
        "Pitch Sample Only (S)",
        "Pitch Envelope Amount (M)",
        "Volume Osc (S)",
        "Shaper Amt (S)",
        "Filter Freq (S)",
        "Filter Res (S)",
        "Filter Morph (S)",
        "Filter Drive (S)",
        "Filter Envelope Amount (S)",
        "Volume (S)",
        "Panorama (M)",
        "Time (M)",
        "LFO 1 Rate (S)",
        "LFO 1 Amount Vol (S)",
        "LFO 1 Amount Pan (M)",
        "LFO 1 Amount Filter (S)",
        "LFO 1 Amount Pitch (M)",
        "LFO 2 Rate (S)",
        "LFO 2 Amount A (S)",
        "LFO 2 Amount B (S)",
        "LFO 3 Rate (S)",
        "LFO 3 Amount A (S)",
        "LFO 3 Amount B (S)",
    ]),
}

MANUAL_PARAM_SKIP_TAGS = {
    "LomId",
    "AutomationTarget",
    "MidiControllerRange",
    "ModulationTarget",
    "MidiCCOnOffThresholds",
}

MANUAL_TEMPLATE_SPECS = {
    "Lfo": [
        ("IsOn", "bool", "false", None, None, False),
        ("Slot/Value/SimplerLfo/Type", "numeric", "0", "0", "5", False),
        ("Slot/Value/SimplerLfo/Frequency", "numeric", "7", "0.009999999776", "30", True),
        ("Slot/Value/SimplerLfo/RateType", "numeric", "0", "0", "1", False),
        ("Slot/Value/SimplerLfo/BeatRate", "numeric", "4", "0", "21", True),
        ("Slot/Value/SimplerLfo/StereoMode", "numeric", "0", "0", "1", False),
        ("Slot/Value/SimplerLfo/Spin", "numeric", "0", "0", "0.5", True),
        ("Slot/Value/SimplerLfo/Phase", "numeric", "0", "0", "360", True),
        ("Slot/Value/SimplerLfo/Offset", "numeric", "0", "0", "360", True),
        ("Slot/Value/SimplerLfo/FrequencyKeyScale", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerLfo/Smooth", "numeric", "0.5", "0", "1", True),
        ("Slot/Value/SimplerLfo/Attack", "numeric", "0.1000000015", "0.1000000015", "20000", True),
        ("Slot/Value/SimplerLfo/Retrigger", "bool", "true", None, None, False),
        ("Slot/Value/SimplerLfo/Width", "numeric", "0", "0", "1", True),
    ],
    "AuxLfos.0": [
        ("IsOn", "bool", "false", None, None, False),
    ],
    "AuxLfos.0/Slot/Value/SimplerAuxLfo": [
        ("Type", "numeric", "0", "0", "5", False),
        ("Frequency", "numeric", "4.43943739", "0.009999999776", "30", True),
        ("RateType", "numeric", "0", "0", "1", False),
        ("BeatRate", "numeric", "4", "0", "21", True),
        ("StereoMode", "numeric", "0", "0", "1", False),
        ("Spin", "numeric", "0", "0", "0.5", True),
        ("Phase", "numeric", "0", "0", "360", True),
        ("Offset", "numeric", "0", "0", "360", True),
        ("FrequencyKeyScale", "numeric", "0", "0", "1", True),
        ("Smooth", "numeric", "0.5", "0", "1", True),
        ("Attack", "numeric", "0.1000000015", "0.1000000015", "20000", True),
        ("Retrigger", "bool", "true", None, None, False),
        ("Width", "numeric", "0", "0", "1", True),
    ],
    "AuxLfos.1": [
        ("IsOn", "bool", "false", None, None, False),
    ],
    "AuxLfos.1/Slot/Value/SimplerAuxLfo": [
        ("Type", "numeric", "0", "0", "5", False),
        ("Frequency", "numeric", "4.43943739", "0.009999999776", "30", True),
        ("RateType", "numeric", "0", "0", "1", False),
        ("BeatRate", "numeric", "4", "0", "21", True),
        ("StereoMode", "numeric", "0", "0", "1", False),
        ("Spin", "numeric", "0", "0", "0.5", True),
        ("Phase", "numeric", "0", "0", "360", True),
        ("Offset", "numeric", "0", "0", "360", True),
        ("FrequencyKeyScale", "numeric", "0", "0", "1", True),
        ("Smooth", "numeric", "0.5", "0", "1", True),
        ("Attack", "numeric", "0.1000000015", "0.1000000015", "20000", True),
        ("Retrigger", "bool", "true", None, None, False),
        ("Width", "numeric", "0", "0", "1", True),
    ],
    "AuxEnv": [
        ("IsOn", "bool", "false", None, None, False),
        ("Slot/Value/SimplerAuxEnvelope/AttackTime", "numeric", "0.1000000015", "0.1000000015", "20000", True),
        ("Slot/Value/SimplerAuxEnvelope/AttackLevel", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerAuxEnvelope/AttackSlope", "numeric", "0", "-1", "1", True),
        ("Slot/Value/SimplerAuxEnvelope/DecayTime", "numeric", "600", "1", "60000", True),
        ("Slot/Value/SimplerAuxEnvelope/DecayLevel", "numeric", "1", "0", "1", True),
        ("Slot/Value/SimplerAuxEnvelope/DecaySlope", "numeric", "1", "-1", "1", True),
        ("Slot/Value/SimplerAuxEnvelope/SustainLevel", "numeric", "1", "0", "1", True),
        ("Slot/Value/SimplerAuxEnvelope/ReleaseTime", "numeric", "50", "1", "60000", True),
        ("Slot/Value/SimplerAuxEnvelope/ReleaseLevel", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerAuxEnvelope/ReleaseSlope", "numeric", "1", "-1", "1", True),
        ("Slot/Value/SimplerAuxEnvelope/LoopMode", "numeric", "0", "0", "4", False),
        ("Slot/Value/SimplerAuxEnvelope/LoopTime", "numeric", "100", "0.200000003", "20000", True),
        ("Slot/Value/SimplerAuxEnvelope/RepeatTime", "numeric", "3", "0", "14", True),
        ("Slot/Value/SimplerAuxEnvelope/TimeVelScale", "numeric", "0", "-100", "100", True),
    ],
    "Pitch/Envelope": [
        ("IsOn", "bool", "false", None, None, False),
        ("Slot/Value/SimplerPitchEnvelope/AttackTime", "numeric", "0.1000000015", "0.1000000015", "20000", True),
        ("Slot/Value/SimplerPitchEnvelope/AttackLevel", "numeric", "0", "-1", "1", True),
        ("Slot/Value/SimplerPitchEnvelope/AttackSlope", "numeric", "0", "-1", "1", True),
        ("Slot/Value/SimplerPitchEnvelope/DecayTime", "numeric", "600", "1", "60000", True),
        ("Slot/Value/SimplerPitchEnvelope/DecayLevel", "numeric", "0", "-1", "1", True),
        ("Slot/Value/SimplerPitchEnvelope/DecaySlope", "numeric", "1", "-1", "1", True),
        ("Slot/Value/SimplerPitchEnvelope/SustainLevel", "numeric", "0", "-1", "1", True),
        ("Slot/Value/SimplerPitchEnvelope/ReleaseTime", "numeric", "50", "1", "60000", True),
        ("Slot/Value/SimplerPitchEnvelope/ReleaseLevel", "numeric", "0", "-1", "1", True),
        ("Slot/Value/SimplerPitchEnvelope/ReleaseSlope", "numeric", "1", "-1", "1", True),
        ("Slot/Value/SimplerPitchEnvelope/LoopMode", "numeric", "0", "0", "4", False),
        ("Slot/Value/SimplerPitchEnvelope/LoopTime", "numeric", "100", "0.200000003", "20000", True),
        ("Slot/Value/SimplerPitchEnvelope/RepeatTime", "numeric", "3", "0", "14", True),
        ("Slot/Value/SimplerPitchEnvelope/TimeVelScale", "numeric", "0", "-100", "100", True),
        ("Slot/Value/SimplerPitchEnvelope/Amount", "numeric", "0", "-48", "48", True),
    ],
    "Player/SubOsc": [
        ("IsOn", "bool", "false", None, None, False),
        ("Slot/Value/SimplerSubOsc/Mode", "numeric", "0", "0", "1", False),
        ("Slot/Value/SimplerSubOsc/Type", "numeric", "0", "0", "20", False),
        ("Slot/Value/SimplerSubOsc/Volume", "numeric", "1", "0.0003162277571", "1", True),
        ("Slot/Value/SimplerSubOsc/VolumeVelScale", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerSubOsc/IsFixedFreq", "bool", "false", None, None, False),
        ("Slot/Value/SimplerSubOsc/TuneCoarse", "numeric", "0", "-2", "48", True),
        ("Slot/Value/SimplerSubOsc/TuneFine", "numeric", "0", "0", "1000", True),
        ("Slot/Value/SimplerSubOsc/FreqFixed", "numeric", "50", "10", "1000", True),
        ("Slot/Value/SimplerSubOsc/FreqFixedMul", "numeric", "0", "0", "4", True),
        ("Slot/Value/SimplerSubOsc/Envelope/AttackTime", "numeric", "0.1000000015", "0.1000000015", "20000", True),
        ("Slot/Value/SimplerSubOsc/Envelope/AttackLevel", "numeric", "0.0003162277571", "0.0003162277571", "1", True),
        ("Slot/Value/SimplerSubOsc/Envelope/AttackSlope", "numeric", "0", "-1", "1", True),
        ("Slot/Value/SimplerSubOsc/Envelope/DecayTime", "numeric", "600", "1", "60000", True),
        ("Slot/Value/SimplerSubOsc/Envelope/DecayLevel", "numeric", "1", "0.0003162277571", "1", True),
        ("Slot/Value/SimplerSubOsc/Envelope/DecaySlope", "numeric", "1", "-1", "1", True),
        ("Slot/Value/SimplerSubOsc/Envelope/SustainLevel", "numeric", "1", "0.0003162277571", "1", True),
        ("Slot/Value/SimplerSubOsc/Envelope/ReleaseTime", "numeric", "50", "1", "60000", True),
        ("Slot/Value/SimplerSubOsc/Envelope/ReleaseLevel", "numeric", "0.0003162277571", "0.0003162277571", "1", True),
        ("Slot/Value/SimplerSubOsc/Envelope/ReleaseSlope", "numeric", "1", "-1", "1", True),
        ("Slot/Value/SimplerSubOsc/Envelope/LoopMode", "numeric", "0", "0", "4", False),
        ("Slot/Value/SimplerSubOsc/Envelope/LoopTime", "numeric", "100", "0.200000003", "20000", True),
        ("Slot/Value/SimplerSubOsc/Envelope/RepeatTime", "numeric", "3", "0", "14", True),
        ("Slot/Value/SimplerSubOsc/Envelope/TimeVelScale", "numeric", "0", "-100", "100", True),
    ],
    "Filter": [
        ("IsOn", "bool", "false", None, None, False),
        ("Slot/Value/SimplerFilter/LegacyType", "numeric", "0", "0", "5", False),
        ("Slot/Value/SimplerFilter/Type", "numeric", "4", "0", "4", False),
        ("Slot/Value/SimplerFilter/CircuitLpHp", "numeric", "1", "0", "4", False),
        ("Slot/Value/SimplerFilter/CircuitBpNoMo", "numeric", "0", "0", "1", False),
        ("Slot/Value/SimplerFilter/Slope", "bool", "false", None, None, False),
        ("Slot/Value/SimplerFilter/Freq", "numeric", "289.780151", "30", "22000", True),
        ("Slot/Value/SimplerFilter/LegacyQ", "numeric", "0.6999999881", "0.3000000119", "10", True),
        ("Slot/Value/SimplerFilter/Res", "numeric", "0.625", "0", "1.25", True),
        ("Slot/Value/SimplerFilter/X", "numeric", "0.06499999762", "0", "1", True),
        ("Slot/Value/SimplerFilter/Drive", "numeric", "0", "0", "24", True),
        ("Slot/Value/SimplerFilter/Envelope/AttackTime", "numeric", "0.1000000015", "0.1000000015", "20000", True),
        ("Slot/Value/SimplerFilter/Envelope/AttackLevel", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerFilter/Envelope/AttackSlope", "numeric", "0", "-1", "1", True),
        ("Slot/Value/SimplerFilter/Envelope/DecayTime", "numeric", "600", "1", "60000", True),
        ("Slot/Value/SimplerFilter/Envelope/DecayLevel", "numeric", "1", "0", "1", True),
        ("Slot/Value/SimplerFilter/Envelope/DecaySlope", "numeric", "1", "-1", "1", True),
        ("Slot/Value/SimplerFilter/Envelope/SustainLevel", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerFilter/Envelope/ReleaseTime", "numeric", "50", "1", "60000", True),
        ("Slot/Value/SimplerFilter/Envelope/ReleaseLevel", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerFilter/Envelope/ReleaseSlope", "numeric", "1", "-1", "1", True),
        ("Slot/Value/SimplerFilter/Envelope/LoopMode", "numeric", "0", "0", "4", False),
        ("Slot/Value/SimplerFilter/Envelope/LoopTime", "numeric", "100", "0.200000003", "20000", True),
        ("Slot/Value/SimplerFilter/Envelope/RepeatTime", "numeric", "3", "0", "14", True),
        ("Slot/Value/SimplerFilter/Envelope/TimeVelScale", "numeric", "0", "-100", "100", True),
        ("Slot/Value/SimplerFilter/Envelope/IsOn", "bool", "false", None, None, False),
        ("Slot/Value/SimplerFilter/Envelope/Amount", "numeric", "0", "-72", "72", True),
        ("Slot/Value/SimplerFilter/ModByPitch", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerFilter/ModByVelocity", "numeric", "0", "0", "1", True),
        ("Slot/Value/SimplerFilter/ModByLfo", "numeric", "0", "0", "24", True),
    ],
    "Shaper": [
        ("IsOn", "bool", "false", None, None, False),
        ("Slot/Value/SimplerShaper/Type", "numeric", "0", "0", "3", False),
        ("Slot/Value/SimplerShaper/Amount", "numeric", "0", "0", "100", True),
        ("Slot/Value/SimplerShaper/Structure", "bool", "false", None, None, False),
    ],
}

VALUE_TEMPLATE_SPECS = {
    "KeyDst": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
    ],
    "VelDst": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
    ],
    "RelVelDst": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
    ],
    "MidiCtrl.0": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
        ("Feedback", "0"),
    ],
    "MidiCtrl.1": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
        ("Feedback", "0"),
    ],
    "MidiCtrl.2": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
        ("Feedback", "0"),
    ],
    "MidiCtrl.3": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
        ("Feedback", "0"),
    ],
    "MidiCtrl.4": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
        ("Feedback", "0"),
    ],
    "MidiCtrl.5": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
        ("Feedback", "0"),
    ],
    "MidiCtrl.6": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
        ("Feedback", "0"),
    ],
    "MidiCtrl.7": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
        ("Feedback", "0"),
    ],
    "AuxEnv/Slot/Value/SimplerAuxEnvelope/ModDst": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
    ],
    "AuxLfos.0/Slot/Value/SimplerAuxLfo/ModDst": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
    ],
    "AuxLfos.1/Slot/Value/SimplerAuxLfo/ModDst": [
        ("ModConnections.0/Amount", "0"),
        ("ModConnections.0/Connection", "0"),
        ("ModConnections.1/Amount", "0"),
        ("ModConnections.1/Connection", "0"),
    ],
}

OPTIONAL_GENERIC_MANUAL_BASES = {
    "AuxLfos.0/Slot/Value/SimplerAuxLfo",
    "AuxLfos.1/Slot/Value/SimplerAuxLfo",
}

OPTIONAL_GENERIC_VALUE_BASES = {
    "MidiCtrl.6",
    "MidiCtrl.7",
    "AuxLfos.0/Slot/Value/SimplerAuxLfo/ModDst",
    "AuxLfos.1/Slot/Value/SimplerAuxLfo/ModDst",
}


def apply_template_defaults_to_synthesized_specs():
    if not DEFAULT_TOOL_TEMPLATE_GLOBAL_VALUES:
        return

    def find_base_path(full_path, specs_map):
        matches = [base for base in specs_map if full_path == base or full_path.startswith(base + "/")]
        if not matches:
            return None
        return max(matches, key=len)

    manual_prefixes = {
        "param_lfo_manual::": MANUAL_TEMPLATE_SPECS,
        "param_filter_manual::": MANUAL_TEMPLATE_SPECS,
        "param_aux_env_manual::": MANUAL_TEMPLATE_SPECS,
        "param_pitch_env_manual::": MANUAL_TEMPLATE_SPECS,
        "param_sub_osc_manual::": MANUAL_TEMPLATE_SPECS,
    }
    value_prefixes = {
        "param_lfo_value::": VALUE_TEMPLATE_SPECS,
        "param_aux_env_value::": VALUE_TEMPLATE_SPECS,
        "param_filter_value::": VALUE_TEMPLATE_SPECS,
    }

    for full_key, value in DEFAULT_TOOL_TEMPLATE_GLOBAL_VALUES.items():
        for prefix, specs_map in manual_prefixes.items():
            if not full_key.startswith(prefix):
                continue
            full_path = full_key[len(prefix):]
            base_path = find_base_path(full_path, specs_map)
            if base_path is None:
                break
            relative_path = full_path[len(base_path):].lstrip("/")
            updated_specs = []
            changed = False
            for spec in specs_map.get(base_path, []):
                if spec[0] == relative_path:
                    updated_specs.append((spec[0], spec[1], str(value), spec[3], spec[4], spec[5]))
                    changed = True
                else:
                    updated_specs.append(spec)
            if changed:
                specs_map[base_path] = updated_specs
            break

        for prefix, specs_map in value_prefixes.items():
            if not full_key.startswith(prefix):
                continue
            full_path = full_key[len(prefix):]
            base_path = find_base_path(full_path, specs_map)
            if base_path is None:
                break
            relative_path = full_path[len(base_path):].lstrip("/")
            updated_specs = []
            changed = False
            for spec in specs_map.get(base_path, []):
                if spec[0] == relative_path:
                    updated_specs.append((spec[0], str(value)))
                    changed = True
                else:
                    updated_specs.append(spec)
            if changed:
                specs_map[base_path] = updated_specs
            break


apply_template_defaults_to_synthesized_specs()

DEFAULT_PRESET_SIMPLE_SECTIONS = [
    {
        "title": "Player / Playback",
        "fields": [
            {"kind": "entry", "label": "Loop mod sample start", "key": "player_loopmod_sample_start", "update": "player_loopmod_sample_start", "storage": "manual", "path": "Player/LoopModulators/SampleStart", "default": "0"},
            {"kind": "entry", "label": "Loop mod sample length", "key": "player_loopmod_sample_length", "update": "player_loopmod_sample_length", "storage": "manual", "path": "Player/LoopModulators/SampleLength", "default": "1"},
            {"kind": "bool", "label": "Loop mod loop on", "key": "player_loopmod_loop_on", "update": "player_loopmod_loop_on", "storage": "manual", "path": "Player/LoopModulators/LoopOn", "default": False},
            {"kind": "entry", "label": "Loop mod loop length", "key": "player_loopmod_loop_length", "update": "player_loopmod_loop_length", "storage": "manual", "path": "Player/LoopModulators/LoopLength", "default": "1"},
            {"kind": "entry", "label": "Loop mod loop fade", "key": "player_loopmod_loop_fade", "update": "player_loopmod_loop_fade", "storage": "manual", "path": "Player/LoopModulators/LoopFade", "default": "0"},
            {"kind": "bool", "label": "Reverse", "key": "player_reverse", "update": "player_reverse", "storage": "manual", "path": "Player/Reverse", "default": False},
            {"kind": "bool", "label": "Snap", "key": "player_snap", "update": "player_snap", "storage": "manual", "path": "Player/Snap", "default": False},
            {"kind": "entry", "label": "Sample selector", "key": "player_sample_selector", "update": "player_sample_selector", "storage": "manual", "path": "Player/SampleSelector", "default": "0"},
            {"kind": "choice", "label": "Interpolation mode", "key": "player_interpolation_mode", "update": "player_interpolation_mode", "storage": "value", "path": "Player/InterpolationMode", "default": "normal", "enum_id": "interpolation_mode"},
            {"kind": "bool", "label": "Sub osc on", "key": "player_sub_osc_on", "update": "player_sub_osc_on", "storage": "manual", "path": "Player/SubOsc/IsOn", "default": False},
        ],
    },
    {
        "title": "Global Pitch",
        "fields": [
            {"kind": "entry", "label": "Transpose key", "key": "pitch_transpose_key", "update": "pitch_transpose_key", "storage": "manual", "path": "Pitch/TransposeKey", "default": "0"},
            {"kind": "entry", "label": "Transpose fine", "key": "pitch_transpose_fine", "update": "pitch_transpose_fine", "storage": "manual", "path": "Pitch/TransposeFine", "default": "0"},
            {"kind": "entry", "label": "Pitch LFO amount", "key": "pitch_lfo_amount", "update": "pitch_lfo_amount", "storage": "manual", "path": "Pitch/PitchLfoAmount", "default": "0"},
            {"kind": "entry", "label": "Key zone shift", "key": "globals_key_zone_shift", "update": "globals_key_zone_shift", "storage": "manual", "path": "Globals/KeyZoneShift", "default": "0"},
            {"kind": "entry", "label": "Pitch bend range", "key": "globals_pitch_bend_range", "update": "globals_pitch_bend_range", "storage": "value", "path": "Globals/PitchBendRange", "default": "12"},
            {"kind": "entry", "label": "MPE pitch bend range", "key": "globals_mpe_pitch_bend_range", "update": "globals_mpe_pitch_bend_range", "storage": "value", "path": "Globals/MpePitchBendRange", "default": "48"},
        ],
    },
    {
        "title": "Amp / Pan",
        "fields": [
            {"kind": "entry", "label": "Volume", "key": "amp_volume", "update": "amp_volume", "storage": "manual", "path": "VolumeAndPan/Volume", "default": "-12"},
            {"kind": "entry", "label": "Volume vel scale", "key": "amp_volume_vel_scale", "update": "amp_volume_vel_scale", "storage": "manual", "path": "VolumeAndPan/VolumeVelScale", "default": "0.7"},
            {"kind": "entry", "label": "Volume key scale", "key": "amp_volume_key_scale", "update": "amp_volume_key_scale", "storage": "manual", "path": "VolumeAndPan/VolumeKeyScale", "default": "0"},
            {"kind": "entry", "label": "Volume LFO amount", "key": "amp_volume_lfo_amount", "update": "amp_volume_lfo_amount", "storage": "manual", "path": "VolumeAndPan/VolumeLfoAmount", "default": "0"},
            {"kind": "entry", "label": "Panorama", "key": "amp_panorama", "update": "amp_panorama", "storage": "manual", "path": "VolumeAndPan/Panorama", "default": "0"},
            {"kind": "entry", "label": "Panorama key scale", "key": "amp_panorama_key_scale", "update": "amp_panorama_key_scale", "storage": "manual", "path": "VolumeAndPan/PanoramaKeyScale", "default": "0"},
            {"kind": "entry", "label": "Panorama rnd", "key": "amp_panorama_rnd", "update": "amp_panorama_rnd", "storage": "manual", "path": "VolumeAndPan/PanoramaRnd", "default": "0"},
            {"kind": "entry", "label": "Panorama LFO amount", "key": "amp_panorama_lfo_amount", "update": "amp_panorama_lfo_amount", "storage": "manual", "path": "VolumeAndPan/PanoramaLfoAmount", "default": "0"},
        ],
    },
    {
        "title": "Envelope Extras",
        "fields": [
            {"kind": "entry", "label": "Attack level", "key": "env_attack_level", "update": "env_attack_level", "storage": "manual", "path": "VolumeAndPan/Envelope/AttackLevel", "default": "0.0003162277571"},
            {"kind": "entry", "label": "Decay level", "key": "env_decay_level", "update": "env_decay_level", "storage": "manual", "path": "VolumeAndPan/Envelope/DecayLevel", "default": "1"},
            {"kind": "entry", "label": "Release level", "key": "env_release_level", "update": "env_release_level", "storage": "manual", "path": "VolumeAndPan/Envelope/ReleaseLevel", "default": "0.0003162277571"},
            {"kind": "choice", "label": "Env loop mode", "key": "env_loop_mode", "update": "env_loop_mode", "storage": "manual", "path": "VolumeAndPan/Envelope/LoopMode", "default": "none", "enum_id": "envelope_loop_mode"},
            {"kind": "entry", "label": "Env loop time", "key": "env_loop_time", "update": "env_loop_time", "storage": "manual", "path": "VolumeAndPan/Envelope/LoopTime", "default": "100"},
            {"kind": "entry", "label": "Env repeat time", "key": "env_repeat_time", "update": "env_repeat_time", "storage": "manual", "path": "VolumeAndPan/Envelope/RepeatTime", "default": "3"},
            {"kind": "entry", "label": "Env time vel scale", "key": "env_time_vel_scale", "update": "env_time_vel_scale", "storage": "manual", "path": "VolumeAndPan/Envelope/TimeVelScale", "default": "0"},
        ],
    },
    {
        "title": "One-shot Envelope",
        "fields": [
            {"kind": "entry", "label": "Fade in time", "key": "oneshot_fade_in_time", "update": "oneshot_fade_in_time", "storage": "manual", "path": "VolumeAndPan/OneShotEnvelope/FadeInTime", "default": "0"},
            {"kind": "entry", "label": "Sustain mode", "key": "oneshot_sustain_mode", "update": "oneshot_sustain_mode", "storage": "manual", "path": "VolumeAndPan/OneShotEnvelope/SustainMode", "default": "0"},
            {"kind": "entry", "label": "Fade out time", "key": "oneshot_fade_out_time", "update": "oneshot_fade_out_time", "storage": "manual", "path": "VolumeAndPan/OneShotEnvelope/FadeOutTime", "default": "5"},
        ],
    },
    {
        "title": "Aux Envelope / Global Behavior",
        "fields": [
            {"kind": "bool", "label": "Aux env on", "key": "aux_env_on", "update": "aux_env_on", "storage": "manual", "path": "AuxEnv/IsOn", "default": False},
            {"kind": "entry", "label": "Spread amount", "key": "globals_spread_amount", "update": "globals_spread_amount", "storage": "manual", "path": "Globals/SpreadAmount", "default": "0"},
            {"kind": "choice", "label": "Portamento mode", "key": "globals_portamento_mode", "update": "globals_portamento_mode", "storage": "manual", "path": "Globals/PortamentoMode", "default": "off", "enum_id": "portamento_mode"},
            {"kind": "entry", "label": "Portamento time", "key": "globals_portamento_time", "update": "globals_portamento_time", "storage": "manual", "path": "Globals/PortamentoTime", "default": "50"},
            {"kind": "entry", "label": "Env scale time", "key": "globals_env_scale_time", "update": "globals_env_scale_time", "storage": "manual", "path": "Globals/EnvScale/EnvTime", "default": "0"},
            {"kind": "entry", "label": "Env time key scale", "key": "globals_env_time_key_scale", "update": "globals_env_time_key_scale", "storage": "manual", "path": "Globals/EnvScale/EnvTimeKeyScale", "default": "0"},
            {"kind": "bool", "label": "Env include attack", "key": "globals_env_include_attack", "update": "globals_env_include_attack", "storage": "manual", "path": "Globals/EnvScale/EnvTimeIncludeAttack", "default": True},
        ],
    },
    {
        "title": "Multisample Map / Identity",
        "fields": [
            {"kind": "bool", "label": "Load in RAM", "key": "mmap_load_in_ram", "update": "mmap_load_in_ram", "storage": "value", "path": "MultiSampleMap/LoadInRam", "default": False},
            {"kind": "entry", "label": "Layer crossfade", "key": "mmap_layer_crossfade", "update": "mmap_layer_crossfade", "storage": "value", "path": "MultiSampleMap/LayerCrossfade", "default": "0"},
            {"kind": "entry", "label": "Preset name", "key": "preset_user_name", "update": "preset_user_name", "storage": "tag", "path": "UserName", "default": ""},
            {"kind": "entry", "label": "Creator", "key": "preset_creator", "update": "preset_creator", "storage": "root_attr", "path": "Creator", "default": ""},
        ],
    },
]


def apply_template_defaults_to_default_preset_simple_sections():
    if not DEFAULT_TOOL_TEMPLATE_GLOBAL_VALUES:
        return
    for section in DEFAULT_PRESET_SIMPLE_SECTIONS:
        for field in section.get("fields", []):
            key = field.get("key")
            if key in DEFAULT_TOOL_TEMPLATE_GLOBAL_VALUES:
                field["default"] = DEFAULT_TOOL_TEMPLATE_GLOBAL_VALUES[key]


apply_template_defaults_to_default_preset_simple_sections()

#
# 4. Reverse-engineered ADV nodes should remain documented near the code
#    that reads/writes them. Do not hide important assumptions.

# =============================================================================
# Generic XML helpers
# =============================================================================

def child(parent, tag):
    if parent is None:
        return None
    return parent.find(tag)


def get_value(parent, tag, default=None):
    node = child(parent, tag)
    if node is None:
        return default
    return node.attrib.get("Value", default)


def set_value(parent, tag, value):
    node = child(parent, tag)
    if node is None:
        raise KeyError("Missing node: " + tag)
    node.set("Value", str(value))


def set_value_if_exists(parent, tag, value):
    node = child(parent, tag)
    if node is not None:
        node.set("Value", str(value))
        return True
    return False


def find_first_value_node_by_tag(root, tag):
    return root.find(".//" + tag)


def multisampler_container(root):
    if root is None:
        return None
    if getattr(root, "tag", None) == "Ableton":
        ms = root.find("MultiSampler")
        if ms is not None:
            return ms
    return root


def normalize_sampler_path(path):
    path = str(path or "").strip().lstrip("/")
    if path.startswith("MultiSampler/"):
        path = path[len("MultiSampler/"):]
    return path


def find_node_by_path(root, path):
    path = normalize_sampler_path(path)
    base = multisampler_container(root)
    if base is None or not path:
        return None
    node = base.find(path)
    if node is not None:
        return node
    return base.find(".//" + path)


def get_value_by_path(root, path, default=None):
    node = find_node_by_path(root, path)
    if node is None:
        return default
    return node.attrib.get("Value", default)


def set_value_by_path(root, path, value):
    node = find_node_by_path(root, path)
    if node is None:
        raise KeyError("Missing node at path: " + path)
    node.set("Value", str(value))


def find_manual_node_by_path(root, path):
    holder = find_node_by_path(root, path)
    if holder is None:
        return None
    return child(holder, "Manual")


def get_manual_value_by_path(root, path, default=None):
    node = find_manual_node_by_path(root, path)
    if node is None:
        return default
    return node.attrib.get("Value", default)


def set_manual_value_by_path(root, path, value):
    node = find_manual_node_by_path(root, path)
    if node is None:
        raise KeyError("Missing Manual node at path: " + path)
    node.set("Value", str(value))


def ensure_child(parent, tag):
    node = child(parent, tag)
    if node is None:
        node = ET.SubElement(parent, tag)
        if tag in ("SimplerLfo", "SimplerFilter", "SimplerShaper"):
            node.set("Id", "0")
    return node


def ensure_path(root, path):
    node = multisampler_container(root)
    for part in normalize_sampler_path(path).split("/"):
        if not part:
            continue
        node = ensure_child(node, part)
    return node


def matching_template_base(path, template_specs):
    path = str(path)
    matches = [base for base in template_specs if path == base or path.startswith(base + "/")]
    if not matches:
        return None
    return max(matches, key=len)


def build_manual_parameter_element(tag, kind, default, range_min=None, range_max=None, include_modulation=False):
    node = ET.Element(tag)
    ET.SubElement(node, "LomId").set("Value", "0")
    ET.SubElement(node, "Manual").set("Value", str(default))

    automation = ET.SubElement(node, "AutomationTarget")
    automation.set("Id", "0")
    ET.SubElement(automation, "LockEnvelope").set("Value", "0")

    if kind == "bool":
        thresholds = ET.SubElement(node, "MidiCCOnOffThresholds")
        ET.SubElement(thresholds, "Min").set("Value", "64")
        ET.SubElement(thresholds, "Max").set("Value", "127")
        return node

    if range_min is not None and range_max is not None:
        controller_range = ET.SubElement(node, "MidiControllerRange")
        ET.SubElement(controller_range, "Min").set("Value", str(range_min))
        ET.SubElement(controller_range, "Max").set("Value", str(range_max))

    if include_modulation:
        modulation = ET.SubElement(node, "ModulationTarget")
        modulation.set("Id", "0")
        ET.SubElement(modulation, "LockEnvelope").set("Value", "0")

    return node


def ensure_manual_group_template(root, base_path):
    specs = MANUAL_TEMPLATE_SPECS.get(base_path)
    if not specs:
        return

    container = ensure_path(root, base_path)
    for relative_path, kind, default, range_min, range_max, include_modulation in specs:
        parts = [part for part in str(relative_path).split("/") if part]
        if not parts:
            continue
        parent = container
        for part in parts[:-1]:
            parent = ensure_child(parent, part)
        leaf_tag = parts[-1]
        leaf = child(parent, leaf_tag)
        if leaf is None:
            parent.append(
                build_manual_parameter_element(
                    leaf_tag,
                    kind,
                    default,
                    range_min=range_min,
                    range_max=range_max,
                    include_modulation=include_modulation,
                )
            )


def ensure_value_group_template(root, base_path):
    specs = VALUE_TEMPLATE_SPECS.get(base_path)
    if not specs:
        return

    container = ensure_path(root, base_path)
    for relative_path, default in specs:
        parts = [part for part in str(relative_path).split("/") if part]
        if not parts:
            continue
        parent = container
        for part in parts[:-1]:
            parent = ensure_child(parent, part)
        leaf_tag = parts[-1]
        leaf = child(parent, leaf_tag)
        if leaf is None:
            leaf = ET.SubElement(parent, leaf_tag)
        if "Value" not in leaf.attrib:
            leaf.set("Value", str(default))


def ensure_manual_value_path(root, path):
    base_path = matching_template_base(path, MANUAL_TEMPLATE_SPECS)
    if base_path is not None:
        ensure_manual_group_template(root, base_path)


def ensure_direct_value_path(root, path):
    base_path = matching_template_base(path, VALUE_TEMPLATE_SPECS)
    if base_path is not None:
        ensure_value_group_template(root, base_path)


def generic_manual_group_has_existing_content(root, base_path):
    return bool(list_manual_parameter_paths(root, base_path))


def generic_value_group_has_existing_content(root, base_path):
    return bool(list_value_parameter_paths(root, base_path))


def merged_template_manual_paths(root, base_path):
    template_specs = MANUAL_TEMPLATE_SPECS.get(base_path, [])
    existing = {path: value for path, value in list_manual_parameter_paths(root, base_path)}
    merged = []
    seen = set()

    for relative_path, _kind, default, _range_min, _range_max, _include_modulation in template_specs:
        full_path = base_path + "/" + relative_path
        merged.append((full_path, existing.get(full_path, default)))
        seen.add(full_path)

    for path, value in sorted(existing.items()):
        if path not in seen:
            merged.append((path, value))

    return merged


def merged_template_value_paths(root, base_path):
    template_specs = VALUE_TEMPLATE_SPECS.get(base_path, [])
    existing = {path: value for path, value in list_value_parameter_paths(root, base_path)}
    merged = []
    seen = set()

    for relative_path, default in template_specs:
        full_path = base_path + "/" + relative_path
        merged.append((full_path, existing.get(full_path, default)))
        seen.add(full_path)

    for path, value in sorted(existing.items()):
        if path not in seen:
            merged.append((path, value))

    return merged


def float_to_text(value):
    if isinstance(value, str):
        return value
    try:
        return "{:g}".format(float(value))
    except Exception:
        return str(value)


def list_manual_parameter_paths(root, base_path):
    holder = find_node_by_path(root, base_path)
    if holder is None:
        return []

    params = []

    def walk(elem, parts):
        manual = child(elem, "Manual")
        if manual is not None:
            params.append(("/".join(parts), manual.attrib.get("Value", "")))
            return
        for sub in list(elem):
            if sub.tag in MANUAL_PARAM_SKIP_TAGS:
                continue
            walk(sub, parts + [sub.tag])

    walk(holder, [base_path])
    return params


def loop_mode_values_for_prefix(prefix):
    return RELEASE_MODE_VALUES if str(prefix).strip().lower() == "release" else SUSTAIN_MODE_VALUES


def normalize_mode_label(label):
    raw = str(label or "").strip()
    return LEGACY_MODE_LABEL_ALIASES.get(raw, LEGACY_MODE_LABEL_ALIASES.get(raw.lower(), raw.lower()))


def loop_mode_value_from_label(prefix, label):
    raw = str(label or "").strip()
    if raw.isdigit():
        return raw
    normalized = normalize_mode_label(raw)
    values = loop_mode_values_for_prefix(prefix)
    return values.get(normalized, raw)


def loop_mode_label_from_value(prefix, value):
    raw = str(value or "").strip()
    values = loop_mode_values_for_prefix(prefix)
    return next((label for label, mapped in values.items() if mapped == raw), raw)


def list_value_parameter_paths(root, base_path):
    holder = find_node_by_path(root, base_path)
    if holder is None:
        return []

    params = []

    def walk(elem, parts):
        value = elem.attrib.get("Value")
        if value is not None and parts:
            params.append(("/".join(parts), value))
        for sub in list(elem):
            walk(sub, parts + [sub.tag])

    walk(holder, [base_path])
    return params


def iter_default_preset_field_specs():
    for section in DEFAULT_PRESET_SIMPLE_SECTIONS:
        for spec in section["fields"]:
            yield spec


def db_to_linear(db):
    return math.pow(10.0, db / 20.0)


def linear_to_db(linear):
    try:
        linear = float(linear)
        if linear <= 0:
            return -999.0
        return 20.0 * math.log10(linear)
    except Exception:
        return 0.0


def clamp_int(v, lo, hi):
    return max(lo, min(hi, int(v)))


def clamp_loop_crossfade(sample_start, loop_start, loop_end, crossfade):
    sample_start = int(sample_start)
    loop_start = int(loop_start)
    loop_end = int(loop_end)
    crossfade = max(0, int(crossfade))
    loop_length = max(0, loop_end - loop_start)
    available_before_start = max(0, loop_start - sample_start)
    return max(0, min(crossfade, loop_length // 2, available_before_start))


def sanitize_filename_component(text, fallback="item"):
    text = str(text or "").strip()
    if not text:
        text = fallback
    text = re.sub(r"[<>:\"/\\\\|?*]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._ ")
    return text or fallback


def render_name_pattern(pattern, tokens):
    result = str(pattern or "")
    for key, value in tokens.items():
        result = result.replace("[{}]".format(key), str(value))
    return result


def read_audio_file_metadata(path):
    path = Path(path)
    if sf is not None:
        info = sf.info(str(path))
        return int(info.frames), int(info.samplerate)
    suffix = path.suffix.lower()
    if suffix == ".wav":
        with wave.open(str(path), "rb") as handle:
            return int(handle.getnframes()), int(handle.getframerate())
    raise RuntimeError("Audio metadata requires soundfile for this format: {}".format(path.suffix))


def path_looks_like_audio(path):
    return Path(path).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def enum_info(enum_id):
    return ENUM_MAPS.get(enum_id)


def enum_choices(enum_id):
    info = enum_info(enum_id)
    return info["choices"] if info else []


def enum_label_from_value(enum_id, raw_value):
    info = enum_info(enum_id)
    if not info:
        return str(raw_value)
    return info["value_to_label"].get(str(raw_value), str(raw_value))


def enum_value_from_label(enum_id, label):
    info = enum_info(enum_id)
    if not info:
        return str(label)
    return info["label_to_value"].get(str(label), str(label))


def enum_id_for_path(path):
    path = str(path)
    if path == "Player/InterpolationMode":
        return "interpolation_mode"
    if path == "Globals/PortamentoMode":
        return "portamento_mode"
    if path in (
        "VolumeAndPan/Envelope/LoopMode",
        "AuxEnv/Slot/Value/SimplerAuxEnvelope/LoopMode",
        "Pitch/Envelope/Slot/Value/SimplerPitchEnvelope/LoopMode",
        "Player/SubOsc/Slot/Value/SimplerSubOsc/Envelope/LoopMode",
    ):
        return "envelope_loop_mode"
    if path in ("Lfo/Slot/Value/SimplerLfo/Type", "AuxLfos.0/Slot/Value/SimplerAuxLfo/Type", "AuxLfos.1/Slot/Value/SimplerAuxLfo/Type"):
        return "lfo_type"
    if path in ("Lfo/Slot/Value/SimplerLfo/RateType", "AuxLfos.0/Slot/Value/SimplerAuxLfo/RateType", "AuxLfos.1/Slot/Value/SimplerAuxLfo/RateType"):
        return "lfo_rate_type"
    if path in ("Lfo/Slot/Value/SimplerLfo/StereoMode", "AuxLfos.0/Slot/Value/SimplerAuxLfo/StereoMode", "AuxLfos.1/Slot/Value/SimplerAuxLfo/StereoMode"):
        return "lfo_stereo_mode"
    if path == "Filter/Slot/Value/SimplerFilter/LegacyType":
        return "__hidden__"
    if path == "Filter/Slot/Value/SimplerFilter/Type":
        return "filter_type"
    if path == "Filter/Slot/Value/SimplerFilter/Slope":
        return "filter_slope"
    if path in ("Filter/Slot/Value/SimplerFilter/CircuitLpHp", "Filter/Slot/Value/SimplerFilter/CircuitBpNoMo"):
        return "filter_circuit"
    if path == "Shaper/Slot/Value/SimplerShaper/Type":
        return "shaper_type"
    if path == "Player/SubOsc/Slot/Value/SimplerSubOsc/Mode":
        return "sub_osc_mode"
    if path == "Player/SubOsc/Slot/Value/SimplerSubOsc/Type":
        return "sub_osc_type"
    if path.endswith("/Connection") and (
        path.startswith("KeyDst/")
        or path.startswith("VelDst/")
        or path.startswith("RelVelDst/")
        or path.startswith("MidiCtrl.")
        or "/ModDst/" in path
    ):
        return "routing_connection"
    return None


# =============================================================================
# ADV file codec
# =============================================================================

class AdvCodec:
    @staticmethod
    def read_xml_bytes(path):
        with gzip.open(path, "rb") as f:
            return f.read()

    @staticmethod
    def parse_xml(xml_bytes):
        return ET.ElementTree(ET.fromstring(xml_bytes))

    @staticmethod
    def load(path):
        xml_bytes = AdvCodec.read_xml_bytes(path)
        return AdvCodec.parse_xml(xml_bytes)

    @staticmethod
    def write(tree, path):
        body = ET.tostring(tree.getroot(), encoding="utf-8")
        xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + body
        with open(path, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=raw, mtime=0) as gz:
                gz.write(xml_bytes)

    @staticmethod
    def export_decompressed_xml(tree, path):
        body = ET.tostring(tree.getroot(), encoding="utf-8")
        xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + body
        Path(path).write_bytes(xml_bytes)

    @staticmethod
    def load_default_scaffold():
        if not DEFAULT_ADV_SCAFFOLD_PATH.exists():
            raise FileNotFoundError("Default ADV scaffold not found: {}".format(DEFAULT_ADV_SCAFFOLD_PATH))
        return AdvCodec.load(DEFAULT_ADV_SCAFFOLD_PATH)


# =============================================================================
# Sampler .adv model helpers
# =============================================================================

class SamplerAdvModel:
    """
    Thin wrapper around the Ableton XML tree.

    Important:
    - We keep the original XML tree.
    - We primarily read/write specific known nodes.
    - Some missing parameter groups are synthesized when the tool needs them.
    """

    def __init__(self, tree, source_path=None):
        self.tree = tree
        self.root = tree.getroot()
        self.source_path = Path(source_path) if source_path is not None else None
        self.multisampler = self.find_multisampler()
        if self.multisampler is None:
            raise RuntimeError("No <MultiSampler> found. Is this really a Sampler .adv?")
        self.multisample_map = self.find_multisample_map()
        self.zones = self.find_sample_parts()

    def creator(self):
        return self.root.attrib.get("Creator", "")

    def find_multisampler(self):
        if self.root.tag == "MultiSampler":
            return self.root
        return self.root.find(".//MultiSampler")

    def find_multisample_map(self):
        return self.multisampler.find(".//MultiSampleMap")

    def find_sample_parts(self):
        mmap = self.multisample_map
        if mmap is None:
            return []
        sample_parts = child(mmap, "SampleParts")
        if sample_parts is None:
            return []
        return list(sample_parts.findall("MultiSamplePart"))

    def refresh(self):
        self.multisampler = self.find_multisampler()
        self.multisample_map = self.find_multisample_map()
        self.zones = self.find_sample_parts()

    # -------------------------------------------------------------------------
    # Zone-level extraction
    # -------------------------------------------------------------------------

    def zone_count(self):
        return len(self.zones)

    def get_zone(self, index):
        if index < 0 or index >= len(self.zones):
            raise IndexError("Zone index out of range: " + str(index))
        return self.zones[index]

    def sample_file_ref(self, zone):
        sample_ref = child(zone, "SampleRef")
        if sample_ref is None:
            return None
        return sample_ref.find(".//FileRef")

    def extract_sample_path(self, zone):
        file_ref = self.sample_file_ref(zone)
        if file_ref is None:
            return "", ""
        return get_value(file_ref, "Path", ""), get_value(file_ref, "RelativePath", "")

    def set_zone_sample_reference(self, zone, absolute_path=None, relative_path=None, relative_path_type=None):
        file_ref = self.sample_file_ref(zone)
        if file_ref is None:
            raise KeyError("Missing SampleRef/FileRef node.")

        if absolute_path is not None:
            set_value(file_ref, "Path", str(absolute_path))
        if relative_path is not None:
            set_value(file_ref, "RelativePath", str(relative_path))
        if relative_path_type is not None:
            set_value(file_ref, "RelativePathType", str(relative_path_type))

    def resolve_sample_file(self, zone):
        sample_path, relative_path = self.extract_sample_path(zone)
        candidates = []

        if sample_path:
            candidates.append(Path(sample_path))

        if relative_path and self.source_path is not None:
            rel = Path(relative_path)
            for base in [self.source_path.parent] + list(self.source_path.parent.parents[:4]):
                candidate = base / rel
                if candidate not in candidates:
                    candidates.append(candidate)

        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate.resolve()
            except Exception:
                pass

        if candidates:
            return candidates[0]

        raise FileNotFoundError("Zone has no usable sample path.")

    def read_range(self, zone, tag):
        r = child(zone, tag)
        if r is None:
            return {"min": "", "max": "", "xfade_min": "", "xfade_max": ""}
        return {
            "min": get_value(r, "Min", ""),
            "max": get_value(r, "Max", ""),
            "xfade_min": get_value(r, "CrossfadeMin", ""),
            "xfade_max": get_value(r, "CrossfadeMax", ""),
        }

    def write_range(self, zone, tag, vals):
        r = child(zone, tag)
        if r is None:
            raise KeyError("Missing range node: " + tag)
        set_value(r, "Min", vals["min"])
        set_value(r, "Max", vals["max"])
        set_value(r, "CrossfadeMin", vals["xfade_min"])
        set_value(r, "CrossfadeMax", vals["xfade_max"])

    def read_loop(self, zone, tag):
        l = child(zone, tag)
        if l is None:
            return {"start": "", "end": "", "mode": "", "crossfade": "", "detune": ""}
        return {
            "start": get_value(l, "Start", ""),
            "end": get_value(l, "End", ""),
            "mode": get_value(l, "Mode", ""),
            "crossfade": get_value(l, "Crossfade", ""),
            "detune": get_value(l, "Detune", ""),
        }

    def write_loop(self, zone, tag, vals):
        l = child(zone, tag)
        if l is None:
            raise KeyError("Missing loop node: " + tag)
        set_value(l, "Start", vals["start"])
        set_value(l, "End", vals["end"])
        set_value(l, "Mode", vals["mode"])
        set_value(l, "Crossfade", vals["crossfade"])
        set_value_if_exists(l, "Detune", vals["detune"])

    def read_zone_summary(self, index):
        zone = self.get_zone(index)
        sample_path, relative_path = self.extract_sample_path(zone)
        raw_detune = parse_number_from_text(get_value(zone, "Detune", "0"), 0.0)
        detune_cents = clamp_int(round(raw_detune), -50, 50)

        return {
            "index": index,
            "id": zone.attrib.get("Id", ""),
            "name": get_value(zone, "Name", ""),
            "sample_path": sample_path,
            "relative_path": relative_path,
            "root_key": get_value(zone, "RootKey", ""),
            "detune": str(detune_cents),
            "tune_scale": get_value(zone, "TuneScale", ""),
            "volume_linear": get_value(zone, "Volume", ""),
            "volume_db": linear_to_db(get_value(zone, "Volume", "1")),
            "sample_start": get_value(zone, "SampleStart", ""),
            "sample_end": get_value(zone, "SampleEnd", ""),
            "key_range": self.read_range(zone, "KeyRange"),
            "velocity_range": self.read_range(zone, "VelocityRange"),
            "selector_range": self.read_range(zone, "SelectorRange"),
            "sustain_loop": self.read_loop(zone, "SustainLoop"),
            "release_loop": self.read_loop(zone, "ReleaseLoop"),
        }

    def dump_summary(self):
        return {
            "creator": self.creator(),
            "zone_count": self.zone_count(),
            "zones": [self.read_zone_summary(i) for i in range(self.zone_count())],
            "global": self.read_global_summary(),
        }

    # -------------------------------------------------------------------------
    # Validation / consistency
    # -------------------------------------------------------------------------

    def validate_range(self, vals, lo, hi):
        mn = clamp_int(vals["min"], lo, hi)
        mx = clamp_int(vals["max"], lo, hi)
        xmn = clamp_int(vals["xfade_min"], lo, hi)
        xmx = clamp_int(vals["xfade_max"], lo, hi)

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

    def clamp_loops_to_sample_bounds(self, zone):
        sample_start = int(float(get_value(zone, "SampleStart", "0")))
        sample_end = int(float(get_value(zone, "SampleEnd", "0")))

        for loop_tag in ("SustainLoop", "ReleaseLoop"):
            loop = child(zone, loop_tag)
            if loop is None:
                continue

            start_node = child(loop, "Start")
            end_node = child(loop, "End")

            if start_node is not None:
                v = int(float(start_node.attrib.get("Value", "0")))
                v = max(sample_start, min(v, sample_end - 1))
                start_node.set("Value", str(v))

            if end_node is not None:
                v = int(float(end_node.attrib.get("Value", "0")))
                v = max(sample_start + 1, min(v, sample_end))
                end_node.set("Value", str(v))

            if start_node is not None and end_node is not None:
                s = int(float(start_node.attrib.get("Value", "0")))
                e = int(float(end_node.attrib.get("Value", "0")))
                if s >= e:
                    start_node.set("Value", str(max(sample_start, e - 1)))

    # -------------------------------------------------------------------------
    # Zone-level writing
    # -------------------------------------------------------------------------

    def apply_zone_values(self, index, zone_values, range_values, loop_values):
        zone = self.get_zone(index)

        set_value(zone, "Name", zone_values["name"])

        vol_db = float(zone_values["volume_db"])
        set_value(zone, "Volume", "{:.8f}".format(db_to_linear(vol_db)))

        set_value(zone, "RootKey", int(zone_values["root_key"]))
        detune_cents = clamp_int(parse_number_from_text(zone_values["detune"], 0), -50, 50)
        set_value(zone, "Detune", detune_cents)
        set_value(zone, "TuneScale", float_to_text(parse_number_from_text(zone_values.get("tune_scale", "100"), 100.0)))

        ss = int(zone_values["sample_start"])
        se = int(zone_values["sample_end"])
        if ss >= se:
            raise ValueError("SampleStart must be < SampleEnd.")
        set_value(zone, "SampleStart", ss)
        set_value(zone, "SampleEnd", se)

        key_vals = self.validate_range(
            {sub: range_values["key_" + sub] for sub in ("min", "max", "xfade_min", "xfade_max")},
            0,
            127,
        )
        vel_vals = self.validate_range(
            {sub: range_values["vel_" + sub] for sub in ("min", "max", "xfade_min", "xfade_max")},
            1,
            127,
        )
        sel_vals = self.validate_range(
            {sub: range_values["sel_" + sub] for sub in ("min", "max", "xfade_min", "xfade_max")},
            0,
            127,
        )

        self.write_range(zone, "KeyRange", key_vals)
        self.write_range(zone, "VelocityRange", vel_vals)
        self.write_range(zone, "SelectorRange", sel_vals)

        sustain_vals = {sub: loop_values["sustain_" + sub] for sub in ("start", "end", "mode", "crossfade", "detune")}
        release_vals = {sub: loop_values["release_" + sub] for sub in ("start", "end", "mode", "crossfade", "detune")}

        for prefix, vals in (("sustain", sustain_vals), ("release", release_vals)):
            if int(vals["start"]) >= int(vals["end"]):
                raise ValueError("Loop start must be < loop end.")
            vals["mode"] = loop_mode_value_from_label(prefix, vals["mode"])
            int(vals["mode"])
            vals["crossfade"] = str(clamp_loop_crossfade(ss, int(vals["start"]), int(vals["end"]), int(vals["crossfade"])))
            vals["detune"] = str(clamp_int(parse_number_from_text(vals["detune"], 0), -1200, 1200))

        self.write_loop(zone, "SustainLoop", sustain_vals)
        self.write_loop(zone, "ReleaseLoop", release_vals)
        self.clamp_loops_to_sample_bounds(zone)

    # -------------------------------------------------------------------------
    # Zone duplication / replacement helpers
    # -------------------------------------------------------------------------

    def sample_parts_container(self):
        if self.multisample_map is None:
            return None
        return child(self.multisample_map, "SampleParts")

    def next_zone_id(self):
        max_id = -1
        for z in self.zones:
            raw = z.attrib.get("Id", "")
            try:
                max_id = max(max_id, int(raw))
            except Exception:
                pass
        return max_id + 1

    def set_zone_id(self, zone, new_id):
        if "Id" in zone.attrib:
            zone.attrib["Id"] = str(new_id)

    def replace_zone_with_zones(self, index, new_zones):
        container = self.sample_parts_container()
        if container is None:
            raise RuntimeError("No <SampleParts> container found.")

        old_zones = list(container.findall("MultiSamplePart"))
        if index < 0 or index >= len(old_zones):
            raise IndexError("Zone index out of range: " + str(index))

        # ElementTree has no direct insert-before replace list, so rebuild order.
        for z in old_zones:
            container.remove(z)

        rebuilt = []
        for i, z in enumerate(old_zones):
            if i == index:
                rebuilt.extend(new_zones)
            else:
                rebuilt.append(z)

        for z in rebuilt:
            container.append(z)

        self.refresh()

    def delete_zone(self, index):
        container = self.sample_parts_container()
        if container is None:
            raise RuntimeError("No <SampleParts> container found.")

        old_zones = list(container.findall("MultiSamplePart"))
        if index < 0 or index >= len(old_zones):
            raise IndexError("Zone index out of range: " + str(index))

        container.remove(old_zones[index])
        self.refresh()

    def append_zone(self, zone):
        container = self.sample_parts_container()
        if container is None:
            raise RuntimeError("No <SampleParts> container found.")
        container.append(zone)
        self.refresh()

    def reorder_zones(self, ordered_indices):
        container = self.sample_parts_container()
        if container is None:
            raise RuntimeError("No <SampleParts> container found.")

        old_zones = list(container.findall("MultiSamplePart"))
        if len(ordered_indices) != len(old_zones):
            raise ValueError("Zone reorder length mismatch.")
        if sorted(int(v) for v in ordered_indices) != list(range(len(old_zones))):
            raise ValueError("Zone reorder indices must be a permutation of existing zones.")

        for zone in old_zones:
            container.remove(zone)
        for index in ordered_indices:
            container.append(old_zones[int(index)])
        self.refresh()

    def proportional_sample_pos(self, value, old_start, old_end, new_start, new_end):
        old_len = max(1, old_end - old_start)
        new_len = max(1, new_end - new_start)
        ratio = (int(value) - old_start) / float(old_len)
        ratio = max(0.0, min(1.0, ratio))
        return int(round(new_start + ratio * new_len))

    def set_zone_bounds_with_proportional_loops(self, zone, old_start, old_end, new_start, new_end):
        set_value(zone, "SampleStart", int(new_start))
        set_value(zone, "SampleEnd", int(new_end))

        for loop_tag in ("SustainLoop", "ReleaseLoop"):
            loop = child(zone, loop_tag)
            if loop is None:
                continue

            start_val = get_value(loop, "Start", None)
            end_val = get_value(loop, "End", None)

            if start_val is not None:
                new_loop_start = self.proportional_sample_pos(start_val, old_start, old_end, new_start, new_end)
                set_value(loop, "Start", new_loop_start)

            if end_val is not None:
                new_loop_end = self.proportional_sample_pos(end_val, old_start, old_end, new_start, new_end)
                set_value(loop, "End", new_loop_end)

        self.clamp_loops_to_sample_bounds(zone)

    # -------------------------------------------------------------------------
    # Global extraction / writing
    # -------------------------------------------------------------------------

    def shared_zone_value(self, tag):
        values = {get_value(self.get_zone(i), tag, "") for i in range(self.zone_count())}
        return next(iter(values)) if len(values) == 1 else ""

    def read_global_summary(self):
        voices_node = find_first_value_node_by_tag(self.root, "Voices")
        if voices_node is None:
            voices_node = find_node_by_path(self.root, "Globals/NumVoices")
        mmap = self.multisample_map
        envelope_path = "VolumeAndPan/Envelope"

        sustain_modes = {self.read_loop(self.get_zone(i), "SustainLoop").get("mode", "") for i in range(self.zone_count())}
        release_modes = {self.read_loop(self.get_zone(i), "ReleaseLoop").get("mode", "") for i in range(self.zone_count())}

        sustain_mode = next(iter(sustain_modes)) if len(sustain_modes) == 1 else ""
        release_mode = next(iter(release_modes)) if len(release_modes) == 1 else ""

        return {
            "voices": voices_node.attrib.get("Value", "") if voices_node is not None else "",
            "default_tune_scale": self.shared_zone_value("TuneScale"),
            "round_robin": get_value(mmap, "RoundRobin", "") if mmap is not None else "",
            "round_robin_mode": get_value(mmap, "RoundRobinMode", "") if mmap is not None else "",
            "round_robin_reset_period": get_value(mmap, "RoundRobinResetPeriod", "") if mmap is not None else "",
            "round_robin_random_seed": get_value(mmap, "RoundRobinRandomSeed", "") if mmap is not None else "",
            "default_loop_mode": sustain_mode,
            "default_release_loop_mode": release_mode,
            "env_attack_ms": get_manual_value_by_path(self.root, envelope_path + "/AttackTime", ""),
            "env_decay_ms": get_manual_value_by_path(self.root, envelope_path + "/DecayTime", ""),
            "env_sustain": get_manual_value_by_path(self.root, envelope_path + "/SustainLevel", ""),
            "env_release_ms": get_manual_value_by_path(self.root, envelope_path + "/ReleaseTime", ""),
            "env_attack_shape": float_to_text(parse_number_from_text(get_manual_value_by_path(self.root, envelope_path + "/AttackSlope", "0"), 0.0) * 100.0),
            "env_decay_shape": float_to_text(parse_number_from_text(get_manual_value_by_path(self.root, envelope_path + "/DecaySlope", "0"), 0.0) * 100.0),
            "env_release_shape": float_to_text(parse_number_from_text(get_manual_value_by_path(self.root, envelope_path + "/ReleaseSlope", "0"), 0.0) * 100.0),
        }

    def read_default_preset_field(self, spec):
        storage = spec.get("storage", "manual")
        path = spec.get("path", "")
        if storage == "manual":
            return get_manual_value_by_path(self.root, path, spec.get("default", ""))
        if storage == "value":
            return get_value_by_path(self.root, path, spec.get("default", ""))
        if storage == "tag":
            node = find_first_value_node_by_tag(self.root, path)
            if node is None:
                return spec.get("default", "")
            return node.attrib.get("Value", spec.get("default", ""))
        if storage == "root_attr":
            return self.root.attrib.get(path, spec.get("default", ""))
        raise ValueError("Unknown default preset field storage: {}".format(storage))

    def write_default_preset_field(self, spec, value):
        storage = spec.get("storage", "manual")
        path = spec.get("path", "")
        kind = spec.get("kind", "entry")
        enum_id = spec.get("enum_id")
        if kind == "bool":
            if isinstance(value, bool):
                value = "true" if value else "false"
            else:
                value = "true" if str(value).strip().lower() == "true" else "false"
        else:
            value = str(value).strip()
            if enum_id:
                value = enum_value_from_label(enum_id, value)

        if storage == "manual":
            set_manual_value_by_path(self.root, path, value)
            return
        if storage == "value":
            set_value_by_path(self.root, path, value)
            return
        if storage == "tag":
            node = find_first_value_node_by_tag(self.root, path)
            if node is None:
                raise KeyError("Missing tag node: " + path)
            node.set("Value", value)
            return
        if storage == "root_attr":
            self.root.set(path, value)
            return
        raise ValueError("Unknown default preset field storage: {}".format(storage))

    def apply_global_values(self, global_values, global_update, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        if global_update.get("default_tune_scale", False):
            tune_scale = float_to_text(parse_number_from_text(global_values.get("param_default_tune_scale", "100"), 100.0))
            updated = 0
            for i in range(self.zone_count()):
                zone = self.get_zone(i)
                if get_value(zone, "TuneScale", "") != tune_scale:
                    set_value(zone, "TuneScale", tune_scale)
                    updated += 1
            log("Updated TuneScale on {} zone(s): {}\n".format(updated, tune_scale))

        if global_update.get("voices", False):
            voices = global_values["voices"].strip()
            int(voices)
            voices_node = find_first_value_node_by_tag(self.root, "Voices")
            globals_num_voices_node = find_node_by_path(self.root, "Globals/NumVoices")
            updated_nodes = 0
            if voices_node is not None:
                voices_node.set("Value", voices)
                updated_nodes += 1
            if globals_num_voices_node is not None:
                globals_num_voices_node.set("Value", voices)
                updated_nodes += 1
            elif voices_node is None:
                globals_holder = find_node_by_path(self.root, "Globals")
                if globals_holder is not None:
                    ET.SubElement(globals_holder, "NumVoices").set("Value", voices)
                    updated_nodes += 1
            if updated_nodes:
                log("Updated voice count on {} node(s): {}\n".format(updated_nodes, voices))
            else:
                log("No <Voices> node found; skipped.\n")

        if self.multisample_map is not None:
            if global_update.get("rr", False):
                rr_raw = global_values["rr"]
                if isinstance(rr_raw, bool):
                    rr = "true" if rr_raw else "false"
                else:
                    rr = str(rr_raw).strip().lower()
                if rr not in ("true", "false"):
                    raise ValueError("RoundRobin must be true or false.")
                set_value_if_exists(self.multisample_map, "RoundRobin", rr)
                log("Updated RoundRobin: {}\n".format(rr))

            if global_update.get("rr_mode", False):
                raw_mode = str(global_values["rr_mode"]).strip()
                val = ROUND_ROBIN_MODE_LABEL_TO_VALUE.get(raw_mode, raw_mode)
                int(val)
                set_value_if_exists(self.multisample_map, "RoundRobinMode", val)
                log("Updated RoundRobinMode: {}\n".format(val))

            if global_update.get("rr_reset", False):
                raw_reset = str(global_values["rr_reset"]).strip()
                val = ROUND_ROBIN_RESET_LABEL_TO_VALUE.get(raw_reset, raw_reset)
                int(val)
                set_value_if_exists(self.multisample_map, "RoundRobinResetPeriod", val)
                log("Updated RoundRobinResetPeriod: {}\n".format(val))

            if global_update.get("rr_seed", False):
                val = str(global_values["rr_seed"]).strip()
                int(val)
                set_value_if_exists(self.multisample_map, "RoundRobinRandomSeed", val)
                log("Updated RoundRobinRandomSeed: {}\n".format(val))

        if global_update.get("default_loop_mode", False):
            raw_mode = str(global_values.get("param_default_loop_mode", "on")).strip()
            val = loop_mode_value_from_label("sustain", raw_mode)
            int(val)
            updated = 0
            for i in range(self.zone_count()):
                zone = self.get_zone(i)
                loop_vals = self.read_loop(zone, "SustainLoop")
                if loop_vals.get("mode", "") != val:
                    loop_vals["mode"] = val
                    self.write_loop(zone, "SustainLoop", loop_vals)
                    updated += 1
            log("Updated SustainLoop mode on {} zone(s): {}\n".format(updated, val))

        if global_update.get("default_release_loop_mode", False):
            raw_mode = str(global_values.get("param_default_release_loop_mode", "on")).strip()
            val = loop_mode_value_from_label("release", raw_mode)
            int(val)
            updated = 0
            for i in range(self.zone_count()):
                zone = self.get_zone(i)
                loop_vals = self.read_loop(zone, "ReleaseLoop")
                if loop_vals.get("mode", "") != val:
                    loop_vals["mode"] = val
                    self.write_loop(zone, "ReleaseLoop", loop_vals)
                    updated += 1
            log("Updated ReleaseLoop mode on {} zone(s): {}\n".format(updated, val))

        if global_update.get("planned_envelope_time", False):
            envelope_updates = {
                "VolumeAndPan/Envelope/AttackTime": parse_number_from_text(global_values.get("param_env_attack_ms", "0.2"), 0.2),
                "VolumeAndPan/Envelope/DecayTime": parse_number_from_text(global_values.get("param_env_decay_ms", "1000"), 1000.0),
                "VolumeAndPan/Envelope/SustainLevel": parse_number_from_text(global_values.get("param_env_sustain", "1"), 1.0),
                "VolumeAndPan/Envelope/ReleaseTime": parse_number_from_text(global_values.get("param_env_release_ms", "20"), 20.0),
            }
            for path, value in envelope_updates.items():
                set_manual_value_by_path(self.root, path, float_to_text(value))
            log("Updated amplitude envelope times/level.\n")

        if global_update.get("planned_envelope_shape", False):
            slope_updates = {
                "VolumeAndPan/Envelope/AttackSlope": max(-1.0, min(1.0, parse_number_from_text(global_values.get("param_env_attack_shape", "0"), 0.0) / 100.0)),
                "VolumeAndPan/Envelope/DecaySlope": max(-1.0, min(1.0, parse_number_from_text(global_values.get("param_env_decay_shape", "0"), 0.0) / 100.0)),
                "VolumeAndPan/Envelope/ReleaseSlope": max(-1.0, min(1.0, parse_number_from_text(global_values.get("param_env_release_shape", "0"), 0.0) / 100.0)),
            }
            for path, value in slope_updates.items():
                set_manual_value_by_path(self.root, path, float_to_text(value))
            log("Updated amplitude envelope slopes.\n")

        if global_update.get("generic_lfo", False):
            updated = 0
            for key, value in global_values.items():
                if not str(key).startswith("param_lfo_manual::"):
                    if not str(key).startswith("param_lfo_value::"):
                        continue
                    path = str(key).split("::", 1)[1]
                    base_path = matching_template_base(path, VALUE_TEMPLATE_SPECS)
                    if base_path in OPTIONAL_GENERIC_VALUE_BASES and not generic_value_group_has_existing_content(self.root, base_path):
                        continue
                    enum_id = enum_id_for_path(path)
                    if enum_id and enum_id != "__hidden__":
                        value = enum_value_from_label(enum_id, value)
                    ensure_direct_value_path(self.root, path)
                    set_value_by_path(self.root, path, value)
                    updated += 1
                    continue
                path = str(key).split("::", 1)[1]
                base_path = matching_template_base(path, MANUAL_TEMPLATE_SPECS)
                if base_path in OPTIONAL_GENERIC_MANUAL_BASES and not generic_manual_group_has_existing_content(self.root, base_path):
                    continue
                enum_id = enum_id_for_path(path)
                if enum_id and enum_id != "__hidden__":
                    value = enum_value_from_label(enum_id, value)
                ensure_manual_value_path(self.root, path)
                set_manual_value_by_path(self.root, path, value)
                updated += 1
            log("Updated {} generic modulation parameter(s).\n".format(updated))

        if global_update.get("generic_filter", False):
            updated = 0
            for key, value in global_values.items():
                if not str(key).startswith("param_filter_manual::"):
                    if not str(key).startswith("param_filter_value::"):
                        continue
                    path = str(key).split("::", 1)[1]
                    enum_id = enum_id_for_path(path)
                    if enum_id and enum_id != "__hidden__":
                        value = enum_value_from_label(enum_id, value)
                    ensure_direct_value_path(self.root, path)
                    set_value_by_path(self.root, path, value)
                    updated += 1
                    continue
                path = str(key).split("::", 1)[1]
                enum_id = enum_id_for_path(path)
                if enum_id and enum_id != "__hidden__":
                    value = enum_value_from_label(enum_id, value)
                ensure_manual_value_path(self.root, path)
                set_manual_value_by_path(self.root, path, value)
                updated += 1
            log("Updated {} generic filter parameter(s).\n".format(updated))

        if global_update.get("generic_aux_env", False):
            updated = 0
            for key, value in global_values.items():
                if not str(key).startswith("param_aux_env_manual::"):
                    if not str(key).startswith("param_aux_env_value::"):
                        continue
                    path = str(key).split("::", 1)[1]
                    enum_id = enum_id_for_path(path)
                    if enum_id and enum_id != "__hidden__":
                        value = enum_value_from_label(enum_id, value)
                    ensure_direct_value_path(self.root, path)
                    set_value_by_path(self.root, path, value)
                    updated += 1
                    continue
                path = str(key).split("::", 1)[1]
                enum_id = enum_id_for_path(path)
                if enum_id and enum_id != "__hidden__":
                    value = enum_value_from_label(enum_id, value)
                ensure_manual_value_path(self.root, path)
                set_manual_value_by_path(self.root, path, value)
                updated += 1
            log("Updated {} generic aux envelope parameter(s).\n".format(updated))

        if global_update.get("generic_pitch_env", False):
            updated = 0
            for key, value in global_values.items():
                if not str(key).startswith("param_pitch_env_manual::"):
                    continue
                path = str(key).split("::", 1)[1]
                enum_id = enum_id_for_path(path)
                if enum_id and enum_id != "__hidden__":
                    value = enum_value_from_label(enum_id, value)
                ensure_manual_value_path(self.root, path)
                set_manual_value_by_path(self.root, path, value)
                updated += 1
            log("Updated {} generic pitch envelope parameter(s).\n".format(updated))

        if global_update.get("generic_sub_osc", False):
            updated = 0
            for key, value in global_values.items():
                if not str(key).startswith("param_sub_osc_manual::"):
                    continue
                path = str(key).split("::", 1)[1]
                enum_id = enum_id_for_path(path)
                if enum_id and enum_id != "__hidden__":
                    value = enum_value_from_label(enum_id, value)
                ensure_manual_value_path(self.root, path)
                set_manual_value_by_path(self.root, path, value)
                updated += 1
            log("Updated {} generic sub oscillator parameter(s).\n".format(updated))

        simple_updates = 0
        for spec in iter_default_preset_field_specs():
            if not global_update.get(spec["update"], False):
                continue
            self.write_default_preset_field(spec, global_values.get(spec["key"], spec.get("default", "")))
            simple_updates += 1
        if simple_updates:
            log("Updated {} default preset field(s).\n".format(simple_updates))




# =============================================================================
# Processing utility functions
# =============================================================================

def parse_number_from_text(text, default):
    if text is None:
        return default
    m = re.search(r"[-+]?\d*\.?\d+", str(text))
    if not m:
        return default
    try:
        return float(m.group(0))
    except Exception:
        return default


def duration_text_to_beats(text):
    text = str(text).strip().lower()

    if "bar" in text:
        value = parse_number_from_text(text, 1.0)
        return value * 4.0

    if "beat" in text:
        return parse_number_from_text(text, 1.0)


def midi_key_to_note_label(midi_key):
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    midi_key = clamp_int(midi_key, 0, 127)
    octave = (midi_key // 12) - 2
    return "{} {}".format(note_names[midi_key % 12], octave)


def midi_var_len(value):
    value = max(0, int(value))
    buffer = value & 0x7F
    result = bytearray([buffer])
    value >>= 7
    while value:
        buffer = 0x80 | (value & 0x7F)
        result.insert(0, buffer)
        value >>= 7
    return bytes(result)


def midi_seconds_to_ticks(seconds, tempo_bpm=100.0, ticks_per_quarter=480):
    seconds = max(0.0, float(seconds))
    quarter_seconds = 60.0 / max(1e-9, float(tempo_bpm))
    return max(0, int(round((seconds / quarter_seconds) * int(ticks_per_quarter))))


def write_midi_file(path, events, tempo_bpm=100.0, ticks_per_quarter=480, track_name="MIDI_test"):
    path = Path(path)
    ticks_per_quarter = int(ticks_per_quarter)
    microseconds_per_quarter = int(round(60000000.0 / max(1e-9, float(tempo_bpm))))

    track = bytearray()
    track.extend(midi_var_len(0))
    track.extend(b"\xff\x03")
    encoded_name = str(track_name).encode("utf-8", errors="replace")
    track.extend(midi_var_len(len(encoded_name)))
    track.extend(encoded_name)

    track.extend(midi_var_len(0))
    track.extend(b"\xff\x51\x03")
    track.extend(microseconds_per_quarter.to_bytes(3, "big"))

    for delta_ticks, payload in events:
        track.extend(midi_var_len(delta_ticks))
        track.extend(bytes(payload))

    track.extend(midi_var_len(0))
    track.extend(b"\xff\x2f\x00")

    header = bytearray()
    header.extend(b"MThd")
    header.extend((6).to_bytes(4, "big"))
    header.extend((0).to_bytes(2, "big"))
    header.extend((1).to_bytes(2, "big"))
    header.extend(int(ticks_per_quarter).to_bytes(2, "big"))

    chunk = bytearray()
    chunk.extend(b"MTrk")
    chunk.extend(len(track).to_bytes(4, "big"))
    chunk.extend(track)
    path.write_bytes(bytes(header + chunk))


def zone_range_midpoint(range_vals, default_value):
    try:
        mn = clamp_int(range_vals.get("min", default_value), 0, 127)
        mx = clamp_int(range_vals.get("max", default_value), 0, 127)
    except Exception:
        return clamp_int(default_value, 0, 127)
    if mx < mn:
        mn, mx = mx, mn
    return clamp_int(int(round((mn + mx) / 2.0)), 0, 127)


def note_inside_range_near_root(range_vals, root_key):
    try:
        mn = clamp_int(range_vals.get("min", root_key), 0, 127)
        mx = clamp_int(range_vals.get("max", root_key), 0, 127)
    except Exception:
        return clamp_int(root_key, 0, 127)
    if mx < mn:
        mn, mx = mx, mn
    root_key = clamp_int(root_key, 0, 127)
    return clamp_int(root_key, mn, mx)


def zone_simple_value(zone, tag, default_value=""):
    if isinstance(zone, dict):
        return str(zone.get(tag, default_value))
    return get_value(zone, tag, default_value)


def zone_loop_runtime_seconds(model, zone, zone_audio):
    zone_start = int(zone_audio.zone_start)
    zone_end = int(zone_audio.zone_end)
    sample_rate = max(1, int(zone_audio.sample_rate))
    full_duration = max(0.05, (zone_end - zone_start) / float(sample_rate))

    sustain = model.read_loop(zone, "SustainLoop")
    sustain_mode = str(sustain.get("mode", "")).strip()
    try:
        sustain_start = clamp_int(sustain.get("start", zone_start), zone_start, max(zone_start, zone_end - 1))
        sustain_end = clamp_int(sustain.get("end", zone_end), sustain_start + 1, zone_end)
    except Exception:
        sustain_start = zone_start
        sustain_end = zone_end
    sustain_loop_length = max(1, sustain_end - sustain_start)
    sustain_hold = full_duration
    if sustain_mode in ("1", "2", "3"):
        sustain_hold = max(0.05, ((sustain_start - zone_start) + sustain_loop_length) / float(sample_rate))

    release = model.read_loop(zone, "ReleaseLoop")
    release_mode = str(release.get("mode", "")).strip()
    release_wait = 0.10
    if release_mode != "0":
        try:
            release_start = clamp_int(release.get("start", zone_start), zone_start, max(zone_start, zone_end - 1))
            release_end = clamp_int(release.get("end", zone_end), release_start + 1, zone_end)
        except Exception:
            release_start = zone_start
            release_end = zone_end
        release_note_off = max(0.05, (release_start - zone_start) / float(sample_rate))
        release_span = max(0.05, (zone_end - release_start) / float(sample_rate))
        release_loop_length = max(1, release_end - release_start)
        if release_mode in ("2", "3"):
            release_span = max(release_span, (release_end - release_start + release_loop_length) / float(sample_rate))
        return min(sustain_hold, release_note_off), min(6.0, release_span)

    return sustain_hold, release_wait


def build_midi_test_plan(model, audio_cache, tempo_bpm=100.0, selector_cc=1):
    summary = model.read_global_summary()
    rr_enabled = str(summary.get("round_robin", "")).strip().lower() == "true"
    rr_mode_raw = str(summary.get("round_robin_mode", "")).strip()
    rr_mode = ROUND_ROBIN_MODE_VALUE_TO_LABEL.get(rr_mode_raw, rr_mode_raw)
    rr_random = rr_enabled and rr_mode == "random"

    zones = []
    selector_values = set()
    for index in range(model.zone_count()):
        zone = model.get_zone(index)
        key_range = model.read_range(zone, "KeyRange")
        velocity_range = model.read_range(zone, "VelocityRange")
        selector_range = model.read_range(zone, "SelectorRange")
        root_key = parse_number_from_text(zone_simple_value(zone, "RootKey", "60"), 60)
        note_value = note_inside_range_near_root(key_range, root_key)
        velocity_value = zone_range_midpoint(velocity_range, 100)
        selector_value = zone_range_midpoint(selector_range, 64)
        selector_values.add(selector_value)
        try:
            zone_audio = audio_cache.get_zone_audio(model, zone)
            hold_seconds, tail_seconds = zone_loop_runtime_seconds(model, zone, zone_audio)
        except Exception:
            hold_seconds, tail_seconds = 1.0, 0.10
        zones.append({
            "index": index,
            "name": zone_simple_value(zone, "Name", "zone {}".format(index)),
            "note": note_value,
            "velocity": velocity_value,
            "selector": selector_value,
            "hold_seconds": float(hold_seconds),
            "tail_seconds": float(tail_seconds),
        })

    grouped = {}
    for zone_info in zones:
        key = (zone_info["note"], zone_info["velocity"], zone_info["selector"])
        grouped.setdefault(key, []).append(zone_info)

    use_selector_cc = len(selector_values) > 1
    plan = []
    for trigger_key in sorted(grouped.keys(), key=lambda item: (item[0], item[1], item[2])):
        members = grouped[trigger_key]
        repeats = len(members) if rr_enabled else 1
        hold_seconds = max(member["hold_seconds"] for member in members)
        tail_seconds = max(member["tail_seconds"] for member in members)
        for repeat_index in range(repeats):
            plan.append({
                "note": int(trigger_key[0]),
                "velocity": int(trigger_key[1]),
                "selector": int(trigger_key[2]),
                "hold_seconds": float(hold_seconds),
                "tail_seconds": float(tail_seconds),
                "label": members[min(repeat_index, len(members) - 1)]["name"],
            })

    return {
        "tempo_bpm": float(tempo_bpm),
        "selector_cc": int(selector_cc),
        "use_selector_cc": bool(use_selector_cc),
        "round_robin_random": bool(rr_random),
        "events": plan,
    }


def build_midi_test_events(plan, tempo_bpm=100.0, selector_cc=1, ticks_per_quarter=480):
    events = []
    current_delta = 0
    last_selector = None
    for event in plan:
        if event.get("use_selector_cc", False):
            selector_value = clamp_int(event.get("selector", 64), 0, 127)
            if selector_value != last_selector:
                events.append((current_delta, bytes([0xB0, clamp_int(selector_cc, 0, 127), selector_value])))
                current_delta = 0
                last_selector = selector_value
        note_value = clamp_int(event.get("note", 60), 0, 127)
        velocity_value = clamp_int(event.get("velocity", 100), 1, 127)
        events.append((current_delta, bytes([0x90, note_value, velocity_value])))
        hold_ticks = midi_seconds_to_ticks(event.get("hold_seconds", 1.0), tempo_bpm=tempo_bpm, ticks_per_quarter=ticks_per_quarter)
        events.append((hold_ticks, bytes([0x80, note_value, 0])))
        current_delta = midi_seconds_to_ticks(event.get("tail_seconds", 0.10), tempo_bpm=tempo_bpm, ticks_per_quarter=ticks_per_quarter)
    return events

    # fallback: raw number = beats
    return parse_number_from_text(text, 1.0)


def get_zone_sample_rate(zone, default=44100):
    # Observed with changed sample references.
    for tag in ("DefaultSampleRate", "SampleRate"):
        value = get_value(zone, tag, None)
        if value is not None:
            try:
                return int(float(value))
            except Exception:
                pass

    # Search deeper just in case Ableton nests it.
    node = zone.find(".//DefaultSampleRate")
    if node is not None and "Value" in node.attrib:
        try:
            return int(float(node.attrib["Value"]))
        except Exception:
            pass

    return default


# =============================================================================
# Audio helpers
# =============================================================================

@dataclass
class ZoneAudioSlice:
    sample_path: Path
    sample_rate: int
    audio: object
    zone_start: int
    zone_end: int
    samples: object


class ZoneAudioCache:
    def __init__(self):
        self.cache = {}

    def clear(self):
        self.cache.clear()

    def ensure_available(self):
        missing = []
        if np is None:
            missing.append("numpy")
        if sf is None:
            missing.append("soundfile")
        if signal is None:
            missing.append("scipy")
        if missing:
            raise RuntimeError(
                "Audio analysis requires these Python packages: {}.".format(", ".join(missing))
            )

    def read_file_mono(self, path):
        self.ensure_available()

        path = Path(path).resolve()
        cache_key = str(path)
        if cache_key in self.cache:
            return self.cache[cache_key]

        audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
        if len(audio) == 0:
            raise RuntimeError("Referenced sample is empty: {}".format(path))

        mono = np.mean(audio, axis=1, dtype=np.float32)
        self.cache[cache_key] = (mono, int(sample_rate))
        return self.cache[cache_key]

    def get_zone_audio(self, model, zone):
        sample_path = model.resolve_sample_file(zone)
        audio, sample_rate = self.read_file_mono(sample_path)

        zone_start = int(float(get_value(zone, "SampleStart", "0")))
        zone_end = int(float(get_value(zone, "SampleEnd", str(len(audio)))))

        zone_start = max(0, min(zone_start, max(0, len(audio) - 1)))
        zone_end = max(zone_start + 1, min(zone_end, len(audio)))

        return ZoneAudioSlice(
            sample_path=sample_path,
            sample_rate=sample_rate,
            audio=audio,
            zone_start=zone_start,
            zone_end=zone_end,
            samples=audio[zone_start:zone_end],
        )


class AudioAnalysis:
    NORMALIZE_TARGET_RMS = db_to_linear(-18.0)
    NORMALIZE_TARGET_PEAK = 0.98
    NORMALIZE_TARGET_LUFS = -18.0

    @staticmethod
    def moving_average(values, window):
        if len(values) == 0:
            return values
        window = max(1, int(window))
        if window == 1:
            return values.copy()
        kernel = np.ones(window, dtype=np.float64) / float(window)
        return np.convolve(values, kernel, mode="same")

    @staticmethod
    def split_profile_compression(values, compression_pct=0.0):
        values = np.asarray(values, dtype=np.float64)
        if len(values) == 0:
            return values

        blend = max(0.0, min(1.0, float(compression_pct) / 100.0))
        if blend <= 0.0:
            return values.copy()

        peak = float(np.max(values))
        if peak <= 1e-12:
            return values.copy()

        normalized = np.maximum(0.0, values / peak)
        log_profile = np.log1p(normalized * 99.0) / math.log1p(99.0)
        blended = ((1.0 - blend) * normalized) + (blend * log_profile)
        return blended

    @staticmethod
    def frame_rms(samples, frame_size=2048, hop_size=256):
        samples = np.asarray(samples, dtype=np.float64)
        if len(samples) == 0:
            return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.int64)

        frame_size = max(32, min(int(frame_size), len(samples)))
        hop_size = max(1, int(hop_size))

        if len(samples) <= frame_size:
            rms = math.sqrt(float(np.mean(samples * samples)))
            return np.array([rms], dtype=np.float64), np.array([0], dtype=np.int64)

        offsets = np.arange(0, len(samples) - frame_size + 1, hop_size, dtype=np.int64)
        values = np.empty(len(offsets), dtype=np.float64)

        for i, offset in enumerate(offsets):
            window = samples[offset:offset + frame_size]
            values[i] = math.sqrt(float(np.mean(window * window)))

        return values, offsets

    @staticmethod
    def parse_offset_samples(text, sample_rate, zone_length):
        raw = str(text or "").strip().lower()
        if not raw:
            return 0

        value = parse_number_from_text(raw, 0.0)

        if "%" in raw:
            return int(round(zone_length * value / 100.0))

        if "ms" in raw:
            return int(round(sample_rate * value / 1000.0))

        if "sec" in raw or "second" in raw:
            return int(round(sample_rate * value))

        return int(round(value))

    @staticmethod
    def parse_number_unit_samples(number_text, unit_text, sample_rate, zone_length, tempo_bpm=None):
        value = parse_number_from_text(number_text, 0.0)
        unit = str(unit_text or "samples").strip().lower()

        if "%" in unit:
            return int(round(zone_length * value / 100.0))

        if unit in ("ms", "millisecond", "milliseconds"):
            return int(round(sample_rate * value / 1000.0))

        if unit in ("sec", "second", "seconds", "s"):
            return int(round(sample_rate * value))

        if "beat" in unit:
            bpm = parse_number_from_text(tempo_bpm, 120.0)
            if bpm <= 0:
                bpm = 120.0
            samples_per_beat = sample_rate * 60.0 / bpm
            return int(round(samples_per_beat * value))

        return int(round(value))

    @staticmethod
    def pitch_window_bounds(sample_count, sample_rate, params):
        sample_count = max(1, int(sample_count))
        start_offset = AudioAnalysis.parse_number_unit_samples(
            params.get("param_pitch_window_start_number", DEFAULT_PITCH_WINDOW_START_NUMBER),
            params.get("param_pitch_window_start_unit", DEFAULT_PITCH_WINDOW_START_UNIT),
            sample_rate,
            sample_count,
        )
        stop_offset = AudioAnalysis.parse_number_unit_samples(
            params.get("param_pitch_window_stop_number", DEFAULT_PITCH_WINDOW_STOP_NUMBER),
            params.get("param_pitch_window_stop_unit", DEFAULT_PITCH_WINDOW_STOP_UNIT),
            sample_rate,
            sample_count,
        )
        start_index = clamp_int(start_offset, 0, max(0, sample_count - 1))
        stop_index = clamp_int(stop_offset, start_index + 1, sample_count)
        if stop_index <= start_index:
            stop_index = min(sample_count, start_index + 1)
        return start_index, stop_index

    @staticmethod
    def detect_onsets(samples, sample_rate, sensitivity=0.5, min_duration_samples=1000, profile_compression_pct=0.0):
        sensitivity = max(0.01, min(0.99, float(sensitivity)))
        min_duration_samples = max(64, int(min_duration_samples))

        frame_size = min(4096, max(512, sample_rate // 20))
        hop_size = max(64, frame_size // 8)
        envelope, offsets = AudioAnalysis.frame_rms(samples, frame_size=frame_size, hop_size=hop_size)

        if len(envelope) < 3:
            return []

        smoothed = AudioAnalysis.moving_average(envelope, 5)
        profiled = AudioAnalysis.split_profile_compression(smoothed, profile_compression_pct)
        delta = np.maximum(0.0, np.diff(profiled, prepend=profiled[0]))
        peak_delta = float(np.max(delta))
        if peak_delta <= 0:
            return []

        threshold = peak_delta * sensitivity
        distance_frames = max(1, int(min_duration_samples / float(hop_size)))
        peaks, _props = signal.find_peaks(delta, height=threshold, distance=distance_frames)

        onsets = []
        for peak in peaks:
            sample_offset = int(offsets[min(int(peak), len(offsets) - 1)])
            if sample_offset < min_duration_samples // 2:
                continue
            if sample_offset >= len(samples) - min_duration_samples // 2:
                continue
            onsets.append(sample_offset)

        return onsets

    @staticmethod
    def detect_gate_onsets(
        samples,
        sample_rate,
        sensitivity=0.5,
        min_duration_samples=1000,
        profile_compression_pct=0.0,
        stop_hysteresis_pct=60.0,
        start_placement="local attack",
    ):
        sensitivity = max(0.01, min(0.99, float(sensitivity)))
        min_duration_samples = max(64, int(min_duration_samples))

        frame_size = min(4096, max(512, sample_rate // 20))
        hop_size = max(64, frame_size // 8)
        envelope, offsets = AudioAnalysis.frame_rms(samples, frame_size=frame_size, hop_size=hop_size)

        if len(envelope) < 3:
            return []

        smoothed = AudioAnalysis.moving_average(envelope, 5)
        profiled = AudioAnalysis.split_profile_compression(smoothed, profile_compression_pct)
        peak_level = float(np.max(profiled))
        if peak_level <= 0:
            return []

        start_threshold = sensitivity
        stop_ratio = max(0.01, min(1.0, float(stop_hysteresis_pct) / 100.0))
        stop_threshold = start_threshold * stop_ratio
        min_gap_frames = max(1, int(min_duration_samples / float(hop_size)))
        quiet_hold_frames = max(1, min_gap_frames // 3)
        max_anchor_frames = max(1, min(int(round(0.10 * sample_rate / float(hop_size))), min_gap_frames * 2))
        delta = np.maximum(0.0, np.diff(profiled, prepend=profiled[0]))

        onsets = []
        active = False
        quiet_run = 0
        region_entry_idx = None

        def frame_to_sample(frame_idx):
            sample_offset = int(offsets[min(int(frame_idx), len(offsets) - 1)] + (frame_size // 2))
            return max(0, min(sample_offset, len(samples) - 1))

        def finalize_onset(entry_idx, region_end_idx):
            threshold_sample = frame_to_sample(entry_idx)
            placement = str(start_placement or "local attack").strip().lower()
            if placement == "threshold":
                return threshold_sample

            search_end_idx = max(entry_idx + 1, min(region_end_idx + 1, entry_idx + max_anchor_frames))
            search_delta = delta[entry_idx:search_end_idx]
            if len(search_delta) == 0 or float(np.max(search_delta)) <= 0:
                return threshold_sample

            peak_idx = int(np.argmax(search_delta)) + entry_idx
            attack_sample = frame_to_sample(peak_idx)
            if placement == "local attack":
                return attack_sample

            return threshold_sample

        for idx, level in enumerate(profiled):
            sample_offset = frame_to_sample(idx)
            if not active:
                if level >= start_threshold:
                    if sample_offset < min_duration_samples // 2:
                        active = True
                        region_entry_idx = idx
                        quiet_run = 0
                        continue
                    if onsets and sample_offset - onsets[-1] < min_duration_samples:
                        active = True
                        region_entry_idx = idx
                        quiet_run = 0
                        continue
                    if sample_offset >= len(samples) - min_duration_samples // 2:
                        continue
                    active = True
                    region_entry_idx = idx
                    quiet_run = 0
            else:
                if level <= stop_threshold:
                    quiet_run += 1
                    if quiet_run >= quiet_hold_frames:
                        region_end_idx = idx - quiet_run + 1
                        onset_sample = finalize_onset(region_entry_idx, region_end_idx)
                        if not onsets or onset_sample - onsets[-1] >= min_duration_samples:
                            onsets.append(onset_sample)
                        active = False
                        region_entry_idx = None
                        quiet_run = 0
                else:
                    quiet_run = 0

        if active and region_entry_idx is not None:
            onset_sample = finalize_onset(region_entry_idx, len(profiled) - 1)
            if not onsets or onset_sample - onsets[-1] >= min_duration_samples:
                onsets.append(onset_sample)

        return onsets

    @staticmethod
    def onset_strength_profile(samples, sample_rate):
        frame_size = min(4096, max(512, sample_rate // 20))
        hop_size = max(64, frame_size // 8)
        envelope, offsets = AudioAnalysis.frame_rms(samples, frame_size=frame_size, hop_size=hop_size)
        if len(envelope) < 3:
            return None

        smoothed = AudioAnalysis.moving_average(envelope, 5)
        delta = np.maximum(0.0, np.diff(smoothed, prepend=smoothed[0]))
        return {
            "frame_size": frame_size,
            "hop_size": hop_size,
            "offsets": offsets,
            "envelope": envelope,
            "smoothed": smoothed,
            "delta": delta,
        }

    @staticmethod
    def suggest_onset_sensitivity(samples, sample_rate):
        profile = AudioAnalysis.onset_strength_profile(samples, sample_rate)
        if profile is None:
            return None

        delta = profile["delta"]
        peak_delta = float(np.max(delta))
        if peak_delta <= 1e-12:
            return None

        positive = delta[delta > 0]
        if len(positive) < 8:
            return None

        sorted_positive = np.sort(positive)
        noise_cutoff_index = max(1, int(round(len(sorted_positive) * 0.70)))
        noise_band = sorted_positive[:noise_cutoff_index]
        noise_floor = float(np.percentile(noise_band, 90))
        noise_median = float(np.median(noise_band))
        noise_spread = float(np.median(np.abs(noise_band - noise_median)) * 1.4826)

        peak_distance = max(1, int(0.05 * sample_rate / float(profile["hop_size"])))
        peaks, _props = signal.find_peaks(delta, distance=peak_distance)
        if len(peaks) == 0:
            candidate_values = positive
        else:
            candidate_values = delta[peaks]

        clear_floor = noise_floor + max(noise_spread * 4.0, peak_delta * 0.015)
        clear_values = candidate_values[candidate_values >= clear_floor]
        if len(clear_values) == 0:
            clear_floor = noise_floor + max(noise_spread * 2.0, peak_delta * 0.008)
            clear_values = candidate_values[candidate_values >= clear_floor]
        if len(clear_values) == 0:
            return None

        quietest_clear = float(np.min(clear_values))
        midpoint = 0.5 * (noise_floor + quietest_clear)
        sensitivity = midpoint / peak_delta
        sensitivity = max(0.02, min(0.95, sensitivity))

        return {
            "noise_floor": noise_floor,
            "quietest_clear": quietest_clear,
            "midpoint": midpoint,
            "peak_delta": peak_delta,
            "sensitivity": sensitivity,
        }

    @staticmethod
    def detect_activity_bounds(
        samples,
        release_threshold=0.02,
        tail_margin_samples=0,
        next_activity_threshold=None,
        quiet_hold_samples=None,
    ):
        samples = np.asarray(samples, dtype=np.float64)
        if len(samples) == 0:
            return 0, 0

        abs_samples = np.abs(samples)
        peak = float(np.max(abs_samples))
        if peak <= 1e-9:
            return 0, len(samples)

        release_threshold = max(1e-6, float(release_threshold))
        attack_threshold = max(release_threshold, peak * 0.08)
        tail_margin_samples = max(0, int(tail_margin_samples))
        if next_activity_threshold is None:
            next_activity_threshold = release_threshold
        next_activity_threshold = max(1e-6, float(next_activity_threshold))

        window = min(4096, max(128, len(samples) // 256))
        envelope = AudioAnalysis.moving_average(abs_samples, window)

        attack_indices = np.where(envelope >= attack_threshold)[0]
        if len(attack_indices) == 0:
            return 0, len(samples)

        start = int(attack_indices[0])
        quiet_hold_samples = int(
            quiet_hold_samples
            if quiet_hold_samples is not None
            else max(window * 2, min(2048, max(window, len(samples) // 64)))
        )
        quiet_hold_samples = max(16, min(quiet_hold_samples, max(16, len(samples) - start)))

        below_threshold = envelope < release_threshold
        quiet_start = None
        quiet_run = 0
        for idx in range(start, len(envelope)):
            if below_threshold[idx]:
                quiet_run += 1
                if quiet_run >= quiet_hold_samples:
                    quiet_start = idx - quiet_run + 1
                    break
            else:
                quiet_run = 0

        if quiet_start is None:
            release_indices = np.where(envelope >= release_threshold)[0]
            if len(release_indices) == 0:
                return 0, len(samples)
            end = int(release_indices[-1] + 1)
            end = max(start + 1, min(end, len(samples)))
            return start, end

        next_activity_start = None
        activity_hold_samples = max(4, min(quiet_hold_samples // 4, 256))
        activity_run = 0
        scan_start = min(len(envelope), quiet_start + quiet_hold_samples)
        for idx in range(scan_start, len(envelope)):
            if envelope[idx] >= next_activity_threshold:
                activity_run += 1
                if activity_run >= activity_hold_samples:
                    next_activity_start = idx - activity_run + 1
                    break
            else:
                activity_run = 0

        end = quiet_start + tail_margin_samples
        if next_activity_start is not None:
            end = min(end, next_activity_start)
        end = max(start + 1, min(end, len(samples)))
        return start, end

    @staticmethod
    def select_pitch_window(samples, sample_rate):
        samples = np.asarray(samples, dtype=np.float64)
        if len(samples) <= sample_rate // 8:
            return samples

        start = min(len(samples) - 1, max(0, int(len(samples) * 0.10)))
        end = max(start + sample_rate // 8, int(len(samples) * 0.60))
        end = min(len(samples), end)

        window = samples[start:end]
        max_length = max(sample_rate // 2, min(len(window), sample_rate * 2))
        return window[:max_length]

    @staticmethod
    def detect_pitch_hz(samples, sample_rate, min_hz=24.0, max_hz=2000.0):
        samples = AudioAnalysis.select_pitch_window(samples, sample_rate)
        if len(samples) < max(2048, sample_rate // 20):
            return None

        values = np.asarray(samples, dtype=np.float64)
        values = values - np.mean(values)
        peak = float(np.max(np.abs(values)))
        if peak <= 1e-8:
            return None

        values = values / peak
        values = values * np.hanning(len(values))

        corr = signal.correlate(values, values, mode="full", method="fft")
        corr = corr[len(corr) // 2:]

        min_lag = max(1, int(sample_rate / float(max_hz)))
        max_lag = min(len(corr) - 2, int(sample_rate / float(min_hz)))
        if max_lag <= min_lag:
            return None

        search = corr[min_lag:max_lag + 1]
        peak_index = int(np.argmax(search)) + min_lag
        if corr[peak_index] <= 0:
            return None

        lag = float(peak_index)
        if 1 <= peak_index < len(corr) - 1:
            alpha = corr[peak_index - 1]
            beta = corr[peak_index]
            gamma = corr[peak_index + 1]
            denom = alpha - (2.0 * beta) + gamma
            if abs(float(denom)) > 1e-12:
                lag += 0.5 * float(alpha - gamma) / float(denom)

        if lag <= 0:
            return None

        freq = float(sample_rate) / lag
        if not (min_hz <= freq <= max_hz):
            return None
        return AudioAnalysis.correct_subharmonic_pitch_hz(values, sample_rate, freq, min_hz=min_hz, max_hz=max_hz)

    @staticmethod
    def spectral_harmonic_score(values, sample_rate, freq_hz, harmonic_count=8):
        values = np.asarray(values, dtype=np.float64)
        if len(values) < 64 or freq_hz <= 0:
            return 0.0
        magnitudes = np.abs(np.fft.rfft(values))
        freqs = np.fft.rfftfreq(len(values), 1.0 / float(sample_rate))
        if len(freqs) == 0:
            return 0.0

        score = 0.0
        for harmonic in range(1, int(harmonic_count) + 1):
            target_hz = float(freq_hz) * harmonic
            if target_hz >= freqs[-1]:
                break
            idx = int(np.searchsorted(freqs, target_hz))
            lo = max(0, idx - 1)
            hi = min(len(magnitudes), idx + 2)
            if hi <= lo:
                continue
            score += float(np.max(magnitudes[lo:hi])) / harmonic
        return score

    @staticmethod
    def correct_subharmonic_pitch_hz(values, sample_rate, base_freq_hz, min_hz=24.0, max_hz=2000.0):
        base_freq_hz = float(base_freq_hz)
        if not (min_hz <= base_freq_hz <= max_hz):
            return base_freq_hz

        candidates = []
        for multiplier in (1, 2, 3, 4):
            candidate_hz = base_freq_hz * multiplier
            if not (min_hz <= candidate_hz <= max_hz):
                continue
            score = AudioAnalysis.spectral_harmonic_score(values, sample_rate, candidate_hz)
            if multiplier > 1:
                score *= 0.97 ** (multiplier - 1)
            candidates.append((score, multiplier, candidate_hz))

        if not candidates:
            return base_freq_hz

        candidates.sort(reverse=True)
        best_score, best_multiplier, best_freq_hz = candidates[0]
        base_score = next((score for score, multiplier, _freq_hz in candidates if multiplier == 1), 0.0)
        if best_multiplier > 1 and best_score > (base_score * 1.25):
            return float(best_freq_hz)
        return base_freq_hz

    @staticmethod
    def frequency_to_midi_parts(freq_hz, diapason_hz=440.0):
        diapason_hz = max(1e-6, float(parse_number_from_text(diapason_hz, 440.0)))
        midi_float = 69.0 + (12.0 * math.log2(float(freq_hz) / diapason_hz))
        root_key = int(round(midi_float))
        cents = (midi_float - root_key) * 100.0
        root_key = clamp_int(root_key, 0, 127)
        cents = max(-50.0, min(50.0, cents))
        return midi_float, root_key, cents

    @staticmethod
    def midi_key_to_frequency(root_key, diapason_hz=440.0):
        root_key = clamp_int(root_key, 0, 127)
        diapason_hz = max(1e-6, float(parse_number_from_text(diapason_hz, 440.0)))
        return diapason_hz * math.pow(2.0, (root_key - 69) / 12.0)

    @staticmethod
    def detect_loop_playback_pitch_info(loop_samples, sample_rate, reference_hz=None):
        values = np.asarray(loop_samples, dtype=np.float64)
        if len(values) < 2:
            return None

        detected_hz = AudioAnalysis.detect_pitch_hz(values, sample_rate)
        if reference_hz is None or reference_hz <= 0:
            if detected_hz is None:
                return None
            return {"freq_hz": float(detected_hz), "method": "autocorr", "cycles": None}

        estimated_cycles = max(1, int(round((len(values) * float(reference_hz)) / float(sample_rate))))
        derived_hz = float(sample_rate) * float(estimated_cycles) / float(len(values))
        use_length_method = len(values) < max(2048, sample_rate // 20) or estimated_cycles <= 4

        if use_length_method or detected_hz is None:
            return {
                "freq_hz": derived_hz,
                "method": "loop_length",
                "cycles": int(estimated_cycles),
            }

        return {
            "freq_hz": float(detected_hz),
            "method": "autocorr",
            "cycles": int(estimated_cycles),
        }

    @staticmethod
    def release_loop_basis_start(samples, sample_rate, basis_label, sustain_loop_end_rel=None, release_region_start=None):
        values = np.asarray(samples, dtype=np.float64)
        sample_count = len(values)
        if sample_count <= 0:
            return 0

        basis = str(basis_label or "note-end to end").strip().lower()
        if basis == "start to end":
            return 0
        if basis == "loop-end to end":
            sustain_end = 0 if sustain_loop_end_rel is None else int(sustain_loop_end_rel)
            return max(0, min(sample_count - 1, sustain_end))
        if release_region_start is None:
            release_region_start = 0
        return max(0, min(sample_count - 1, int(release_region_start)))

    @staticmethod
    def estimate_loop_detune_info(zone_samples, loop_samples, sample_rate, fallback_root_key=None, diapason_hz=440.0):
        target_hz = AudioAnalysis.detect_pitch_hz(zone_samples, sample_rate)
        if target_hz is None and fallback_root_key is not None:
            target_hz = AudioAnalysis.midi_key_to_frequency(fallback_root_key, diapason_hz=diapason_hz)
        if target_hz is None or target_hz <= 0:
            return None

        loop_info = AudioAnalysis.detect_loop_playback_pitch_info(loop_samples, sample_rate, reference_hz=target_hz)
        if loop_info is None or loop_info["freq_hz"] <= 0:
            return None

        detune_cents = 1200.0 * math.log2(float(target_hz) / float(loop_info["freq_hz"]))
        detune_cents = max(-1200.0, min(1200.0, detune_cents))
        return {
            "target_hz": float(target_hz),
            "loop_hz": float(loop_info["freq_hz"]),
            "detune_cents": float(detune_cents),
            "method": loop_info["method"],
            "cycles": loop_info.get("cycles"),
        }

    @staticmethod
    def compute_level(samples, mode):
        values = np.asarray(samples, dtype=np.float64)
        if len(values) == 0:
            return 0.0

        if str(mode).strip().lower() == "peak":
            return float(np.max(np.abs(values)))

        return math.sqrt(float(np.mean(values * values)))

    @staticmethod
    def compute_lufs(samples, sample_rate):
        values = np.asarray(samples, dtype=np.float64)
        if values.ndim > 1:
            values = np.mean(values, axis=1)
        if len(values) == 0:
            return None

        if signal is not None and sample_rate and sample_rate > 200:
            try:
                b, a = signal.butter(1, 60.0 / (float(sample_rate) * 0.5), btype="highpass")
                values = signal.lfilter(b, a, values)
            except Exception:
                pass

        frame_size = max(1, int(round(float(sample_rate) * 0.4)))
        hop_size = max(1, int(round(float(sample_rate) * 0.1)))
        if len(values) <= frame_size:
            energies = np.array([float(np.mean(values * values))], dtype=np.float64)
        else:
            energies = []
            for offset in range(0, len(values) - frame_size + 1, hop_size):
                frame = values[offset:offset + frame_size]
                energies.append(float(np.mean(frame * frame)))
            energies = np.asarray(energies, dtype=np.float64)

        if len(energies) == 0:
            return None

        abs_gate = -70.0
        frame_lufs = -0.691 + (10.0 * np.log10(np.maximum(energies, 1e-12)))
        abs_mask = frame_lufs > abs_gate
        if not np.any(abs_mask):
            return float(np.max(frame_lufs))

        ungated_energy = float(np.mean(energies[abs_mask]))
        ungated_lufs = -0.691 + (10.0 * math.log10(max(ungated_energy, 1e-12)))
        rel_gate = ungated_lufs - 10.0
        gated_mask = abs_mask & (frame_lufs > rel_gate)
        if not np.any(gated_mask):
            gated_mask = abs_mask

        integrated_energy = float(np.mean(energies[gated_mask]))
        return -0.691 + (10.0 * math.log10(max(integrated_energy, 1e-12)))

    @staticmethod
    def compute_peak(samples):
        values = np.asarray(samples, dtype=np.float64)
        if len(values) == 0:
            return 0.0
        return float(np.max(np.abs(values)))

    @staticmethod
    def estimate_note_strength(samples, sample_rate):
        values = np.asarray(samples, dtype=np.float64)
        if len(values) == 0:
            return 0.0

        peak = AudioAnalysis.compute_peak(values)
        if peak <= 1e-9:
            return 0.0

        frame_size = min(len(values), max(128, min(2048, sample_rate // 40)))
        hop_size = max(1, frame_size // 4)
        rms_values, _offsets = AudioAnalysis.frame_rms(values, frame_size=frame_size, hop_size=hop_size)
        if len(rms_values) == 0:
            return peak

        max_rms = float(np.max(rms_values))
        abs_values = np.abs(values)
        percentile_95 = float(np.percentile(abs_values, 95))

        # Emphasize sustained energy over isolated spikes while keeping a
        # little peak sensitivity for very short notes.
        return (max_rms * 0.8) + (percentile_95 * 0.2)

    @staticmethod
    def bounded_positions(lo, hi, step, anchor, max_positions=48):
        lo = int(lo)
        hi = int(hi)
        step = max(1, int(step))
        if hi <= lo:
            return [lo]

        positions = list(range(lo, hi + 1, step))
        if positions[-1] != hi:
            positions.append(hi)
        if anchor < lo or anchor > hi:
            return positions
        if anchor not in positions:
            positions.append(int(anchor))
        positions = sorted(set(positions))

        max_positions = max(8, int(max_positions))
        if len(positions) > max_positions:
            positions = [int(round(v)) for v in np.linspace(lo, hi, max_positions)]
            positions.append(int(anchor))
            positions = sorted(set(positions))

        return positions

    @staticmethod
    def resolve_crossfade_samples(sample_rate, loop_length, policy_label, custom_number, custom_unit, pitch_hz=None):
        loop_length = max(0, int(loop_length))
        policy = str(policy_label or "Custom").strip()

        if loop_length <= 0 or policy == "No fade":
            return 0
        if policy == "Longest possible":
            return max(0, loop_length // 2)
        if policy == "One waveform":
            if pitch_hz and pitch_hz > 0:
                period = int(round(sample_rate / float(pitch_hz)))
            else:
                period = max(16, sample_rate // 220)
            return max(0, min(loop_length // 2, int(period)))

        custom = AudioAnalysis.parse_number_unit_samples(
            custom_number,
            custom_unit,
            sample_rate,
            loop_length,
        )
        return max(0, min(loop_length // 2, int(custom)))

    @staticmethod
    def nearest_zero_crossing(values, boundary_index, search_radius=12):
        values = np.asarray(values, dtype=np.float64)
        if len(values) < 2:
            return None

        boundary_index = int(boundary_index)
        lo = max(0, boundary_index - int(search_radius))
        hi = min(len(values) - 2, boundary_index + int(search_radius))
        best = None

        for idx in range(lo, hi + 1):
            a = float(values[idx])
            b = float(values[idx + 1])
            if a <= 0.0 < b:
                direction = 1
            else:
                continue
            distance = abs((idx + 0.5) - float(boundary_index))
            magnitude = abs(a) + abs(b)
            candidate = (distance, magnitude, direction, idx + 1)
            if best is None or candidate[:2] < best[:2]:
                best = candidate

        if best is None:
            return None
        return {
            "distance": float(best[0]),
            "magnitude": float(best[1]),
            "direction": int(best[2]),
            "boundary_index": int(best[3]),
        }

    @staticmethod
    def snap_loop_boundaries_to_zero_crossings(values, loop_start, loop_end, search_radius=24):
        start_cross = AudioAnalysis.nearest_zero_crossing(values, loop_start, search_radius=search_radius)
        end_cross = AudioAnalysis.nearest_zero_crossing(values, loop_end - 1, search_radius=search_radius)
        if start_cross is None or end_cross is None:
            return int(loop_start), int(loop_end)

        snapped_start = int(start_cross["boundary_index"])
        snapped_end = int(end_cross["boundary_index"])
        if snapped_end <= snapped_start:
            return int(loop_start), int(loop_end)
        return snapped_start, snapped_end

    @staticmethod
    def loop_candidate_score(values, loop_start, loop_end, match_window, fade_samples=0, target_start=None, target_end=None, search_half=0):
        head = values[loop_start:loop_start + match_window]
        tail = values[loop_end - match_window:loop_end]
        if len(head) < match_window or len(tail) < match_window:
            return None

        diff = head - tail
        level = float(np.mean(np.abs(head)) + np.mean(np.abs(tail)) + 1e-9)
        seam_level = float(abs(values[loop_start]) + abs(values[loop_end - 1]) + 1e-9)
        score = 1.35 * float(np.mean(diff * diff)) / level
        score += 0.90 * abs(float(values[loop_start]) - float(values[loop_end - 1])) / seam_level

        if head[0] * tail[-1] < 0:
            score += 0.25
        if len(head) > 1 and len(tail) > 1:
            head_slope = float(head[1] - head[0])
            tail_slope = float(tail[-1] - tail[-2])
            if head_slope * tail_slope < 0:
                score += 0.40
            score += 0.45 * abs(head_slope - tail_slope) / seam_level

        score += 0.12 * abs(float(np.mean(head)) - float(np.mean(tail)))

        start_cross = AudioAnalysis.nearest_zero_crossing(values, loop_start)
        end_cross = AudioAnalysis.nearest_zero_crossing(values, loop_end - 1)
        if start_cross is not None and end_cross is not None:
            crossing_distance_penalty = 0.08 * (start_cross["distance"] + end_cross["distance"])
            if start_cross["direction"] == end_cross["direction"]:
                score += crossing_distance_penalty
            else:
                score += 1.50 + crossing_distance_penalty
        else:
            score += 0.55 * (abs(float(values[loop_start])) + abs(float(values[loop_end - 1]))) / level

        fade_samples = max(0, min(int(fade_samples), (loop_end - loop_start) // 2))
        if fade_samples >= 4:
            fade_in = values[loop_start:loop_start + fade_samples]
            fade_out = values[loop_end - fade_samples:loop_end]
            if len(fade_in) == fade_samples and len(fade_out) == fade_samples:
                weights = np.linspace(1.0, 0.15, fade_samples, dtype=np.float64)
                fade_diff = fade_in - fade_out
                fade_level = float(np.mean(np.abs(fade_in)) + np.mean(np.abs(fade_out)) + 1e-9)
                score += 0.18 * float(np.mean((fade_diff * fade_diff) * weights)) / fade_level

        if search_half and search_half > 0 and target_start is not None:
            penalty = abs(loop_start - int(target_start))
            if target_end is not None:
                penalty += abs(loop_end - int(target_end))
                score += 0.10 * penalty / float(search_half * 2)
            else:
                score += 0.10 * penalty / float(search_half)

        return score

    @staticmethod
    def find_loop_points(samples, sample_rate, start_pct=25.0, end_pct=75.0, shift_pct=25.0, search_range_samples=None, fade_policy="No fade", fade_custom_number="25", fade_custom_unit="%", pitch_hz=None, target_start_sample=None, target_end_sample=None):
        values = np.asarray(samples, dtype=np.float64)
        zone_length = len(values)
        if zone_length < 2048:
            return None

        start_pct = max(0.0, min(95.0, float(start_pct)))
        end_pct = max(start_pct + 1.0, min(99.0, float(end_pct)))
        shift_pct = max(0.0, float(shift_pct))

        target_start = int(zone_length * start_pct / 100.0) if target_start_sample is None else int(target_start_sample)
        target_end = int(zone_length * end_pct / 100.0) if target_end_sample is None else int(target_end_sample)
        target_start = max(0, min(target_start, zone_length - 2))
        target_end = max(target_start + 1, min(target_end, zone_length - 1))
        if search_range_samples is None:
            search_half = min(int(zone_length * shift_pct / 100.0), sample_rate * 4)
        else:
            search_half = max(0, min(int(search_range_samples), sample_rate * 4))

        if pitch_hz is None:
            sustain_start = int(zone_length * 0.20)
            sustain_end = int(zone_length * 0.80)
            pitch_hz = AudioAnalysis.detect_pitch_hz(values[sustain_start:sustain_end], sample_rate)

        period = int(round(sample_rate / pitch_hz)) if pitch_hz else max(64, sample_rate // 220)
        period = max(16, period)

        match_window = max(256, min(4096, period * 4))
        min_loop_length = max(match_window, period * 2)

        start_lo = max(0, target_start - search_half)
        start_hi = min(zone_length - match_window - 1, target_start + search_half)
        end_lo = max(start_lo + min_loop_length, target_end - search_half)
        end_hi = min(zone_length - 1, target_end + search_half)

        if start_hi < start_lo or end_hi < end_lo:
            return None

        step = max(16, period // 4)
        start_positions = AudioAnalysis.bounded_positions(start_lo, start_hi, step, target_start)
        end_positions = AudioAnalysis.bounded_positions(end_lo, end_hi, step, target_end)

        best = None

        for loop_start in start_positions:
            head = values[loop_start:loop_start + match_window]
            if len(head) < match_window:
                continue

            for loop_end in end_positions:
                if loop_end - loop_start < min_loop_length:
                    continue
                loop_length = loop_end - loop_start
                fade_samples = AudioAnalysis.resolve_crossfade_samples(
                    sample_rate,
                    loop_length,
                    fade_policy,
                    fade_custom_number,
                    fade_custom_unit,
                    pitch_hz=pitch_hz,
                )
                score = AudioAnalysis.loop_candidate_score(
                    values,
                    loop_start,
                    loop_end,
                    match_window,
                    fade_samples=fade_samples,
                    target_start=target_start,
                    target_end=target_end,
                    search_half=search_half,
                )
                if score is None:
                    continue

                if best is None or score < best["score"]:
                    best = {
                        "start": int(loop_start),
                        "end": int(loop_end),
                        "score": score,
                        "period": int(period),
                        "crossfade": int(fade_samples),
                    }

        if best is None:
            return None
        snapped_start, snapped_end = AudioAnalysis.snap_loop_boundaries_to_zero_crossings(values, best["start"], best["end"])
        best["start"] = int(snapped_start)
        best["end"] = int(snapped_end)
        best["crossfade"] = int(min(max(0, best.get("crossfade", 0)), max(0, (best["end"] - best["start"]) // 2)))
        return best

    @staticmethod
    def optimize_crossfade_samples(samples, sample_rate, loop_start_rel, loop_end_rel, min_spec, max_spec, preference, default_crossfade=0):
        values = np.asarray(samples, dtype=np.float64)
        loop_start_rel = int(loop_start_rel)
        loop_end_rel = int(loop_end_rel)
        loop_length = loop_end_rel - loop_start_rel

        if loop_length <= 64:
            return 0

        min_samples = max(16, int(AudioAnalysis.parse_offset_samples(str(min_spec), sample_rate, loop_length)))
        max_samples = max(16, int(AudioAnalysis.parse_offset_samples(str(max_spec), sample_rate, loop_length)))
        max_samples = min(loop_length // 2, max_samples)
        min_samples = min(min_samples, max_samples)

        if max_samples < min_samples:
            return min(max_samples, max(0, int(default_crossfade)))

        lengths = {min_samples, max_samples}
        if min_samples < max_samples:
            for value in np.linspace(min_samples, max_samples, 24):
                lengths.add(int(round(value)))
        if default_crossfade:
            lengths.add(int(default_crossfade))

        best_length = 0
        best_score = None
        preference_name = str(preference or "balanced").strip().lower()
        preference_penalties = {
            "clean seam": 0.08,
            "balanced": 0.22,
            "short fade": 0.45,
        }
        length_penalty = preference_penalties.get(preference_name, preference_penalties["balanced"])

        for length in sorted(v for v in lengths if min_samples <= v <= max_samples):
            head = values[loop_start_rel:loop_start_rel + length]
            tail = values[loop_end_rel - length:loop_end_rel]
            if len(head) != length or len(tail) != length:
                continue

            diff = head - tail
            mse = float(np.mean(diff * diff))
            level_mismatch = abs(float(np.mean(head)) - float(np.mean(tail)))
            if length > 1:
                head_slope = float(head[1] - head[0])
                tail_slope = float(tail[-1] - tail[-2])
            else:
                head_slope = 0.0
                tail_slope = 0.0
            slope_mismatch = abs(head_slope - tail_slope)
            score = (
                mse
                + (0.5 * level_mismatch)
                + (0.25 * slope_mismatch)
                + (length_penalty * (length / float(loop_length)))
            )

            if best_score is None or score < best_score:
                best_score = score
                best_length = int(length)

        return best_length

    @staticmethod
    def find_release_loop_to_sample_end(samples, sample_rate, start_pct=85.0, shift_pct=10.0, search_range_samples=None, fade_policy="No fade", fade_custom_number="25", fade_custom_unit="%", pitch_hz=None, target_start_sample=None):
        values = np.asarray(samples, dtype=np.float64)
        zone_length = len(values)
        if zone_length < 2048:
            return None

        start_pct = max(0.0, min(95.0, float(start_pct)))
        shift_pct = max(0.0, float(shift_pct))
        target_start = int(zone_length * start_pct / 100.0) if target_start_sample is None else int(target_start_sample)
        target_start = max(0, min(target_start, zone_length - 2))
        loop_end = zone_length
        if search_range_samples is None:
            search_half = min(int(zone_length * shift_pct / 100.0), sample_rate * 4)
        else:
            search_half = max(0, min(int(search_range_samples), sample_rate * 4))

        if pitch_hz is None:
            sustain_start = int(zone_length * 0.20)
            sustain_end = int(zone_length * 0.95)
            pitch_hz = AudioAnalysis.detect_pitch_hz(values[sustain_start:sustain_end], sample_rate)

        period = int(round(sample_rate / pitch_hz)) if pitch_hz else max(64, sample_rate // 220)
        period = max(16, period)

        match_window = max(256, min(4096, period * 4))
        min_loop_length = max(match_window, period * 2)
        start_lo = max(0, target_start - search_half)
        start_hi = min(zone_length - match_window - 1, target_start + search_half)
        if start_hi < start_lo:
            return None

        tail = values[max(0, loop_end - match_window):loop_end]
        if len(tail) < match_window:
            return None

        step = max(16, period // 4)
        start_positions = AudioAnalysis.bounded_positions(start_lo, start_hi, step, target_start)
        best = None

        for loop_start in start_positions:
            if loop_end - loop_start < min_loop_length:
                continue
            loop_length = loop_end - loop_start
            fade_samples = AudioAnalysis.resolve_crossfade_samples(
                sample_rate,
                loop_length,
                fade_policy,
                fade_custom_number,
                fade_custom_unit,
                pitch_hz=pitch_hz,
            )
            score = AudioAnalysis.loop_candidate_score(
                values,
                loop_start,
                loop_end,
                match_window,
                fade_samples=fade_samples,
                target_start=target_start,
                target_end=None,
                search_half=search_half,
            )
            if score is None:
                continue

            if best is None or score < best["score"]:
                best = {
                    "start": int(loop_start),
                    "end": int(loop_end),
                    "score": score,
                    "period": int(period),
                    "crossfade": int(fade_samples),
                }

        if best is None:
            return None
        snapped_start, snapped_end = AudioAnalysis.snap_loop_boundaries_to_zero_crossings(values, best["start"], best["end"])
        best["start"] = int(snapped_start)
        best["end"] = int(snapped_end)
        best["crossfade"] = int(min(max(0, best.get("crossfade", 0)), max(0, (best["end"] - best["start"]) // 2)))
        return best

    @staticmethod
    def detect_release_region_start(samples, release_threshold=0.02, next_activity_threshold=None):
        values = np.asarray(samples, dtype=np.float64)
        if len(values) < 64:
            return None

        if next_activity_threshold is None:
            next_activity_threshold = release_threshold

        _activity_start, activity_end = AudioAnalysis.detect_activity_bounds(
            values,
            release_threshold=release_threshold,
            tail_margin_samples=0,
            next_activity_threshold=next_activity_threshold,
        )
        activity_end = max(0, min(int(activity_end), len(values) - 1))
        remaining = len(values) - activity_end
        if remaining < 2048:
            return None
        return activity_end


def apply_hardcoded_scratch_preset_defaults(model):
    for spec in iter_default_preset_field_specs():
        model.write_default_preset_field(spec, spec.get("default", ""))
    scratch_values = dict(SCRATCH_PRESET_GLOBAL_VALUES)
    for key in list(scratch_values):
        if key in DEFAULT_TOOL_TEMPLATE_GLOBAL_VALUES:
            scratch_values[key] = DEFAULT_TOOL_TEMPLATE_GLOBAL_VALUES[key]
    model.apply_global_values(
        scratch_values,
        SCRATCH_PRESET_GLOBAL_UPDATES,
        log_func=None,
    )


# =============================================================================
# Processing logic
# =============================================================================

class SamplerProcessors:
    """
    Processing namespace.

    Order matters:
    - split
    - mapping
    - per-zone audio refinements
    """

    @staticmethod
    def enabled_processing_flags(gui_processing_update):
        return [k for k, v in gui_processing_update.items() if v.get()]

    @staticmethod
    def zone_label(zone, fallback_index=None):
        name = get_value(zone, "Name", "").strip()
        if name:
            return name
        if fallback_index is None:
            return "zone"
        return "zone {}".format(fallback_index)

    @staticmethod
    def duplicate_source_zone_with_bounds(model, source_zone, zone_index, original_start, original_end, bounds, name_suffix):
        new_zones = []
        next_id = model.next_zone_id()
        old_name = get_value(source_zone, "Name", "zone")

        for idx, (zone_start, zone_end) in enumerate(bounds, start=1):
            z = copy.deepcopy(source_zone)
            model.set_zone_id(z, next_id)
            next_id += 1
            set_value(z, "Name", "{}_{}_{:03d}".format(old_name, name_suffix, idx))
            model.set_zone_bounds_with_proportional_loops(
                z,
                original_start,
                original_end,
                int(zone_start),
                int(zone_end),
            )
            new_zones.append(z)

        model.replace_zone_with_zones(zone_index, new_zones)
        return len(new_zones)

    @staticmethod
    def split_boundaries_from_onsets(zone_start, zone_end, onsets, min_duration_samples, include_first_zone=True):
        include_first_zone = bool(include_first_zone)
        boundaries = [int(zone_start)] if include_first_zone else []

        for onset in onsets:
            absolute_onset = int(zone_start) + int(onset)
            if not boundaries:
                boundaries.append(absolute_onset)
            elif absolute_onset - boundaries[-1] >= min_duration_samples:
                boundaries.append(absolute_onset)

        bounds = []
        for idx, slice_start in enumerate(boundaries):
            slice_end = boundaries[idx + 1] if idx + 1 < len(boundaries) else int(zone_end)
            if slice_end - slice_start >= min_duration_samples:
                bounds.append((int(slice_start), int(slice_end)))

        return bounds

    @staticmethod
    def split_selected_zone_by_detection(model, zone_index, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        if zone_index is None:
            raise RuntimeError("Select a source zone before splitting.")

        source = model.get_zone(zone_index)
        source_audio = audio_cache.get_zone_audio(model, source)
        if len(source_audio.samples) < 2048:
            log("Detection split: source zone is too short to analyze; skipped.\n")
            return 0

        sensitivity = parse_number_from_text(
            params.get("param_split_sensitivity", DEFAULT_DETECTION_SPLIT_SENSITIVITY),
            parse_number_from_text(DEFAULT_DETECTION_SPLIT_SENSITIVITY, 0.5),
        )
        min_duration_samples = int(
            parse_number_from_text(
                params.get("param_min_duration", DEFAULT_DETECTION_SPLIT_MIN_DURATION),
                parse_number_from_text(DEFAULT_DETECTION_SPLIT_MIN_DURATION, 1000),
            )
        )
        profile_compression_pct = parse_number_from_text(
            params.get("param_split_profile_compression", DEFAULT_DETECTION_PROFILE_COMPRESSION),
            parse_number_from_text(DEFAULT_DETECTION_PROFILE_COMPRESSION, 0.0),
        )
        include_first_zone_raw = params.get("param_split_include_first_zone", False)
        if isinstance(include_first_zone_raw, bool):
            include_first_zone = include_first_zone_raw
        else:
            include_first_zone = str(include_first_zone_raw).strip().lower() != "false"

        onsets = AudioAnalysis.detect_onsets(
            source_audio.samples,
            source_audio.sample_rate,
            sensitivity=sensitivity,
            min_duration_samples=min_duration_samples,
            profile_compression_pct=profile_compression_pct,
        )

        if not onsets:
            log("Detection split: no usable onset found inside selected zone.\n")
            return 0

        bounds = SamplerProcessors.split_boundaries_from_onsets(
            source_audio.zone_start,
            source_audio.zone_end,
            onsets,
            min_duration_samples,
            include_first_zone=include_first_zone,
        )

        if len(bounds) <= 1:
            log("Detection split: all candidate slices were too short after filtering.\n")
            return 0

        count = SamplerProcessors.duplicate_source_zone_with_bounds(
            model,
            source,
            zone_index,
            source_audio.zone_start,
            source_audio.zone_end,
            bounds,
            "detect",
        )
        log(
            "Detection split: replaced zone {} with {} zones. threshold={} compression={} min_duration={} onsets={} include_first={}\n".format(
                zone_index,
                count,
                sensitivity,
                profile_compression_pct,
                min_duration_samples,
                len(onsets),
                include_first_zone,
            )
        )
        return count

    @staticmethod
    def split_selected_zone_by_gate(model, zone_index, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        if zone_index is None:
            raise RuntimeError("Select a source zone before splitting.")

        source = model.get_zone(zone_index)
        source_audio = audio_cache.get_zone_audio(model, source)
        if len(source_audio.samples) < 2048:
            log("Detect split: source zone is too short to analyze; skipped.\n")
            return 0

        sensitivity = parse_number_from_text(
            params.get("param_gate_sensitivity", DEFAULT_GATE_SPLIT_SENSITIVITY),
            parse_number_from_text(DEFAULT_GATE_SPLIT_SENSITIVITY, 0.35),
        )
        min_duration_samples = int(
            parse_number_from_text(
                params.get("param_gate_min_duration", DEFAULT_GATE_SPLIT_MIN_DURATION),
                parse_number_from_text(DEFAULT_GATE_SPLIT_MIN_DURATION, 2000),
            )
        )
        profile_compression_pct = parse_number_from_text(
            params.get("param_gate_profile_compression", DEFAULT_GATE_PROFILE_COMPRESSION),
            parse_number_from_text(DEFAULT_GATE_PROFILE_COMPRESSION, 50.0),
        )
        stop_hysteresis_pct = parse_number_from_text(
            params.get("param_gate_stop_hysteresis_pct", DEFAULT_GATE_STOP_HYSTERESIS_PCT),
            parse_number_from_text(DEFAULT_GATE_STOP_HYSTERESIS_PCT, 60.0),
        )
        start_placement = str(params.get("param_gate_start_placement", DEFAULT_GATE_START_PLACEMENT)).strip()
        include_first_zone_raw = params.get("param_gate_include_first_zone", False)
        if isinstance(include_first_zone_raw, bool):
            include_first_zone = include_first_zone_raw
        else:
            include_first_zone = str(include_first_zone_raw).strip().lower() != "false"

        onsets = AudioAnalysis.detect_gate_onsets(
            source_audio.samples,
            source_audio.sample_rate,
            sensitivity=sensitivity,
            min_duration_samples=min_duration_samples,
            profile_compression_pct=profile_compression_pct,
            stop_hysteresis_pct=stop_hysteresis_pct,
            start_placement=start_placement,
        )

        if not onsets:
            log("Detect split: no usable level region found inside selected zone.\n")
            return 0

        bounds = SamplerProcessors.split_boundaries_from_onsets(
            source_audio.zone_start,
            source_audio.zone_end,
            onsets,
            min_duration_samples,
            include_first_zone=include_first_zone,
        )

        if len(bounds) <= 1:
            log("Detect split: all candidate slices were too short after filtering.\n")
            return 0

        count = SamplerProcessors.duplicate_source_zone_with_bounds(
            model,
            source,
            zone_index,
            source_audio.zone_start,
            source_audio.zone_end,
            bounds,
            "gate",
        )
        log(
            "Detect split: replaced zone {} with {} zones. threshold={} compression={} hysteresis={} placement={} min_duration={} regions={} include_first={}\n".format(
                zone_index,
                count,
                sensitivity,
                profile_compression_pct,
                stop_hysteresis_pct,
                start_placement,
                min_duration_samples,
                len(onsets),
                include_first_zone,
            )
        )
        return count

    @staticmethod
    def split_all_zones_by_detection(model, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        original_zone_count = model.zone_count()
        total_generated = 0
        zones_changed = 0

        for zone_index in range(original_zone_count - 1, -1, -1):
            before_count = model.zone_count()
            generated = SamplerProcessors.split_selected_zone_by_detection(
                model,
                zone_index,
                params,
                audio_cache=audio_cache,
                log_func=log_func,
            )
            after_count = model.zone_count()
            if generated > 0 and after_count != before_count:
                zones_changed += 1
                total_generated += generated

        if zones_changed == 0:
            log("Detection split: no zone was split.\n")
        else:
            log(
                "Detection split summary: split {} original zone(s) into {} generated zone(s).\n".format(
                    zones_changed,
                    total_generated,
                )
            )

        return total_generated

    @staticmethod
    def split_all_zones_by_gate(model, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        original_zone_count = model.zone_count()
        total_generated = 0
        zones_changed = 0

        for zone_index in range(original_zone_count - 1, -1, -1):
            before_count = model.zone_count()
            generated = SamplerProcessors.split_selected_zone_by_gate(
                model,
                zone_index,
                params,
                audio_cache=audio_cache,
                log_func=log_func,
            )
            after_count = model.zone_count()
            if generated > 0 and after_count != before_count:
                zones_changed += 1
                total_generated += generated

        if zones_changed == 0:
            log("Detect split: no zone was split.\n")
        else:
            log(
                "Detect split summary: split {} original zone(s) into {} generated zone(s).\n".format(
                    zones_changed,
                    total_generated,
                )
            )

        return total_generated

    @staticmethod
    def split_selected_zone_by_grid(model, zone_index, params, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        if zone_index is None:
            raise RuntimeError("Select a source zone before splitting.")

        source = model.get_zone(zone_index)

        original_start = int(float(get_value(source, "SampleStart", "0")))
        original_end = int(float(get_value(source, "SampleEnd", "0")))

        if original_start >= original_end:
            raise ValueError("Source zone SampleStart must be < SampleEnd.")

        sample_rate = get_zone_sample_rate(source, default=44100)

        bpm = parse_number_from_text(params.get("param_grid_tempo", "100"), 100.0)

        every_text = "{} {}".format(
            params.get("param_grid_every_number", "1"),
            params.get("param_grid_every_unit", "bar")
        )
        end_after_text = "{} {}".format(
            params.get("param_grid_end_after_number", "3"),
            params.get("param_grid_end_after_unit", "beats")
        )

        every_beats = duration_text_to_beats(every_text)
        end_after_beats = duration_text_to_beats(end_after_text)

        if bpm <= 0:
            raise ValueError("Grid tempo must be > 0.")
        if every_beats <= 0:
            raise ValueError("Grid spacing must be > 0.")
        if end_after_beats <= 0:
            raise ValueError("Grid zone duration must be > 0.")

        samples_per_beat = sample_rate * 60.0 / bpm
        step_samples = max(1, int(round(every_beats * samples_per_beat)))
        duration_samples = max(1, int(round(end_after_beats * samples_per_beat)))

        new_zones = []
        next_id = model.next_zone_id()
        pos = original_start
        idx = 0

        while pos < original_end:
            zone_start = pos
            zone_end = min(original_end, zone_start + duration_samples)

            if zone_end <= zone_start:
                break

            z = copy.deepcopy(source)
            model.set_zone_id(z, next_id)
            next_id += 1

            old_name = get_value(z, "Name", "zone")
            set_value(z, "Name", "{}_grid_{:03d}".format(old_name, idx + 1))

            model.set_zone_bounds_with_proportional_loops(
                z,
                original_start,
                original_end,
                zone_start,
                zone_end
            )

            new_zones.append(z)

            pos += step_samples
            idx += 1

            # Safety guard against accidental infinite explosion.
            if idx > 2048:
                raise RuntimeError("Too many zones generated (>2048). Check tempo/grid settings.")

        if not new_zones:
            raise RuntimeError("Grid split produced no zones.")

        model.replace_zone_with_zones(zone_index, new_zones)
        log("Grid split: replaced zone {} with {} zones. sample_rate={} bpm={} step={} duration={}\n".format(
            zone_index,
            len(new_zones),
            sample_rate,
            bpm,
            step_samples,
            duration_samples
        ))

        return len(new_zones)

    @staticmethod
    def split_all_zones_by_grid(model, params, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        original_zone_count = model.zone_count()
        total_generated = 0
        zones_changed = 0

        for zone_index in range(original_zone_count - 1, -1, -1):
            before_count = model.zone_count()
            generated = SamplerProcessors.split_selected_zone_by_grid(
                model,
                zone_index,
                params,
                log_func=log_func,
            )
            after_count = model.zone_count()
            if generated > 0 and after_count != before_count:
                zones_changed += 1
                total_generated += generated

        if zones_changed == 0:
            log("Grid split: no zone was split.\n")
        else:
            log(
                "Grid split summary: split {} original zone(s) into {} generated zone(s).\n".format(
                    zones_changed,
                    total_generated,
                )
            )

        return total_generated

    @staticmethod
    def refine_zone_bounds(model, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        release_threshold = parse_number_from_text(
            params.get("param_release_threshold", DEFAULT_REFINE_RELEASE_THRESHOLD),
            parse_number_from_text(DEFAULT_REFINE_RELEASE_THRESHOLD, 0.0005),
        )
        updated = 0

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            audio = audio_cache.get_zone_audio(model, zone)
            if len(audio.samples) < 64:
                continue

            zone_length = len(audio.samples)
            release_tail_margin = max(
                0,
                AudioAnalysis.parse_number_unit_samples(
                    params.get("param_release_tail_number", DEFAULT_REFINE_TAIL_NUMBER),
                    params.get("param_release_tail_unit", DEFAULT_REFINE_TAIL_UNIT),
                    audio.sample_rate,
                    zone_length,
                ),
            )
            next_activity_threshold = parse_number_from_text(
                params.get("param_next_activity_threshold", DEFAULT_REFINE_NEXT_ACTIVITY_THRESHOLD),
                release_threshold,
            )
            rel_start, rel_end = AudioAnalysis.detect_activity_bounds(
                audio.samples,
                release_threshold=release_threshold,
                tail_margin_samples=release_tail_margin,
                next_activity_threshold=next_activity_threshold,
            )
            start_shift = AudioAnalysis.parse_number_unit_samples(
                params.get("param_shift_start_number", DEFAULT_REFINE_SHIFT_START_NUMBER),
                params.get("param_shift_start_unit", DEFAULT_REFINE_SHIFT_START_UNIT),
                audio.sample_rate,
                zone_length,
                tempo_bpm=params.get("param_shift_start_tempo", DEFAULT_REFINE_SHIFT_START_TEMPO),
            )
            stop_shift = AudioAnalysis.parse_number_unit_samples(
                params.get("param_shift_stop_number", DEFAULT_REFINE_SHIFT_STOP_NUMBER),
                params.get("param_shift_stop_unit", DEFAULT_REFINE_SHIFT_STOP_UNIT),
                audio.sample_rate,
                zone_length,
                tempo_bpm=params.get("param_shift_stop_tempo", DEFAULT_REFINE_SHIFT_STOP_TEMPO),
            )

            new_start = audio.zone_start + rel_start + start_shift
            new_end = audio.zone_start + rel_end + stop_shift
            new_start = max(audio.zone_start, min(new_start, audio.zone_end - 1))
            new_end = max(new_start + 1, min(new_end, audio.zone_end))

            if new_start == audio.zone_start and new_end == audio.zone_end:
                continue

            model.set_zone_bounds_with_proportional_loops(
                zone,
                audio.zone_start,
                audio.zone_end,
                new_start,
                new_end,
            )
            updated += 1

            log(
                "Refined {}: {}-{} -> {}-{} (threshold={})\n".format(
                    SamplerProcessors.zone_label(zone, i),
                    audio.zone_start,
                    audio.zone_end,
                    new_start,
                    new_end,
                    release_threshold,
                )
            )

        if updated == 0:
            log("Start/end refinement: no zone boundary changed.\n")

        return updated

    @staticmethod
    def normalize_zone_volumes(model, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        mode = str(params.get("param_normalize_mode", "RMS")).strip()
        mode_lower = mode.lower()
        target = AudioAnalysis.NORMALIZE_TARGET_PEAK if mode_lower == "peak" else AudioAnalysis.NORMALIZE_TARGET_RMS
        normalize_amount = max(0.0, min(1.0, parse_number_from_text(params.get("param_normalize_amount_pct", "100"), 100.0) / 100.0))
        updated = 0

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            audio = audio_cache.get_zone_audio(model, zone)
            raw_peak = AudioAnalysis.compute_peak(audio.samples)
            if raw_peak <= 1e-9:
                continue

            if mode_lower == "lufs":
                raw_lufs = AudioAnalysis.compute_lufs(audio.samples, audio.sample_rate)
                if raw_lufs is None:
                    continue
                fully_normalized_volume = math.pow(10.0, (AudioAnalysis.NORMALIZE_TARGET_LUFS - raw_lufs) / 20.0)
            else:
                raw_level = AudioAnalysis.compute_level(audio.samples, mode)
                if raw_level <= 1e-9:
                    continue
                fully_normalized_volume = target / raw_level

            max_safe_volume = 0.99 / raw_peak
            fully_normalized_volume = min(fully_normalized_volume, max_safe_volume)
            current_volume = float(get_value(zone, "Volume", "1") or 1.0)
            new_volume = current_volume + ((fully_normalized_volume - current_volume) * normalize_amount)
            new_volume = min(new_volume, max_safe_volume)

            if abs(new_volume - current_volume) < 1e-7:
                continue

            set_value(zone, "Volume", "{:.8f}".format(new_volume))
            updated += 1
            log(
                "Normalized {}: mode={} amount={:.1f}% volume {:.6f} -> {:.6f}\n".format(
                    SamplerProcessors.zone_label(zone, i),
                    mode,
                    normalize_amount * 100.0,
                    current_volume,
                    new_volume,
                )
            )

        if updated == 0:
            log("Volume normalization: no zone volume changed.\n")
        else:
            target_label = AudioAnalysis.NORMALIZE_TARGET_LUFS if mode_lower == "lufs" else round(target, 6)
            log("Volume normalization: updated {} zone(s) with {} target {} at {:.1f}% amount.\n".format(updated, mode, target_label, normalize_amount * 100.0))

        return updated

    @staticmethod
    def detect_zone_pitch(model, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        detect_root = bool(params.get("pitch_detection_root", False))
        detect_detune = bool(params.get("pitch_detection_detune", False))
        if not detect_root and not detect_detune:
            return 0
        diapason_hz = parse_number_from_text(params.get("param_diapason_hz", DEFAULT_DIAPASON_HZ), 440.0)

        updated = 0

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            audio = audio_cache.get_zone_audio(model, zone)
            window_start, window_stop = AudioAnalysis.pitch_window_bounds(len(audio.samples), audio.sample_rate, params)
            freq_hz = AudioAnalysis.detect_pitch_hz(audio.samples[window_start:window_stop], audio.sample_rate)
            if freq_hz is None:
                log("Pitch detection: could not estimate pitch for {}.\n".format(SamplerProcessors.zone_label(zone, i)))
                continue

            _midi_float, detected_root, detected_cents = AudioAnalysis.frequency_to_midi_parts(freq_hz, diapason_hz=diapason_hz)
            zone_changed = False

            if detect_root:
                if get_value(zone, "RootKey", "") != str(detected_root):
                    set_value(zone, "RootKey", detected_root)
                    zone_changed = True

            if detect_detune:
                if detect_root:
                    detune_cents = detected_cents
                else:
                    current_root = clamp_int(parse_number_from_text(get_value(zone, "RootKey", "60"), 60), 0, 127)
                    _midi_existing, _ignored_root, detune_cents = AudioAnalysis.frequency_to_midi_parts(freq_hz, diapason_hz=diapason_hz)
                    detune_cents = (_midi_existing - current_root) * 100.0
                    if detune_cents < -50.0 or detune_cents > 50.0:
                        log(
                            "Pitch detection: skipped detune for {} because detected pitch is too far from current RootKey {}.\n".format(
                                SamplerProcessors.zone_label(zone, i),
                                current_root,
                            )
                        )
                        detune_cents = None

                if detune_cents is not None:
                    detune_value = clamp_int(round(detune_cents), -50, 50)
                    if get_value(zone, "Detune", "") != str(detune_value):
                        set_value(zone, "Detune", detune_value)
                        zone_changed = True

            if zone_changed:
                updated += 1
                log(
                    "Pitch detection: {} -> {:.2f} Hz, RootKey={}, Detune={:+d} ct\n".format(
                        SamplerProcessors.zone_label(zone, i),
                        freq_hz,
                        get_value(zone, "RootKey", ""),
                        clamp_int(parse_number_from_text(get_value(zone, "Detune", "0"), 0), -50, 50),
                    )
                )

        if updated == 0:
            log("Pitch detection: no zone metadata changed.\n")

        return updated

    @staticmethod
    def detect_zone_loops(model, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        updated = 0

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            audio = audio_cache.get_zone_audio(model, zone)
            pitch_hz = AudioAnalysis.detect_pitch_hz(audio.samples, audio.sample_rate)
            zone_changed = False
            for loop_tag, loop_label, prefix in (
                ("SustainLoop", "sustain", "sustain"),
                ("ReleaseLoop", "release", "release"),
            ):
                flag_key = "loop_detection" if prefix == "sustain" else "release_loop_detection"
                if not params.get(flag_key, False):
                    continue

                default_search_number = "25" if prefix == "sustain" else "10"
                search_range_number = params.get("param_{}_loop_search_number".format(prefix), default_search_number)
                search_range_unit = params.get("param_{}_loop_search_unit".format(prefix), "%")
                crossfade_policy = params.get("param_{}_crossfade_policy".format(prefix), "No fade")
                crossfade_custom_number = params.get("param_{}_crossfade_custom_number".format(prefix), "25")
                crossfade_custom_unit = params.get("param_{}_crossfade_custom_unit".format(prefix), "%")
                start_number = params.get("param_{}_loop_start_pct".format(prefix), "25")
                start_unit = params.get("param_{}_loop_start_unit".format(prefix), "%")
                release_loop_uses_absolute_start = False

                if prefix == "release":
                    release_loop_uses_absolute_start = True
                    release_threshold = parse_number_from_text(
                        params.get("param_release_threshold", DEFAULT_REFINE_RELEASE_THRESHOLD),
                        parse_number_from_text(DEFAULT_REFINE_RELEASE_THRESHOLD, 0.0005),
                    )
                    next_activity_threshold = parse_number_from_text(
                        params.get("param_next_activity_threshold", DEFAULT_REFINE_NEXT_ACTIVITY_THRESHOLD),
                        release_threshold,
                    )
                    release_region_start = AudioAnalysis.detect_release_region_start(
                        audio.samples,
                        release_threshold=release_threshold,
                        next_activity_threshold=next_activity_threshold,
                    )
                    start_reference = str(params.get("param_release_loop_start_reference", "note-end to end")).strip().lower()
                    sustain_loop_end_rel = None
                    if params.get("loop_detection", False):
                        sustain_vals_for_basis = model.read_loop(zone, "SustainLoop")
                        try:
                            sustain_loop_end_rel = int(float(sustain_vals_for_basis.get("end", ""))) - int(audio.zone_start)
                        except Exception:
                            sustain_loop_end_rel = None
                    basis_start = AudioAnalysis.release_loop_basis_start(
                        audio.samples,
                        audio.sample_rate,
                        start_reference,
                        sustain_loop_end_rel=sustain_loop_end_rel,
                        release_region_start=release_region_start,
                    )
                    basis_span = max(1, len(audio.samples) - int(basis_start))
                    search_range_samples = AudioAnalysis.parse_number_unit_samples(
                        search_range_number,
                        search_range_unit,
                        audio.sample_rate,
                        basis_span,
                    )
                    target_offset = AudioAnalysis.parse_number_unit_samples(
                        start_number,
                        start_unit,
                        audio.sample_rate,
                        basis_span,
                    )
                    target_start_sample = int(basis_start) + int(target_offset)
                    loop_info = AudioAnalysis.find_release_loop_to_sample_end(
                        audio.samples,
                        audio.sample_rate,
                        target_start_sample=target_start_sample,
                        search_range_samples=search_range_samples,
                        fade_policy=crossfade_policy,
                        fade_custom_number=crossfade_custom_number,
                        fade_custom_unit=crossfade_custom_unit,
                        pitch_hz=pitch_hz,
                    )
                else:
                    end_number = params.get("param_{}_loop_end_pct".format(prefix), "75")
                    end_unit = params.get("param_{}_loop_end_unit".format(prefix), "%")
                    search_range_samples = AudioAnalysis.parse_number_unit_samples(
                        search_range_number,
                        search_range_unit,
                        audio.sample_rate,
                        len(audio.samples),
                    )
                    target_start_sample = AudioAnalysis.parse_number_unit_samples(
                        start_number,
                        start_unit,
                        audio.sample_rate,
                        len(audio.samples),
                    )
                    target_end_sample = AudioAnalysis.parse_number_unit_samples(
                        end_number,
                        end_unit,
                        audio.sample_rate,
                        len(audio.samples),
                    )
                    loop_info = AudioAnalysis.find_loop_points(
                        audio.samples,
                        audio.sample_rate,
                        target_start_sample=target_start_sample,
                        target_end_sample=target_end_sample,
                        search_range_samples=search_range_samples,
                        fade_policy=crossfade_policy,
                        fade_custom_number=crossfade_custom_number,
                        fade_custom_unit=crossfade_custom_unit,
                        pitch_hz=pitch_hz,
                    )
                if loop_info is None:
                    log("Loop detection: no good {} loop found for {}.\n".format(loop_label, SamplerProcessors.zone_label(zone, i)))
                    continue

                loop_offset = int(release_region_start) if prefix == "release" and release_region_start is not None and not release_loop_uses_absolute_start else 0
                loop_start = audio.zone_start + loop_offset + loop_info["start"]
                loop_end = audio.zone_start + loop_offset + loop_info["end"]
                loop_length = max(1, loop_end - loop_start)
                crossfade = clamp_loop_crossfade(audio.zone_start, loop_start, loop_end, int(loop_info.get("crossfade", 0)))
                mode_label = str(params.get("param_{}_loop_mode".format(prefix), "on")).strip()
                mode_value = loop_mode_value_from_label(prefix, mode_label)

                loop_vals = model.read_loop(zone, loop_tag)
                before = (
                    loop_vals.get("start", ""),
                    loop_vals.get("end", ""),
                    loop_vals.get("mode", ""),
                    loop_vals.get("crossfade", ""),
                )
                loop_vals["start"] = str(loop_start)
                loop_vals["end"] = str(loop_end)
                loop_vals["mode"] = str(mode_value)
                loop_vals["crossfade"] = str(crossfade)
                model.write_loop(zone, loop_tag, loop_vals)
                after = (
                    loop_vals["start"],
                    loop_vals["end"],
                    loop_vals["mode"],
                    loop_vals["crossfade"],
                )
                if after != before:
                    zone_changed = True
                log(
                    "Loop detection: {} {} loop -> start={} end={} crossfade={} period={} release_start={}\n".format(
                        SamplerProcessors.zone_label(zone, i),
                        loop_label,
                        loop_start,
                        loop_end,
                        crossfade,
                        loop_info["period"],
                        loop_offset if prefix == "release" else "-",
                    )
                )

            model.clamp_loops_to_sample_bounds(zone)
            if zone_changed:
                updated += 1

        if updated == 0:
            log("Loop detection: no zone loop was changed.\n")

        return updated

    @staticmethod
    def optimize_zone_crossfades(model, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        updated = 0

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            audio = audio_cache.get_zone_audio(model, zone)
            zone_changed = False

            for loop_tag, loop_label, prefix in (
                ("SustainLoop", "sustain", "sustain"),
                ("ReleaseLoop", "release", "release"),
            ):
                detect_flag_key = "loop_detection" if prefix == "sustain" else "release_loop_detection"
                optimize_flag_key = "crossfade_optimization" if prefix == "sustain" else "release_crossfade_optimization"
                if not params.get(detect_flag_key, False) or not params.get(optimize_flag_key, False):
                    continue

                loop_vals = model.read_loop(zone, loop_tag)
                try:
                    loop_start = int(float(loop_vals["start"]))
                    loop_end = int(float(loop_vals["end"]))
                    current_crossfade = int(float(loop_vals["crossfade"] or 0))
                except Exception:
                    continue

                if loop_start >= loop_end:
                    continue

                rel_start = loop_start - audio.zone_start
                rel_end = loop_end - audio.zone_start
                if rel_start < 0 or rel_end > len(audio.samples):
                    continue

                crossfade = AudioAnalysis.optimize_crossfade_samples(
                    audio.samples,
                    audio.sample_rate,
                    rel_start,
                    rel_end,
                    "{} {}".format(
                        params.get("param_{}_crossfade_min_number".format(prefix), "500"),
                        params.get("param_{}_crossfade_min_unit".format(prefix), "samples"),
                    ),
                    "{} {}".format(
                        params.get("param_{}_crossfade_max_number".format(prefix), "50"),
                        params.get("param_{}_crossfade_max_unit".format(prefix), "%"),
                    ),
                    params.get("param_{}_crossfade_preference".format(prefix), "balanced"),
                    default_crossfade=current_crossfade,
                )

                if crossfade == current_crossfade:
                    continue

                loop_vals["crossfade"] = str(crossfade)
                model.write_loop(zone, loop_tag, loop_vals)
                zone_changed = True
                log(
                    "Crossfade optimization: {} {} loop -> {} samples\n".format(
                        SamplerProcessors.zone_label(zone, i),
                        loop_label,
                        crossfade,
                    )
                )

            if zone_changed:
                updated += 1

        if updated == 0:
            log("Crossfade optimization: no loop crossfade changed.\n")

        return updated

    @staticmethod
    def key_spread_root_groups(model):
        root_to_indices = {}

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            raw = get_value(zone, "RootKey", None)
            if raw is None:
                continue
            try:
                root = int(float(raw))
            except Exception:
                continue
            root = max(0, min(127, root))
            root_to_indices.setdefault(root, []).append(i)

        roots = sorted(root_to_indices.keys())
        return roots, root_to_indices

    @staticmethod
    def spread_around_root(model, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        roots, root_to_indices = SamplerProcessors.key_spread_root_groups(model)

        if not roots:
            log("Spread around root: no usable RootKey values found.\n")
            return 0

        ranges = {}

        for idx, root in enumerate(roots):
            if idx == 0:
                mn = 0
            else:
                prev_root = roots[idx - 1]
                mn = int((prev_root + root) // 2) + 1

            if idx == len(roots) - 1:
                mx = 127
            else:
                next_root = roots[idx + 1]
                mx = int((root + next_root) // 2)

            mn = max(0, min(127, mn))
            mx = max(0, min(127, mx))
            if mn > mx:
                mn, mx = mx, mn

            ranges[root] = {
                "min": str(mn),
                "max": str(mx),
                "xfade_min": str(mn),
                "xfade_max": str(mx),
            }

        count = 0
        for root, indices in root_to_indices.items():
            for i in indices:
                zone = model.get_zone(i)
                model.write_range(zone, "KeyRange", ranges[root])
                count += 1

        log("Spread around root: updated KeyRange on {} zones across {} root keys.\n".format(count, len(roots)))
        return count

    @staticmethod
    def spread_evenly(model, key_min=0, key_max=127, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        roots, root_to_indices = SamplerProcessors.key_spread_root_groups(model)
        if not roots:
            log("Spread evenly: no usable RootKey values found.\n")
            return 0

        key_min = max(0, min(127, int(key_min)))
        key_max = max(0, min(127, int(key_max)))
        if key_min > key_max:
            key_min, key_max = key_max, key_min

        total_width = max(1, (key_max - key_min + 1))
        ranges = {}
        for idx, root in enumerate(roots):
            mn = key_min + int(math.floor((idx * total_width) / float(len(roots))))
            mx = key_min + int(math.floor(((idx + 1) * total_width) / float(len(roots)))) - 1
            mx = max(mn, min(key_max, mx))
            ranges[root] = {
                "min": str(mn),
                "max": str(mx),
                "xfade_min": str(mn),
                "xfade_max": str(mx),
            }

        count = 0
        for root, indices in root_to_indices.items():
            for i in indices:
                model.write_range(model.get_zone(i), "KeyRange", ranges[root])
                count += 1

        log("Spread evenly: updated KeyRange on {} zones across {} root keys inside {}-{}.\n".format(count, len(roots), key_min, key_max))
        return count

    @staticmethod
    def spread_one_note_per_key(model, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        roots, root_to_indices = SamplerProcessors.key_spread_root_groups(model)
        if not roots:
            log("One note per key: no usable RootKey values found.\n")
            return 0

        count = 0
        for root, indices in root_to_indices.items():
            vals = {
                "min": str(root),
                "max": str(root),
                "xfade_min": str(root),
                "xfade_max": str(root),
            }
            for i in indices:
                model.write_range(model.get_zone(i), "KeyRange", vals)
                count += 1

        log("One note per key: updated KeyRange on {} zones across {} root keys.\n".format(count, len(roots)))
        return count

    @staticmethod
    def spread_first_note_interval(model, first_note=0, interval=1, repeat_count=1, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        zone_count = model.zone_count()
        if zone_count <= 0:
            log("First note + interval: no zones found.\n")
            return 0

        first_note = clamp_int(parse_number_from_text(first_note, 0), 0, 127)
        interval = max(1, int(round(parse_number_from_text(interval, 1))))
        repeat_count = max(1, int(round(parse_number_from_text(repeat_count, 1))))
        centers = []
        for idx in range(zone_count):
            group_index = idx // repeat_count
            center = clamp_int(first_note + (group_index * interval), 0, 127)
            centers.append(center)

        unique_centers = []
        center_to_range = {}
        for center in centers:
            if center not in center_to_range:
                unique_centers.append(center)
                center_to_range[center] = None

        for idx, center in enumerate(unique_centers):
            if idx == 0:
                mn = 0
            else:
                mn = int((unique_centers[idx - 1] + center) // 2) + 1

            if idx == len(unique_centers) - 1:
                mx = 127
            else:
                mx = int((center + unique_centers[idx + 1]) // 2)

            mn = max(0, min(127, mn))
            mx = max(0, min(127, mx))
            if mn > mx:
                mn, mx = mx, mn

            center_to_range[center] = {
                "min": str(mn),
                "max": str(mx),
                "xfade_min": str(mn),
                "xfade_max": str(mx),
            }

        count = 0
        for idx, center in enumerate(centers):
            vals = center_to_range[center]
            model.write_range(model.get_zone(idx), "KeyRange", vals)
            count += 1

        log("First note + interval: updated KeyRange on {} zones from {} every {} semitone(s), repeating each note {} time(s).\n".format(count, first_note, interval, repeat_count))
        return count

    @staticmethod
    def spread_key_zones(model, params, log_func=None):
        mode = str(params.get("param_key_spread_mode", "around root key")).strip().lower()
        if mode == "around root key":
            return SamplerProcessors.spread_around_root(model, log_func=log_func)
        if mode == "spread evenly":
            return SamplerProcessors.spread_evenly(
                model,
                key_min=parse_number_from_text(params.get("param_key_spread_min", "0"), 0),
                key_max=parse_number_from_text(params.get("param_key_spread_max", "127"), 127),
                log_func=log_func,
            )
        if mode == "one note per key":
            return SamplerProcessors.spread_first_note_interval(
                model,
                first_note=params.get("param_key_spread_first_note", "0"),
                interval="1",
                repeat_count="1",
                log_func=log_func,
            )
        if mode == "first note + interval":
            return SamplerProcessors.spread_first_note_interval(
                model,
                first_note=params.get("param_key_spread_first_note", "0"),
                interval=params.get("param_key_spread_interval", "1"),
                repeat_count=params.get("param_key_spread_repeat_count", "1"),
                log_func=log_func,
            )
        if log_func:
            log_func("Spread key zones: unknown mode {}; skipped.\n".format(mode))
        return 0

    @staticmethod
    def parse_filename_mapping_tokens(text):
        tokens = {}
        for prefix, raw_value in FILENAME_MAPPING_PATTERN.findall(str(text or "")):
            tokens[prefix.upper()] = int(raw_value)
        return tokens

    @staticmethod
    def apply_filename_mapping(model, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        updated = 0
        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            sample_path, relative_path = model.extract_sample_path(zone)
            zone_name = zone.get("Name", "zone") if isinstance(zone, dict) else get_value(zone, "Name", "zone")
            candidate = Path(str(sample_path or relative_path or zone_name)).stem
            tokens = SamplerProcessors.parse_filename_mapping_tokens(candidate)
            if not tokens:
                continue

            zone_changed = False
            if "P" in tokens:
                root_key = clamp_int(tokens["P"], 0, 127)
                current_root = zone.get("RootKey", "") if isinstance(zone, dict) else get_value(zone, "RootKey", "")
                if current_root != str(root_key):
                    if isinstance(zone, dict):
                        zone["RootKey"] = str(root_key)
                    else:
                        set_value(zone, "RootKey", root_key)
                    zone_changed = True
            if "D" in tokens:
                detune = clamp_int(tokens["D"], -50, 50)
                current_detune = zone.get("Detune", "") if isinstance(zone, dict) else get_value(zone, "Detune", "")
                if current_detune != str(detune):
                    if isinstance(zone, dict):
                        zone["Detune"] = str(detune)
                    else:
                        set_value(zone, "Detune", detune)
                    zone_changed = True
            if "V" in tokens:
                vel = clamp_int(tokens["V"], 1, 127)
                current = model.read_range(zone, "VelocityRange")
                target = {"min": str(vel), "max": str(vel), "xfade_min": str(vel), "xfade_max": str(vel)}
                if current != target:
                    model.write_range(zone, "VelocityRange", target)
                    zone_changed = True
            if "C" in tokens:
                chain = clamp_int(tokens["C"], 0, 127)
                current = model.read_range(zone, "SelectorRange")
                target = {"min": str(chain), "max": str(chain), "xfade_min": str(chain), "xfade_max": str(chain)}
                if current != target:
                    model.write_range(zone, "SelectorRange", target)
                    zone_changed = True

            if zone_changed:
                updated += 1
                log("Filename mapping: {} -> {}\n".format(candidate, tokens))

        if updated == 0:
            log("Filename mapping: no zone changed.\n")
        return updated

    @staticmethod
    def zone_play_area_key(model, zone):
        """
        Return the grouping key for zones that are effectively competing
        for the same playback space.

        Zones are grouped by KeyRange and SelectorRange.
        RootKey is ignored so detected notes can still be regrouped before
        key spreading has been applied.
        """
        key_range = model.read_range(zone, "KeyRange")
        selector_range = model.read_range(zone, "SelectorRange")

        return (
            key_range["min"],
            key_range["max"],
            selector_range["min"],
            selector_range["max"],
        )

    @staticmethod
    def zone_chain_area_key(model, zone):
        key_range = model.read_range(zone, "KeyRange")
        velocity_range = model.read_range(zone, "VelocityRange")
        return (
            key_range["min"],
            key_range["max"],
            velocity_range["min"],
            velocity_range["max"],
        )

    @staticmethod
    def distribute_velocity_by_play_area(model, gamma=1.0, log_func=None):
        """
        Distribute VelocityRange among zones sharing the same playback area.

        Grouping:
        - identical KeyRange Min/Max
        - identical SelectorRange Min/Max

        This is better than grouping by RootKey because several different
        root notes can still overlap completely if Spread around root note
        has not been applied.

        Current behavior:
        - zones are kept in XML order inside each group
        - velocity 1..127 is split among them
        - gamma controls non-linear distribution:
            gamma = 1.0 -> linear
            gamma < 1.0 -> lower velocities get more space
            gamma > 1.0 -> higher velocities get more space
        - no velocity crossfade is introduced here:
            CrossfadeMin = Min
            CrossfadeMax = Max
        """
        def log(text):
            if log_func:
                log_func(text)

        try:
            gamma = float(gamma)
        except Exception:
            gamma = 1.0

        if gamma <= 0:
            gamma = 1.0

        group_to_indices = {}

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            key = SamplerProcessors.zone_play_area_key(model, zone)
            group_to_indices.setdefault(key, []).append(i)

        log("Velocity distribution: found {} zones in {} playback-area group(s).\n".format(
            model.zone_count(),
            len(group_to_indices)
        ))

        updated = 0
        groups = 0

        for key, indices in sorted(group_to_indices.items(), key=lambda item: item[0]):
            n = len(indices)
            log("  Area KeyRange {}-{}, SelectorRange {}-{}: {} zone(s): {}\n".format(
                key[0], key[1], key[2], key[3], n, indices
            ))

            if n > 1:
                groups += 1
            updated += SamplerProcessors.assign_velocity_ranges_in_order(
                model,
                indices,
                gamma=gamma,
                log_func=log_func,
            )

        if updated == 0:
            log("Velocity distribution: no playback-area group found, so nothing was changed.\n")
        else:
            log("Velocity distribution: updated {} zones across {} playback-area group(s). gamma={}\n".format(updated, groups, gamma))

        return updated

    @staticmethod
    def spread_velocity_ranges_for_count(count, gamma=1.0):
        if count <= 0:
            return []
        if count == 1:
            return [(1, 127)]

        try:
            gamma = float(gamma)
        except Exception:
            gamma = 1.0
        if gamma <= 0:
            gamma = 1.0

        boundaries = []
        for k in range(count + 1):
            x = k / float(count)
            y = pow(x, gamma)
            v = 1 + int(round(y * 127))
            v = max(1, min(128, v))
            boundaries.append(v)

        boundaries[0] = 1
        boundaries[-1] = 128

        for k in range(1, len(boundaries)):
            if boundaries[k] <= boundaries[k - 1]:
                boundaries[k] = min(128, boundaries[k - 1] + 1)

        boundaries[-1] = 128

        ranges = []
        for idx in range(count):
            mn = max(1, min(127, boundaries[idx]))
            mx = max(1, min(127, boundaries[idx + 1] - 1))
            if mn > mx:
                mn = mx
            ranges.append((mn, mx))
        return ranges

    @staticmethod
    def assign_velocity_ranges_in_order(model, ordered_indices, gamma=1.0, log_func=None, score_lookup=None):
        def log(text):
            if log_func:
                log_func(text)

        ranges = SamplerProcessors.spread_velocity_ranges_for_count(len(ordered_indices), gamma=gamma)
        updated = 0
        for zone_index, (mn, mx) in zip(ordered_indices, ranges):
            zone = model.get_zone(zone_index)
            vals = {
                "min": str(mn),
                "max": str(mx),
                "xfade_min": str(mn),
                "xfade_max": str(mx),
            }
            model.write_range(zone, "VelocityRange", vals)
            updated += 1
            if isinstance(zone, dict):
                root = zone.get("RootKey", "?")
            else:
                root = get_value(zone, "RootKey", "?")
            if score_lookup is None:
                log("    zone {} (RootKey {}) -> VelocityRange {}-{}\n".format(zone_index, root, mn, mx))
            else:
                log("    zone {} (RootKey {}, strength {:.6f}) -> VelocityRange {}-{}\n".format(zone_index, root, score_lookup.get(zone_index, 0.0), mn, mx))
        return updated

    @staticmethod
    def sort_velocity_by_play_area(model, audio_cache, gamma=1.0, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        group_to_entries = {}
        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            audio = audio_cache.get_zone_audio(model, zone)
            score = AudioAnalysis.estimate_note_strength(audio.samples, audio.sample_rate)
            key = SamplerProcessors.zone_play_area_key(model, zone)
            group_to_entries.setdefault(key, []).append((i, float(score)))

        log("Velocity sort: found {} zones in {} playback-area group(s).\n".format(
            model.zone_count(),
            len(group_to_entries),
        ))

        updated = 0
        groups = 0
        for key, entries in sorted(group_to_entries.items(), key=lambda item: item[0]):
            n = len(entries)
            log("  Area KeyRange {}-{}, SelectorRange {}-{}: {} zone(s)\n".format(
                key[0], key[1], key[2], key[3], n
            ))
            if n > 1:
                groups += 1
            ranked_entries = sorted(entries, key=lambda item: (item[1], item[0]))
            score_lookup = {zone_index: score for zone_index, score in ranked_entries}
            updated += SamplerProcessors.assign_velocity_ranges_in_order(
                model,
                [zone_index for zone_index, _score in ranked_entries],
                gamma=gamma,
                log_func=log_func,
                score_lookup=score_lookup,
            )

        if updated == 0:
            log("Velocity sort: no playback-area group found, so nothing was changed.\n")
        else:
            log("Velocity sort: updated {} zones across {} playback-area group(s). gamma={}\n".format(updated, groups, gamma))
        return updated

    @staticmethod
    def velocity_ranges_from_scores(scores):
        values = [float(v) for v in scores]
        n = len(values)
        if n == 0:
            return []
        if n == 1:
            return [(1, 127)]

        lo = min(values)
        hi = max(values)

        if hi - lo <= 1e-12:
            cutoffs = [k / float(n) for k in range(1, n)]
        else:
            normalized = [(value - lo) / float(hi - lo) for value in values]
            cutoffs = [
                0.5 * (normalized[k] + normalized[k + 1])
                for k in range(n - 1)
            ]

        starts = [1]
        for cutoff in cutoffs:
            starts.append(1 + int(round(cutoff * 127.0)))

        for idx in range(1, len(starts)):
            starts[idx] = max(starts[idx], starts[idx - 1] + 1)

        for idx in range(len(starts) - 2, 0, -1):
            starts[idx] = min(starts[idx], starts[idx + 1] - 1)

        starts[0] = 1
        starts[-1] = min(starts[-1], 127)

        ranges = []
        for idx, start in enumerate(starts):
            if idx == len(starts) - 1:
                end = 127
            else:
                end = starts[idx + 1] - 1
            start = max(1, min(127, int(start)))
            end = max(start, min(127, int(end)))
            ranges.append((start, end))

        return ranges

    @staticmethod
    def detect_velocity_by_play_area(model, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        group_to_entries = {}

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            audio = audio_cache.get_zone_audio(model, zone)
            score = AudioAnalysis.estimate_note_strength(audio.samples, audio.sample_rate)
            key = SamplerProcessors.zone_play_area_key(model, zone)
            group_to_entries.setdefault(key, []).append((i, float(score)))

        log("Velocity detection: found {} zones in {} playback-area group(s).\n".format(
            model.zone_count(),
            len(group_to_entries),
        ))

        updated = 0
        groups = 0

        for key, entries in sorted(group_to_entries.items(), key=lambda item: item[0]):
            n = len(entries)
            log("  Area KeyRange {}-{}, SelectorRange {}-{}: {} zone(s)\n".format(
                key[0], key[1], key[2], key[3], n
            ))

            if n > 1:
                groups += 1
            ranked_entries = sorted(entries, key=lambda item: (item[1], item[0]))
            ranges = SamplerProcessors.velocity_ranges_from_scores([score for _zone_index, score in ranked_entries])

            for (zone_index, score), (mn, mx) in zip(ranked_entries, ranges):
                zone = model.get_zone(zone_index)
                vals = {
                    "min": str(mn),
                    "max": str(mx),
                    "xfade_min": str(mn),
                    "xfade_max": str(mx),
                }
                model.write_range(zone, "VelocityRange", vals)
                updated += 1

                try:
                    root = get_value(zone, "RootKey", "?")
                except Exception:
                    root = "?"
                log(
                    "    zone {} (RootKey {}, strength {:.6f}) -> VelocityRange {}-{}\n".format(
                        zone_index,
                        root,
                        score,
                        mn,
                        mx,
                    )
                )

        if updated == 0:
            log("Velocity detection: no playback-area group found, so nothing was changed.\n")
        else:
            log("Velocity detection: updated {} zones across {} playback-area group(s).\n".format(updated, groups))

        return updated

    @staticmethod
    def chain_ranges_for_count(count):
        if count <= 0:
            return []
        if count == 1:
            return [(0, 127)]

        starts = []
        for idx in range(count):
            start = int(round((idx * 128.0) / float(count)))
            starts.append(max(0, min(127, start)))

        ranges = []
        for idx, start in enumerate(starts):
            end = 127 if idx == count - 1 else max(start, starts[idx + 1] - 1)
            ranges.append((start, min(127, end)))
        return ranges

    @staticmethod
    def chain_by_play_area(model, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        group_to_indices = {}
        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            key = SamplerProcessors.zone_chain_area_key(model, zone)
            group_to_indices.setdefault(key, []).append(i)

        updated = 0
        groups = 0
        log("Chain distribution: found {} zones in {} key/velocity group(s).\n".format(model.zone_count(), len(group_to_indices)))

        for key, indices in sorted(group_to_indices.items(), key=lambda item: item[0]):
            if len(indices) <= 1:
                continue
            groups += 1
            ranges = SamplerProcessors.chain_ranges_for_count(len(indices))
            log("  Area KeyRange {}-{}, VelocityRange {}-{}: {} zone(s): {}\n".format(
                key[0], key[1], key[2], key[3], len(indices), indices
            ))

            for zone_index, (mn, mx) in zip(indices, ranges):
                zone = model.get_zone(zone_index)
                vals = {
                    "min": str(mn),
                    "max": str(mx),
                    "xfade_min": str(mn),
                    "xfade_max": str(mx),
                }
                model.write_range(zone, "SelectorRange", vals)
                updated += 1
                log("    zone {} -> SelectorRange {}-{}\n".format(zone_index, mn, mx))

        if updated == 0:
            log("Chain distribution: no key/velocity group with multiple zones found, so nothing was changed.\n")
        else:
            log("Chain distribution: updated {} zones across {} key/velocity group(s).\n".format(updated, groups))

        return updated

    @staticmethod
    def auto_volume_velocity_scale(model, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        group_to_indices = {}
        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            key = SamplerProcessors.zone_play_area_key(model, zone)
            group_to_indices.setdefault(key, []).append(i)

        counts = [len(indices) for indices in group_to_indices.values() if len(indices) > 0]
        if not counts:
            log("Auto volume>velocity: no playback-area groups found.\n")
            return 0

        average_layers = float(sum(counts)) / float(len(counts))
        if average_layers <= 0:
            log("Auto volume>velocity: average layer count was zero.\n")
            return 0

        volume_vel_scale = max(0.0, min(1.0, 1.0 / average_layers))
        set_manual_value_by_path(model.root, "VolumeAndPan/VolumeVelScale", float_to_text(volume_vel_scale))
        log(
            "Auto volume>velocity: average layers per note = {:.2f}, set VolumeVelScale to {} ({:.1f}%).\n".format(
                average_layers,
                float_to_text(volume_vel_scale),
                volume_vel_scale * 100.0,
            )
        )
        return 1

    @staticmethod
    def zone_sort_value(model, zone, criterion):
        criterion = str(criterion or "none").strip().lower()
        if criterion in ("none", ""):
            return ()
        if criterion in ("keys", "key"):
            values = model.read_range(zone, "KeyRange")
            if isinstance(zone, dict):
                root_key_value = zone.get("RootKey", "0")
            else:
                root_key_value = get_value(zone, "RootKey", "0")
            return (
                clamp_int(values["min"], 0, 127),
                clamp_int(values["max"], 0, 127),
                clamp_int(root_key_value, 0, 127),
            )
        if criterion in ("velocity", "velo"):
            values = model.read_range(zone, "VelocityRange")
            return (
                clamp_int(values["min"], 1, 127),
                clamp_int(values["max"], 1, 127),
            )
        if criterion in ("chain", "selector"):
            values = model.read_range(zone, "SelectorRange")
            return (
                clamp_int(values["min"], 0, 127),
                clamp_int(values["max"], 0, 127),
            )
        if criterion in ("start timing in audio file", "start timing", "sample start", "start"):
            if isinstance(zone, dict):
                sample_start_value = zone.get("SampleStart", "0")
            else:
                sample_start_value = get_value(zone, "SampleStart", "0")
            return (int(parse_number_from_text(sample_start_value, 0)),)
        if criterion in ("file name", "filename", "file"):
            sample_path, relative_path = model.extract_sample_path(zone)
            candidate = sample_path or relative_path or get_value(zone, "Name", "")
            return (Path(str(candidate)).name.lower(),)
        return ()

    @staticmethod
    def sort_zones(model, params, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        criteria = [
            str(params.get("param_sort_zones_1", "none")).strip().lower(),
            str(params.get("param_sort_zones_2", "none")).strip().lower(),
            str(params.get("param_sort_zones_3", "none")).strip().lower(),
        ]
        criteria = [criterion for criterion in criteria if criterion not in ("", "none")]
        if not criteria:
            log("Sort zones: no criteria selected.\n")
            return 0

        ordered = list(range(model.zone_count()))

        def zone_sort_tuple(index):
            zone = model.get_zone(index)
            values = []
            for criterion in criteria:
                values.extend(SamplerProcessors.zone_sort_value(model, zone, criterion))
            values.append(index)
            return tuple(values)

        sorted_indices = sorted(ordered, key=zone_sort_tuple)
        if sorted_indices == ordered:
            log("Sort zones: order already matches {}.\n".format(", ".join(criteria)))
            return 0

        model.reorder_zones(sorted_indices)
        log("Sort zones: reordered {} zones by {}.\n".format(model.zone_count(), ", ".join(criteria)))
        return model.zone_count()

    @staticmethod
    def apply_range_crossfades(model, tag, amount_value, amount_unit, lo, hi, grouping_fields, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        amount_unit = str(amount_unit or "%").strip().lower()
        amount_value = max(0.0, float(amount_value))
        group_to_entries = {}

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            target_range = model.read_range(zone, tag)
            group_key = []
            for other_tag in grouping_fields:
                other_range = model.read_range(zone, other_tag)
                group_key.extend([other_range["min"], other_range["max"]])
            group_to_entries.setdefault(tuple(group_key), []).append(
                {
                    "index": i,
                    "orig_min": clamp_int(target_range["min"], lo, hi),
                    "orig_max": clamp_int(target_range["max"], lo, hi),
                }
            )

        updated = 0
        groups = 0

        for group_key, entries in sorted(group_to_entries.items(), key=lambda item: item[0]):
            entries.sort(key=lambda item: (item["orig_min"], item["orig_max"], item["index"]))
            if not entries:
                continue

            groups += 1
            for entry in entries:
                entry["new_min"] = entry["orig_min"]
                entry["new_max"] = entry["orig_max"]
                entry["xfade_min"] = entry["orig_min"]
                entry["xfade_max"] = entry["orig_max"]

            for left, right in zip(entries, entries[1:]):
                left_width = max(1, left["orig_max"] - left["orig_min"] + 1)
                right_width = max(1, right["orig_max"] - right["orig_min"] + 1)
                if amount_unit == "steps":
                    overlap = int(round(amount_value))
                else:
                    overlap = int(round(min(left_width, right_width) * max(0.0, min(100.0, amount_value)) / 100.0))
                if overlap <= 0:
                    continue

                left_extension = int(math.ceil(overlap / 2.0))
                right_extension = int(math.floor(overlap / 2.0))
                left["new_max"] = min(hi, max(left["new_max"], left["orig_max"] + left_extension))
                right["new_min"] = max(lo, min(right["new_min"], right["orig_min"] - right_extension))
                left["xfade_max"] = max(left["new_min"], min(left["new_max"], left["new_max"] - overlap))
                right["xfade_min"] = max(right["new_min"], min(right["new_max"], right["new_min"] + overlap))

            for entry in entries:
                zone = model.get_zone(entry["index"])
                previous = model.read_range(zone, tag)
                next_values = model.validate_range(
                    {
                        "min": str(entry["new_min"]),
                        "max": str(entry["new_max"]),
                        "xfade_min": str(entry["xfade_min"]),
                        "xfade_max": str(entry["xfade_max"]),
                    },
                    lo,
                    hi,
                )
                if next_values != previous:
                    model.write_range(zone, tag, next_values)
                    updated += 1
                    log(
                        "Zone crossfade: {} zone {} -> {}-{} core {}-{}\n".format(
                            tag,
                            entry["index"],
                            next_values["min"],
                            next_values["max"],
                            next_values["xfade_min"],
                            next_values["xfade_max"],
                        )
                    )

        log("Zone crossfade: updated {} {} range(s) across {} group(s).\n".format(updated, tag, groups))
        return updated

    @staticmethod
    def crossfade_between_zones(model, params, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        mode = str(params.get("param_zone_crossfade_mode", "none")).strip().lower()
        amount_value = parse_number_from_text(params.get("param_zone_crossfade_amount", "0"), 0.0)
        amount_unit = str(params.get("param_zone_crossfade_unit", "%")).strip().lower()
        if mode == "none":
            log("Zone crossfade: mode is none; skipped.\n")
            return 0

        mode_specs = {
            "notes": [("KeyRange", 0, 127, ("VelocityRange", "SelectorRange"))],
            "velo": [("VelocityRange", 1, 127, ("KeyRange", "SelectorRange"))],
            "chain": [("SelectorRange", 0, 127, ("KeyRange", "VelocityRange"))],
            "all": [
                ("KeyRange", 0, 127, ("VelocityRange", "SelectorRange")),
                ("VelocityRange", 1, 127, ("KeyRange", "SelectorRange")),
                ("SelectorRange", 0, 127, ("KeyRange", "VelocityRange")),
            ],
        }
        specs = mode_specs.get(mode)
        if specs is None:
            log("Zone crossfade: unknown mode {}; skipped.\n".format(mode))
            return 0

        total = 0
        for tag, lo, hi, grouping_fields in specs:
            total += SamplerProcessors.apply_range_crossfades(
                model,
                tag,
                amount_value,
                amount_unit,
                lo,
                hi,
                grouping_fields,
                log_func=log_func,
            )
        return total

    @staticmethod
    def detect_zone_loop_detunes(model, params, audio_cache, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        detect_sustain = bool(params.get("loop_detune_detection", False))
        detect_release = bool(params.get("release_loop_detune_detection", False))
        diapason_hz = parse_number_from_text(params.get("param_diapason_hz", DEFAULT_DIAPASON_HZ), 440.0)
        if not detect_sustain and not detect_release:
            return 0

        updated = 0
        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            audio = audio_cache.get_zone_audio(model, zone)
            fallback_root = clamp_int(parse_number_from_text(get_value(zone, "RootKey", "60"), 60), 0, 127)
            zone_changed = False

            for loop_tag, loop_label, enabled in (
                ("SustainLoop", "sustain", detect_sustain),
                ("ReleaseLoop", "release", detect_release),
            ):
                if not enabled:
                    continue
                loop_vals = model.read_loop(zone, loop_tag)
                loop_start = clamp_int(parse_number_from_text(loop_vals.get("start", audio.zone_start), audio.zone_start), audio.zone_start, audio.zone_end - 1)
                loop_end = audio.zone_end if loop_tag == "ReleaseLoop" else clamp_int(parse_number_from_text(loop_vals.get("end", audio.zone_end), audio.zone_end), loop_start + 1, audio.zone_end)
                loop_samples = audio.samples[loop_start - audio.zone_start:loop_end - audio.zone_start]
                if len(loop_samples) < 2:
                    continue

                info = AudioAnalysis.estimate_loop_detune_info(
                    audio.samples,
                    loop_samples,
                    audio.sample_rate,
                    fallback_root_key=fallback_root,
                    diapason_hz=diapason_hz,
                )
                if info is None:
                    log("Loop detune detection: could not estimate {} loop detune for {}.\n".format(loop_label, SamplerProcessors.zone_label(zone, i)))
                    continue

                detune_value = str(clamp_int(round(info["detune_cents"]), -1200, 1200))
                if str(loop_vals.get("detune", "")) != detune_value:
                    loop_vals["detune"] = detune_value
                    model.write_loop(zone, loop_tag, loop_vals)
                    zone_changed = True
                log(
                    "Loop detune detection: {} {} -> {} cents (target {:.2f} Hz, loop {:.2f} Hz, method={})\n".format(
                        SamplerProcessors.zone_label(zone, i),
                        loop_label,
                        detune_value,
                        info["target_hz"],
                        info["loop_hz"],
                        info["method"],
                    )
                )

            if zone_changed:
                updated += 1

        if updated == 0:
            log("Loop detune detection: no loop detune changed.\n")
        return updated

    @staticmethod
    def rewrite_relative_sample_paths(model, params, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        if model.source_path is None:
            raise RuntimeError("Cannot rewrite relative paths without a source ADV path.")

        adv_dir = model.source_path.parent
        updated = 0
        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            sample_path = model.resolve_sample_file(zone)
            try:
                relative_path = Path(sample_path).resolve().relative_to(adv_dir.resolve())
            except Exception:
                relative_path = os.path.relpath(str(sample_path), str(adv_dir))
            relative_text = str(relative_path).replace("\\", "/")
            old_abs, old_rel = model.extract_sample_path(zone)
            if old_rel == relative_text and old_abs == str(sample_path):
                continue
            model.set_zone_sample_reference(zone, absolute_path=str(sample_path), relative_path=relative_text)
            updated += 1
            log("Rewrote relative sample path for {} -> {}\n".format(SamplerProcessors.zone_label(zone, i), relative_text))

        if updated == 0:
            log("Relative path rewrite: no sample reference changed.\n")
        return updated

    @staticmethod
    def relink_samples_from_folder(model, params, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        folder_text = str(params.get("param_sample_relink_folder", "")).strip()
        if not folder_text:
            raise ValueError("Sample relink folder is empty.")
        folder = Path(folder_text)
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError("Sample relink folder not found: {}".format(folder))

        write_relative = bool(params.get("param_sample_relink_relative", True))
        indexed = {}
        for candidate in sorted(folder.rglob("*")):
            if not candidate.is_file():
                continue
            indexed.setdefault(candidate.name.lower(), []).append(candidate)

        updated = 0
        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            current_abs, current_rel = model.extract_sample_path(zone)
            basename = Path(current_abs or current_rel).name.lower()
            matches = indexed.get(basename, [])
            if not matches:
                log("Sample relink: no match for {} ({})\n".format(SamplerProcessors.zone_label(zone, i), basename))
                continue

            target = matches[0].resolve()
            relative_text = current_rel
            if write_relative and model.source_path is not None:
                relative_text = os.path.relpath(str(target), str(model.source_path.parent)).replace("\\", "/")
            if not write_relative:
                relative_text = ""

            if current_abs == str(target) and current_rel == relative_text:
                continue
            model.set_zone_sample_reference(zone, absolute_path=str(target), relative_path=relative_text)
            updated += 1
            log("Sample relink: {} -> {}\n".format(SamplerProcessors.zone_label(zone, i), target))

        if updated == 0:
            log("Sample relink: no sample reference changed.\n")
        return updated

    @staticmethod
    def copy_rename_relink_samples(model, params, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        target_folder_text = str(params.get("param_sample_copy_folder", "")).strip()
        if not target_folder_text:
            raise ValueError("Copy/rename target folder is empty.")
        target_folder = Path(target_folder_text)
        target_folder.mkdir(parents=True, exist_ok=True)

        pattern = str(params.get("param_sample_copy_pattern", "[sample]")).strip() or "[sample]"
        write_relative = bool(params.get("param_sample_copy_relative", True))
        user_name_node = find_first_value_node_by_tag(model.root, "UserName")
        preset_name_raw = model.multisampler.attrib.get("Name", "") if model.multisampler is not None else ""
        if not preset_name_raw and user_name_node is not None:
            preset_name_raw = user_name_node.attrib.get("Value", "")
        preset_name = sanitize_filename_component(preset_name_raw or "preset", "preset")
        source_to_dest = {}
        used_destinations = set()
        updated = 0

        for i in range(model.zone_count()):
            zone = model.get_zone(i)
            try:
                source_sample = model.resolve_sample_file(zone).resolve()
            except Exception as exc:
                log("Copy/rename: could not resolve sample for {} ({})\n".format(SamplerProcessors.zone_label(zone, i), exc))
                continue

            source_key = str(source_sample).lower()
            if source_key not in source_to_dest:
                sample_stem = sanitize_filename_component(source_sample.stem, "sample")
                zone_name = sanitize_filename_component(get_value(zone, "Name", "") or "zone", "zone")
                rendered = sanitize_filename_component(
                    render_name_pattern(
                        pattern,
                        {
                            "preset": preset_name,
                            "sample": sample_stem,
                            "zone": zone_name,
                            "idx": str(i + 1),
                        },
                    ),
                    sample_stem,
                )
                destination = target_folder / (rendered + source_sample.suffix)
                counter = 2
                while str(destination).lower() in used_destinations or (destination.exists() and destination.resolve() != source_sample):
                    destination = target_folder / ("{}_{}".format(rendered, counter) + source_sample.suffix)
                    counter += 1
                if destination.resolve() != source_sample:
                    shutil.copy2(source_sample, destination)
                used_destinations.add(str(destination).lower())
                source_to_dest[source_key] = destination.resolve()
                log("Copy/rename: {} -> {}\n".format(source_sample.name, destination.name))

            destination = source_to_dest[source_key]
            current_abs, current_rel = model.extract_sample_path(zone)
            relative_text = current_rel
            if write_relative and model.source_path is not None:
                relative_text = os.path.relpath(str(destination), str(model.source_path.parent)).replace("\\", "/")
            if not write_relative:
                relative_text = ""
            if current_abs == str(destination) and current_rel == relative_text:
                continue
            model.set_zone_sample_reference(zone, absolute_path=str(destination), relative_path=relative_text)
            updated += 1

        if updated == 0:
            log("Copy/rename/relink: no sample reference changed.\n")
        return updated

    @staticmethod
    def run_enabled_processors(model, selected_zone_index, global_values, processing_update, log_func=None):
        def log(text):
            if log_func:
                log_func(text)

        total_changes = 0
        audio_cache = None

        def require_audio_cache():
            nonlocal audio_cache
            if audio_cache is None:
                audio_cache = ZoneAudioCache()
                audio_cache.ensure_available()
            return audio_cache

        if processing_update.get("split_zones", False):
            mode = global_values.get("param_split_mode", "detect")

            if mode == "grid":
                total_changes += SamplerProcessors.split_all_zones_by_grid(
                    model,
                    global_values,
                    log_func=log_func
                )
                model.refresh()

            elif mode == "detection":
                total_changes += SamplerProcessors.split_all_zones_by_detection(
                    model,
                    global_values,
                    audio_cache=require_audio_cache(),
                    log_func=log_func,
                )
                model.refresh()
            elif mode in ("gate", "detect"):
                total_changes += SamplerProcessors.split_all_zones_by_gate(
                    model,
                    global_values,
                    audio_cache=require_audio_cache(),
                    log_func=log_func,
                )
                model.refresh()
            else:
                log("Unknown split mode; skipped.\n")

        if processing_update.get("pitch_detection_root", False) or processing_update.get("pitch_detection_detune", False):
            pitch_flags = dict(global_values)
            pitch_flags["pitch_detection_root"] = processing_update.get("pitch_detection_root", False)
            pitch_flags["pitch_detection_detune"] = processing_update.get("pitch_detection_detune", False)
            total_changes += SamplerProcessors.detect_zone_pitch(
                model,
                pitch_flags,
                audio_cache=require_audio_cache(),
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("filename_mapping", False):
            total_changes += SamplerProcessors.apply_filename_mapping(
                model,
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("spread_root", False):
            total_changes += SamplerProcessors.spread_key_zones(
                model,
                global_values,
                log_func=log_func
            )
            model.refresh()

        if processing_update.get("multiple_notes_case", False):
            mode = global_values.get("param_multiple_notes_mode", "layer")
            log("Multiple notes case: mode = {}\n".format(mode))

            if mode == "spread velocity":
                total_changes += SamplerProcessors.distribute_velocity_by_play_area(
                    model,
                    gamma=global_values.get("param_velocity_gamma", "1.0"),
                    log_func=log_func
                )
                model.refresh()

            elif mode == "layer":
                log("Multiple notes case: layer mode selected; no VelocityRange changes.\n")

            elif mode == "sort velocity":
                total_changes += SamplerProcessors.sort_velocity_by_play_area(
                    model,
                    audio_cache=require_audio_cache(),
                    gamma=global_values.get("param_velocity_gamma", "1.0"),
                    log_func=log_func,
                )
                model.refresh()

            elif mode == "detect velocity":
                total_changes += SamplerProcessors.detect_velocity_by_play_area(
                    model,
                    audio_cache=require_audio_cache(),
                    log_func=log_func,
                )
                model.refresh()

            elif mode == "chain":
                total_changes += SamplerProcessors.chain_by_play_area(
                    model,
                    log_func=log_func,
                )
                model.refresh()

            else:
                log("Multiple notes case: unknown mode; skipped.\n")

            if processing_update.get("auto_volume_vel_scale", False) and mode in ("spread velocity", "sort velocity", "detect velocity"):
                total_changes += SamplerProcessors.auto_volume_velocity_scale(
                    model,
                    log_func=log_func,
                )
                model.refresh()

        if processing_update.get("zone_crossfades", False):
            total_changes += SamplerProcessors.crossfade_between_zones(
                model,
                global_values,
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("sort_zones", False):
            total_changes += SamplerProcessors.sort_zones(
                model,
                global_values,
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("start_end_refine", False):
            total_changes += SamplerProcessors.refine_zone_bounds(
                model,
                global_values,
                audio_cache=require_audio_cache(),
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("normalize", False):
            total_changes += SamplerProcessors.normalize_zone_volumes(
                model,
                global_values,
                audio_cache=require_audio_cache(),
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("loop_detection", False) or processing_update.get("release_loop_detection", False):
            loop_flags = dict(global_values)
            loop_flags["loop_detection"] = processing_update.get("loop_detection", False)
            loop_flags["release_loop_detection"] = processing_update.get("release_loop_detection", False)
            total_changes += SamplerProcessors.detect_zone_loops(
                model,
                loop_flags,
                audio_cache=require_audio_cache(),
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("loop_detune_detection", False) or processing_update.get("release_loop_detune_detection", False):
            loop_detune_flags = dict(global_values)
            loop_detune_flags["loop_detune_detection"] = processing_update.get("loop_detune_detection", False)
            loop_detune_flags["release_loop_detune_detection"] = processing_update.get("release_loop_detune_detection", False)
            total_changes += SamplerProcessors.detect_zone_loop_detunes(
                model,
                loop_detune_flags,
                audio_cache=require_audio_cache(),
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("rewrite_sample_relative_paths", False):
            total_changes += SamplerProcessors.rewrite_relative_sample_paths(
                model,
                global_values,
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("relink_samples", False):
            total_changes += SamplerProcessors.relink_samples_from_folder(
                model,
                global_values,
                log_func=log_func,
            )
            model.refresh()

        if processing_update.get("rename_relink_samples", False):
            total_changes += SamplerProcessors.copy_rename_relink_samples(
                model,
                global_values,
                log_func=log_func,
            )
            model.refresh()

        return total_changes



# =============================================================================
# Tooltip helpers
# =============================================================================

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        self.after_id = None
        widget.bind("<Enter>", self.schedule)
        widget.bind("<Leave>", self.hide)
        widget.bind("<ButtonPress>", self.hide)

    def schedule(self, event=None):
        self.cancel()
        self.after_id = self.widget.after(500, self.show)

    def cancel(self):
        if self.after_id is not None:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def show(self):
        if self.tipwindow or not self.text:
            return

        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8

        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry("+%d+%d" % (x, y))

        label = tk.Label(
            tw,
            text=self.text,
            justify="left",
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            wraplength=360,
            padx=6,
            pady=4
        )
        label.pack()

    def hide(self, event=None):
        self.cancel()
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


def add_tooltip(widget, text):
    if text:
        ToolTip(widget, text)


# =============================================================================
# Scrollable frame
# =============================================================================

class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, width=None, height=None):
        ttk.Frame.__init__(self, parent)

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, width=width, height=height)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel_windows)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel_windows(self, event):
        x = self.canvas.winfo_pointerx()
        y = self.canvas.winfo_pointery()
        try:
            widget = self.canvas.winfo_containing(x, y)
        except Exception:
            return
        if widget is None:
            return
        widget_class = ""
        try:
            widget_class = str(widget.winfo_class() or "")
        except Exception:
            widget_class = ""
        if "Scale" in widget_class:
            return
        parent = widget
        while parent is not None:
            if parent == self or parent == self.canvas:
                delta = getattr(event, "delta", 0)
                if delta:
                    steps = int(-1 * (delta / 120))
                elif getattr(event, "num", None) == 4:
                    steps = -1
                elif getattr(event, "num", None) == 5:
                    steps = 1
                else:
                    steps = 0
                if steps:
                    self.canvas.yview_scroll(steps, "units")
                return
            parent = parent.master


# =============================================================================
# GUI
# =============================================================================

class SamplerAdvGui:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1260x900")

        self.adv_path = None
        self.model = None

        self.current_zone_index = None

        self.zone_vars = {}
        self.range_vars = {}
        self.loop_vars = {}
        self.global_vars = {}
        self.global_update = {}
        self.processing_update = {}
        self.visibility_rules = []
        self.waveform_cache = ZoneAudioCache()
        self.waveform_analysis_cache = {}
        self.waveform_refresh_after_id = None
        self.waveform_view_state = None
        self.dynamic_lfo_keys = []
        self.dynamic_filter_keys = []
        self.dynamic_aux_env_keys = []
        self.dynamic_pitch_env_keys = []
        self.dynamic_sub_osc_keys = []
        self.template_library_var = tk.StringVar(value="")
        self.template_comments_var = tk.StringVar(value="")
        self.template_library_paths = {}
        self._suspend_template_library_event = False

        self._build_ui()
        self.refresh_template_library(selected_path=DEFAULT_TOOL_TEMPLATE_PATH if DEFAULT_TOOL_TEMPLATE_PATH.exists() else None)
        self.apply_default_global_baseline()

        if DND_AVAILABLE:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self.on_drop)

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        file_frame = ttk.LabelFrame(main, text="ADV file")
        file_frame.pack(fill="x", pady=(0, 8))
        file_frame.columnconfigure(0, weight=1)

        self.path_var = tk.StringVar()
        file_row = ttk.Frame(file_frame)
        file_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        file_row.columnconfigure(0, weight=1)
        ttk.Entry(file_row, textvariable=self.path_var).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(file_row, text="New", command=self.new_empty_session).grid(row=0, column=1, padx=4)
        ttk.Button(file_row, text="Open...", command=self.open_file_dialog).grid(row=0, column=2, padx=4)
        ttk.Button(file_row, text="Export MIDI_test", command=self.export_midi_test_dialog).grid(row=0, column=3, padx=4)
        ttk.Button(file_row, text="Dump JSON", command=self.export_debug_json_dialog).grid(row=0, column=4, padx=4)
        ttk.Button(file_row, text="Log summary", command=self.log_current_summary).grid(row=0, column=5, padx=4)
        ttk.Button(file_row, text="Apply", command=self.apply_changes_only).grid(row=0, column=6, padx=4)
        ttk.Button(file_row, text="Save as...", command=self.save_current_as).grid(row=0, column=7, padx=4)
        ttk.Button(file_row, text="Overwrite + backup", command=self.overwrite_with_backup).grid(row=0, column=8, padx=(4, 0))

        template_row = ttk.Frame(file_frame)
        template_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        template_row.columnconfigure(5, weight=1)
        ttk.Label(template_row, text="Template").grid(row=0, column=0, sticky="w", padx=(0, 2))
        self.template_library_combo = ttk.Combobox(template_row, textvariable=self.template_library_var, state="readonly", width=24, values=[])
        self.template_library_combo.grid(row=0, column=1, sticky="w", padx=(0, 4))
        self.template_library_combo.bind("<<ComboboxSelected>>", self.on_template_library_selected)
        ttk.Button(template_row, text="Save template", command=self.save_template_dialog).grid(row=0, column=2, padx=4)
        ttk.Button(template_row, text="Load template", command=self.load_template_dialog).grid(row=0, column=3, padx=4)
        ttk.Label(template_row, text="Comments").grid(row=0, column=4, sticky="w", padx=(8, 4))
        ttk.Entry(template_row, textvariable=self.template_comments_var).grid(row=0, column=5, sticky="ew")

        hint = "Drag & drop .adv files here." if DND_AVAILABLE else "Drag & drop unavailable. Install tkinterdnd2 or use Open."
        self.status_var = tk.StringVar(value=hint)
        ttk.Label(main, textvariable=self.status_var).pack(fill="x", pady=(0, 8))

        waveform_frame = ttk.LabelFrame(main, text="Waveform")
        waveform_frame.pack(fill="x", pady=(0, 8))
        self.waveform_canvas = tk.Canvas(
            waveform_frame,
            height=180,
            background="#162028",
            highlightthickness=1,
            highlightbackground="#3e4b56"
        )
        self.waveform_canvas.pack(fill="x", padx=6, pady=6)
        self.waveform_canvas.bind("<Configure>", self.schedule_waveform_refresh)
        self.waveform_canvas.bind("<MouseWheel>", self.on_waveform_mousewheel)
        self.waveform_canvas.bind("<Button-4>", self.on_waveform_mousewheel)
        self.waveform_canvas.bind("<Button-5>", self.on_waveform_mousewheel)

        body = ttk.PanedWindow(main, orient="horizontal")
        body.pack(fill="both", expand=True)

        # LEFT COLUMN: zone list + per-zone settings
        left_column = ttk.Frame(body, width=310)
        left_column.pack_propagate(False)
        body.add(left_column, weight=1)

        zones_frame = ttk.LabelFrame(left_column, text="Zones")
        zones_frame.pack(fill="x", padx=(0, 8), pady=(0, 8))
        zones_frame.configure(width=220, height=185)
        zones_frame.pack_propagate(False)

        list_container = ttk.Frame(zones_frame)
        list_container.pack(fill="both", expand=True, padx=6, pady=6)

        self.zone_list = tk.Listbox(list_container, height=6, exportselection=False)
        zone_scroll = ttk.Scrollbar(list_container, orient="vertical", command=self.zone_list.yview)
        self.zone_list.configure(yscrollcommand=zone_scroll.set)
        self.zone_list.pack(side="left", fill="both", expand=True)
        zone_scroll.pack(side="right", fill="y")
        self.zone_list.bind("<<ListboxSelect>>", self.on_zone_select)

        ttk.Button(zones_frame, text="Delete selected zone", command=self.delete_selected_zone).pack(fill="x", padx=6, pady=(0, 6))

        per_zone_frame = ttk.LabelFrame(left_column, text="Per-zone settings")
        per_zone_frame.pack(fill="both", expand=True, padx=(0, 8))
        self.per_zone_scroll = ScrollableFrame(per_zone_frame, width=295)
        self.per_zone_scroll.pack(fill="both", expand=True, padx=4, pady=4)
        self._build_per_zone_panel(self.per_zone_scroll.inner)

        # RIGHT PANEL: global settings
        global_frame = ttk.LabelFrame(body, text="Global / processing settings")
        body.add(global_frame, weight=4)

        self.global_scroll = ScrollableFrame(global_frame)
        self.global_scroll.pack(fill="both", expand=True, padx=4, pady=4)
        self._build_global_panel(self.global_scroll.inner)

        for key in (
            "param_split_sensitivity",
            "param_split_profile_compression",
            "param_min_duration",
            "param_split_include_first_zone",
            "param_gate_sensitivity",
            "param_gate_profile_compression",
            "param_gate_stop_hysteresis_pct",
            "param_gate_start_placement",
            "param_gate_min_duration",
            "param_gate_include_first_zone",
            "param_split_mode",
            "param_grid_tempo",
            "param_grid_every_number",
            "param_grid_every_unit",
            "param_grid_end_after_number",
            "param_grid_end_after_unit",
        ):
            if key in self.global_vars:
                try:
                    self.global_vars[key].trace_add("write", self.schedule_waveform_refresh)
                except Exception:
                    pass

        for key in (
            "param_release_threshold",
            "param_release_tail_number",
            "param_release_tail_unit",
            "param_next_activity_threshold",
            "param_shift_start_number",
            "param_shift_start_unit",
            "param_shift_start_tempo",
            "param_shift_stop_number",
            "param_shift_stop_unit",
            "param_shift_stop_tempo",
            "param_diapason_hz",
            "param_pitch_window_start_number",
            "param_pitch_window_start_unit",
            "param_pitch_window_stop_number",
            "param_pitch_window_stop_unit",
            "param_sustain_loop_start_pct",
            "param_sustain_loop_start_unit",
            "param_sustain_loop_end_pct",
            "param_sustain_loop_end_unit",
            "param_sustain_loop_search_number",
            "param_sustain_loop_search_unit",
            "param_sustain_crossfade_policy",
            "param_sustain_crossfade_custom_number",
            "param_sustain_crossfade_custom_unit",
            "param_release_loop_start_reference",
            "param_release_loop_start_pct",
            "param_release_loop_start_unit",
            "param_release_loop_search_number",
            "param_release_loop_search_unit",
            "param_release_crossfade_policy",
            "param_release_crossfade_custom_number",
            "param_release_crossfade_custom_unit",
            "param_normalize_amount_pct",
            "param_multiple_notes_mode",
        ):
            if key in self.global_vars:
                try:
                    self.global_vars[key].trace_add("write", self.schedule_waveform_refresh)
                except Exception:
                    pass

        for key in (
            "split_zones",
            "start_end_refine",
            "loop_detection",
            "release_loop_detection",
            "loop_detune_detection",
            "release_loop_detune_detection",
            "pitch_detection_root",
            "pitch_detection_detune",
            "multiple_notes_case",
            "normalize",
        ):
            if key in self.processing_update:
                try:
                    self.processing_update[key].trace_add("write", self.schedule_waveform_refresh)
                except Exception:
                    pass

        for var in self.loop_vars.values():
            try:
                var.trace_add("write", self.schedule_waveform_refresh)
            except Exception:
                pass

        for key in ("sample_start", "sample_end"):
            if key in self.zone_vars:
                try:
                    self.zone_vars[key].trace_add("write", self.schedule_waveform_refresh)
                except Exception:
                    pass

        self.log = tk.Text(main, height=5)
        self.log.pack(fill="x", pady=(8, 0))
        self.log_insert("Ready.\n")
        self.schedule_waveform_refresh()

    def _entry_row(self, parent, row, label, key, store, checkbox_store=None, checkbox_key=None):
        if checkbox_store is not None:
            cb_key = checkbox_key or key
            var_cb = tk.BooleanVar(value=False)
            checkbox_store[cb_key] = var_cb
            ttk.Checkbutton(parent, variable=var_cb).grid(row=row, column=0, sticky="w", padx=(4, 0), pady=3)
            label_col = 1
            entry_col = 2
        else:
            label_col = 0
            entry_col = 1

        ttk.Label(parent, text=label).grid(row=row, column=label_col, sticky="w", padx=4, pady=3)
        var = tk.StringVar()
        store[key] = var
        ent = ttk.Entry(parent, textvariable=var)
        ent.grid(row=row, column=entry_col, sticky="ew", padx=4, pady=3)
        return var

    def _param_row(self, parent, row, label, key, default="", checkbox_store=None, checkbox_key=None, tooltip=""):
        if checkbox_store is not None:
            cb_key = checkbox_key or key
            var_cb = tk.BooleanVar(value=False)
            checkbox_store[cb_key] = var_cb
            cb = ttk.Checkbutton(parent, variable=var_cb)
            cb.grid(row=row, column=0, sticky="w", padx=(4, 0), pady=3)
            add_tooltip(cb, tooltip)
            label_col = 1
            entry_col = 2
        else:
            label_col = 0
            entry_col = 1

        lab = ttk.Label(parent, text=label)
        lab.grid(row=row, column=label_col, sticky="w", padx=4, pady=3)
        add_tooltip(lab, tooltip)

        var = tk.StringVar(value=default)
        self.global_vars[key] = var
        ent = ttk.Entry(parent, textvariable=var)
        ent.grid(row=row, column=entry_col, sticky="ew", padx=4, pady=3)
        add_tooltip(ent, tooltip)
        return var

    def _param_slider_row(self, parent, row, label, key, default="", slider_min=0.01, slider_max=0.99, tooltip=""):
        lab = ttk.Label(parent, text=label)
        lab.grid(row=row, column=0, sticky="w", padx=4, pady=3)
        add_tooltip(lab, tooltip)

        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=4, pady=3)
        frame.columnconfigure(1, weight=1)

        var = tk.StringVar(value=default)
        self.global_vars[key] = var
        slider_var = tk.DoubleVar(value=parse_number_from_text(default, slider_min))

        entry = ttk.Entry(frame, textvariable=var, width=8)
        entry.grid(row=0, column=0, sticky="w")
        add_tooltip(entry, tooltip)

        scale = ttk.Scale(frame, variable=slider_var, from_=slider_min, to=slider_max, orient="horizontal")
        scale.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        add_tooltip(scale, tooltip)

        self._suspend_slider_sync = getattr(self, "_suspend_slider_sync", False)

        def sync_from_slider(*_args):
            if getattr(self, "_suspend_slider_sync", False):
                return
            self._suspend_slider_sync = True
            try:
                var.set("{:.3f}".format(slider_var.get()))
            finally:
                self._suspend_slider_sync = False

        def sync_from_entry(*_args):
            if getattr(self, "_suspend_slider_sync", False):
                return
            value = parse_number_from_text(var.get(), slider_min)
            value = max(slider_min, min(slider_max, value))
            self._suspend_slider_sync = True
            try:
                slider_var.set(value)
            finally:
                self._suspend_slider_sync = False

        try:
            slider_var.trace_add("write", sync_from_slider)
        except Exception:
            pass
        try:
            var.trace_add("write", sync_from_entry)
        except Exception:
            pass

        def set_scale_from_event(event):
            width = max(1, scale.winfo_width())
            fraction = max(0.0, min(1.0, event.x / float(width)))
            value = slider_min + ((slider_max - slider_min) * fraction)
            slider_var.set(value)
            return "break"

        def nudge_scale(delta_steps):
            span = float(slider_max - slider_min)
            step = span / 100.0 if span > 0 else 0.01
            value = max(slider_min, min(slider_max, float(slider_var.get()) + (delta_steps * step)))
            slider_var.set(value)

        def on_scale_mousewheel(event):
            delta = 0
            if getattr(event, "num", None) == 4:
                delta = 1
            elif getattr(event, "num", None) == 5:
                delta = -1
            else:
                raw = getattr(event, "delta", 0)
                delta = 1 if raw > 0 else -1 if raw < 0 else 0
            if delta:
                nudge_scale(delta)
            return "break"

        scale.bind("<Button-1>", set_scale_from_event)
        scale.bind("<B1-Motion>", set_scale_from_event)
        scale.bind("<MouseWheel>", on_scale_mousewheel)
        scale.bind("<Button-4>", on_scale_mousewheel)
        scale.bind("<Button-5>", on_scale_mousewheel)
        sync_from_entry()
        return var

    def _choice_row(self, parent, row, label, key, choices, default=None, checkbox_store=None, checkbox_key=None, tooltip="", store=None):
        if default is None:
            default = choices[0] if choices else ""
        if store is None:
            store = self.global_vars

        if checkbox_store is not None:
            cb_key = checkbox_key or key
            var_cb = tk.BooleanVar(value=False)
            checkbox_store[cb_key] = var_cb
            cb = ttk.Checkbutton(parent, variable=var_cb)
            cb.grid(row=row, column=0, sticky="w", padx=(4, 0), pady=3)
            add_tooltip(cb, tooltip)
            label_col = 1
            entry_col = 2
        else:
            label_col = 0
            entry_col = 1

        lab = ttk.Label(parent, text=label)
        lab.grid(row=row, column=label_col, sticky="w", padx=4, pady=3)
        add_tooltip(lab, tooltip)

        var = tk.StringVar(value=default)
        store[key] = var
        combo = ttk.Combobox(parent, textvariable=var, values=choices, state="readonly")
        combo.grid(row=row, column=entry_col, sticky="ew", padx=4, pady=3)
        add_tooltip(combo, tooltip)
        return var

    def _checkbox_row(self, parent, row, label, key, store=None, enabled=True, tooltip="", command=None):
        if store is None:
            store = self.processing_update
        var = tk.BooleanVar(value=False)
        store[key] = var
        state = "normal" if enabled else "disabled"
        cb = ttk.Checkbutton(parent, text=label, variable=var, state=state, command=command)
        cb.grid(row=row, column=0, columnspan=3, sticky="w", padx=4, pady=2)
        add_tooltip(cb, tooltip)
        return var

    def _inline_params_row(self, parent, row, items, store=None, tooltip=""):
        if store is None:
            store = self.global_vars

        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=3)
        add_tooltip(frame, tooltip)

        for i, (label, key, default, width) in enumerate(items):
            lab = ttk.Label(frame, text=label)
            lab.pack(side="left", padx=(0 if i == 0 else 8, 2))
            add_tooltip(lab, tooltip)

            var = tk.StringVar(value=default)
            store[key] = var
            ent = ttk.Entry(frame, textvariable=var, width=width)
            ent.pack(side="left")
            add_tooltip(ent, tooltip)
        return frame

    def _build_default_preset_simple_sections(self, parent, start_row):
        row = start_row
        for section in DEFAULT_PRESET_SIMPLE_SECTIONS:
            self._section_label(parent, row, section["title"])
            row += 1
            for spec in section["fields"]:
                tooltip = spec.get("tooltip", "")
                if spec["kind"] == "bool":
                    self._bool_value_row(
                        parent,
                        row,
                        spec["label"],
                        spec["key"],
                        spec.get("default", False),
                        self.global_update,
                        spec["update"],
                        tooltip=tooltip,
                    )
                elif spec["kind"] == "choice":
                    self._choice_row(
                        parent,
                        row,
                        spec["label"],
                        spec["key"],
                        enum_choices(spec.get("enum_id")) or spec.get("choices", []),
                        spec.get("default", ""),
                        self.global_update,
                        spec["update"],
                        tooltip=tooltip,
                    )
                else:
                    self._param_row(
                        parent,
                        row,
                        spec["label"],
                        spec["key"],
                        spec.get("default", ""),
                        checkbox_store=self.global_update,
                        checkbox_key=spec["update"],
                        tooltip=tooltip,
                    )
                row += 1
        return row

    def _section_label(self, parent, row, text, columns=3):
        ttk.Label(parent, text=text, font=("", 10, "bold")).grid(row=row, column=0, columnspan=columns, sticky="w", pady=(10, 4))

    def _build_per_zone_panel(self, parent):
        parent.columnconfigure(1, weight=1)

        row = 0
        self._section_label(parent, row, "Basic zone values", columns=2)
        row += 1

        fields = [
            ("Name", "name"),
            ("Volume dB", "volume_db"),
            ("RootKey", "root_key"),
            ("Detune", "detune"),
            ("TuneScale", "tune_scale"),
            ("SampleStart", "sample_start"),
            ("SampleEnd", "sample_end"),
        ]
        for label, key in fields:
            self._entry_row(parent, row, label, key, self.zone_vars)
            row += 1

        self._section_label(parent, row, "Mapping ranges", columns=2)
        row += 1

        for label, prefix in [
            ("KeyRange", "key"),
            ("VelocityRange", "vel"),
            ("SelectorRange", "sel"),
        ]:
            ttk.Label(parent, text=label, font=("", 9, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 2))
            row += 1
            for sub in ("min", "max", "xfade_min", "xfade_max"):
                self._entry_row(parent, row, "  " + sub, prefix + "_" + sub, self.range_vars)
                row += 1

        self._section_label(parent, row, "Loops", columns=2)
        row += 1

        for label, prefix in [
            ("Sustain", "sustain"),
            ("Release", "release"),
        ]:
            ttk.Label(parent, text=label, font=("", 9, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 2))
            row += 1
            for sub in ("start", "end", "mode", "crossfade", "detune"):
                if sub == "mode":
                    choices = list(loop_mode_values_for_prefix(prefix).keys())
                    default_choice = "on"
                    self._choice_row(parent, row, "  " + sub, prefix + "_" + sub, choices, default_choice, store=self.loop_vars)
                else:
                    self._entry_row(parent, row, "  " + sub, prefix + "_" + sub, self.loop_vars)
                row += 1

        info = ttk.LabelFrame(parent, text="Current sample reference")
        info.grid(row=row, column=0, columnspan=2, sticky="ew", padx=4, pady=(12, 4))
        info.columnconfigure(1, weight=1)

        self.sample_path_var = tk.StringVar()
        self.relative_path_var = tk.StringVar()
        ttk.Label(info, text="Path").grid(row=0, column=0, sticky="nw", padx=4, pady=4)
        ttk.Label(info, textvariable=self.sample_path_var, wraplength=190).grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(info, text="Relative").grid(row=1, column=0, sticky="nw", padx=4, pady=4)
        ttk.Label(info, textvariable=self.relative_path_var, wraplength=190).grid(row=1, column=1, sticky="w", padx=4, pady=4)

    def _number_with_suffix_row(self, parent, row, label, key, default="", suffix="", tooltip=""):
        lab = ttk.Label(parent, text=label)
        lab.grid(row=row, column=0, sticky="w", padx=4, pady=3)
        add_tooltip(lab, tooltip)

        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, columnspan=2, sticky="w", padx=4, pady=3)

        var = tk.StringVar(value=default)
        self.global_vars[key] = var
        entry = ttk.Entry(frame, textvariable=var, width=12)
        entry.pack(side="left")
        add_tooltip(entry, tooltip)

        suffix_label = ttk.Label(frame, text=suffix, foreground="#666")
        suffix_label.pack(side="left", padx=(6, 0))
        add_tooltip(suffix_label, tooltip)

        return var

    def _number_unit_row(self, parent, row, label, number_key, unit_key, default_number, default_unit, units, tooltip=""):
        lab = ttk.Label(parent, text=label)
        lab.grid(row=row, column=0, sticky="w", padx=4, pady=3)
        add_tooltip(lab, tooltip)

        number_var = tk.StringVar(value=default_number)
        unit_var = tk.StringVar(value=default_unit)
        self.global_vars[number_key] = number_var
        self.global_vars[unit_key] = unit_var

        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=4, pady=3)

        entry = ttk.Entry(frame, textvariable=number_var, width=10)
        entry.pack(side="left")
        add_tooltip(entry, tooltip)

        combo = ttk.Combobox(frame, textvariable=unit_var, values=units, state="readonly", width=10)
        combo.pack(side="left", padx=(6, 0))
        add_tooltip(combo, tooltip)

        return number_var, unit_var

    def _number_unit_tempo_row(self, parent, row, label, number_key, unit_key, tempo_key, default_number, default_unit, default_tempo, units, tooltip=""):
        lab = ttk.Label(parent, text=label)
        lab.grid(row=row, column=0, sticky="w", padx=4, pady=3)
        add_tooltip(lab, tooltip)

        number_var = tk.StringVar(value=default_number)
        unit_var = tk.StringVar(value=default_unit)
        tempo_var = tk.StringVar(value=default_tempo)
        self.global_vars[number_key] = number_var
        self.global_vars[unit_key] = unit_var
        self.global_vars[tempo_key] = tempo_var

        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=4, pady=3)
        frame.columnconfigure(3, weight=1)

        entry = ttk.Entry(frame, textvariable=number_var, width=10)
        entry.grid(row=0, column=0, sticky="w")
        add_tooltip(entry, tooltip)

        combo = ttk.Combobox(frame, textvariable=unit_var, values=units, state="readonly", width=10)
        combo.grid(row=0, column=1, sticky="w", padx=(6, 0))
        add_tooltip(combo, tooltip)

        tempo_label = ttk.Label(frame, text="Tempo")
        tempo_label.grid(row=0, column=2, sticky="w", padx=(8, 2))
        add_tooltip(tempo_label, tooltip)

        tempo_entry = ttk.Entry(frame, textvariable=tempo_var, width=8)
        tempo_entry.grid(row=0, column=3, sticky="w")
        add_tooltip(tempo_entry, tooltip)

        def update_tempo_visibility(*_args):
            show_tempo = "beat" in unit_var.get().lower()
            if show_tempo:
                tempo_label.grid()
                tempo_entry.grid()
            else:
                tempo_label.grid_remove()
                tempo_entry.grid_remove()

        try:
            unit_var.trace_add("write", update_tempo_visibility)
        except Exception:
            pass
        update_tempo_visibility()

        return number_var, unit_var, tempo_var

    def _bool_value_row(self, parent, row, label, key, default=False, checkbox_store=None, checkbox_key=None, tooltip=""):
        cb_key = checkbox_key or key
        var_update = tk.BooleanVar(value=False)
        if checkbox_store is not None:
            checkbox_store[cb_key] = var_update
        ttk.Checkbutton(parent, variable=var_update).grid(row=row, column=0, sticky="w", padx=(4, 0), pady=3)

        lab = ttk.Label(parent, text=label)
        lab.grid(row=row, column=1, sticky="w", padx=4, pady=3)
        add_tooltip(lab, tooltip)

        value_var = tk.BooleanVar(value=default)
        self.global_vars[key] = value_var
        value_cb = ttk.Checkbutton(parent, text="On", variable=value_var)
        value_cb.grid(row=row, column=2, sticky="w", padx=4, pady=3)
        add_tooltip(value_cb, tooltip)
        return value_var

    def _bool_param_row(self, parent, row, label, key, default=False, store=None, tooltip=""):
        if store is None:
            store = self.global_vars

        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        value_var = tk.BooleanVar(value=default)
        store[key] = value_var
        value_cb = ttk.Checkbutton(parent, text="On", variable=value_var)
        value_cb.grid(row=row, column=1, columnspan=2, sticky="w", padx=4, pady=3)
        add_tooltip(value_cb, tooltip)
        return value_var

    def _checkbox_choice_row(self, parent, row, checkbox_label, checkbox_key, choice_label, choice_key, choices, default, tooltip=""):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=3)
        frame.columnconfigure(3, weight=1)

        cb_var = tk.BooleanVar(value=False)
        self.processing_update[checkbox_key] = cb_var
        cb = ttk.Checkbutton(frame, text=checkbox_label, variable=cb_var, command=self._set_split_mode_visibility)
        cb.grid(row=0, column=0, sticky="w")
        add_tooltip(cb, tooltip)

        lab = ttk.Label(frame, text=choice_label)
        lab.grid(row=0, column=1, sticky="w", padx=(12, 4))
        add_tooltip(lab, tooltip)

        choice_var = tk.StringVar(value=default)
        self.global_vars[choice_key] = choice_var
        combo = ttk.Combobox(frame, textvariable=choice_var, values=choices, state="readonly", width=12)
        combo.grid(row=0, column=2, sticky="w")
        combo.bind("<<ComboboxSelected>>", self._set_split_mode_visibility)
        add_tooltip(combo, tooltip)

        return cb_var, choice_var, frame, lab, combo

    def _register_visibility_rule(self, var, widget, predicate=None):
        if predicate is None:
            predicate = lambda value: bool(value)

        rule = {"var": var, "widget": widget, "predicate": predicate}
        self.visibility_rules.append(rule)

        def _callback(*_args):
            self._refresh_visibility_rules()

        try:
            var.trace_add("write", _callback)
        except Exception:
            pass

    def _refresh_visibility_rules(self):
        for rule in self.visibility_rules:
            widget = rule["widget"]
            try:
                visible = bool(rule["predicate"](rule["var"].get()))
            except Exception:
                visible = False

            try:
                if visible:
                    widget.grid()
                else:
                    widget.grid_remove()
            except Exception:
                pass
        self._refresh_pitch_detection_visibility()

    def _refresh_pitch_detection_visibility(self):
        frame = getattr(self, "pitch_detection_options_frame", None)
        if frame is None:
            return
        try:
            visible = bool(self.processing_update.get("pitch_detection_root", tk.BooleanVar(value=False)).get()) or bool(
                self.processing_update.get("pitch_detection_detune", tk.BooleanVar(value=False)).get()
            )
        except Exception:
            visible = False
        try:
            if visible:
                frame.grid()
            else:
                frame.grid_remove()
        except Exception:
            pass

    def _set_split_mode_visibility(self, *_args):
        if not hasattr(self, "split_mode_sections") or not hasattr(self, "split_mode_selector_frame"):
            return

        enabled_var = self.processing_update.get("split_zones")
        enabled = enabled_var.get() if enabled_var is not None else False

        mode_var = self.global_vars.get("param_split_mode")
        mode = mode_var.get() if mode_var is not None else "gate"
        if mode == "detection":
            mode = "gate"

        if enabled:
            self.split_mode_label.grid()
            self.split_mode_combo.grid()
        else:
            self.split_mode_label.grid_remove()
            self.split_mode_combo.grid_remove()

        for frame in self.split_mode_sections.values():
            frame.grid_remove()

        if not enabled:
            return

        if mode in ("detection", "gate", "detect"):
            self.split_mode_sections["gate"].grid()
        elif mode == "grid":
            self.split_mode_sections["grid"].grid()

    def _build_global_panel(self, parent):
        parent.columnconfigure(2, weight=1)

        row = 0

        # ZONES
        zone_box = ttk.LabelFrame(parent, text="ZONES")
        zone_box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=(4, 8))
        zone_box.columnconfigure(0, weight=1)
        zrow = 0

        ttk.Label(zone_box, text="Split into zones", font=("", 9, "bold")).grid(row=zrow, column=0, sticky="w", padx=4, pady=(6, 3))
        zrow += 1
        _split_cb, _split_mode, self.split_mode_selector_frame, self.split_mode_label, self.split_mode_combo = self._checkbox_choice_row(
            zone_box,
            zrow,
            "Enable split processing",
            "split_zones",
            "Mode",
            "param_split_mode",
            ["detect", "grid"],
            "detect",
            tooltip="Create several Sampler zones from every existing zone. detect: sustained-note level gating. grid: tempo-based positions."
        )
        zrow += 1

        self.split_mode_sections = {}

        detection_frame = ttk.Frame(zone_box)
        detection_frame.grid(row=zrow, column=0, sticky="ew", padx=0, pady=(4, 0))
        detection_frame.columnconfigure(1, weight=1)
        self.split_mode_sections["detection"] = detection_frame
        drow = 0

        self._param_slider_row(detection_frame, drow, "Trigger threshold", "param_split_sensitivity", DEFAULT_DETECTION_SPLIT_SENSITIVITY, 0.01, 0.99, tooltip="Relative threshold for attack-based split detection. Lower values catch weaker attacks; higher values keep only stronger attacks.")
        drow += 1
        self._param_slider_row(detection_frame, drow, "Linear -> log %", "param_split_profile_compression", DEFAULT_DETECTION_PROFILE_COMPRESSION, 0.0, 100.0, tooltip="0 = linear attack profile. 100 = log-compressed attack profile. Higher values help weaker triggers become reachable.")
        drow += 1
        self._number_with_suffix_row(detection_frame, drow, "Min duration", "param_min_duration", DEFAULT_DETECTION_SPLIT_MIN_DURATION, "samples", tooltip="Minimum slice length. Prevents very short accidental zones.")
        drow += 1
        include_first_zone_var = tk.BooleanVar(value=False)
        self.global_vars["param_split_include_first_zone"] = include_first_zone_var
        include_first_zone_cb = ttk.Checkbutton(detection_frame, text="Include first zone from start", variable=include_first_zone_var)
        include_first_zone_cb.grid(row=drow, column=0, columnspan=2, sticky="w", padx=4, pady=2)
        add_tooltip(include_first_zone_cb, "When enabled, detection mode creates an initial slice from the zone start to the first valid onset. When disabled, the first slice starts on the first valid onset.")
        zrow += 1

        gate_frame = ttk.Frame(zone_box)
        gate_frame.grid(row=zrow, column=0, sticky="ew", padx=0, pady=(4, 0))
        gate_frame.columnconfigure(1, weight=1)
        self.split_mode_sections["gate"] = gate_frame
        grow = 0

        self._param_slider_row(gate_frame, grow, "Start threshold", "param_gate_sensitivity", DEFAULT_GATE_SPLIT_SENSITIVITY, 0.01, 0.99, tooltip="Gate threshold used to enter a note region. Lower values catch quieter notes but can enter earlier in the note ramp-up.")
        grow += 1
        self._param_slider_row(gate_frame, grow, "Linear -> log %", "param_gate_profile_compression", DEFAULT_GATE_PROFILE_COMPRESSION, 0.0, 100.0, tooltip="0 = linear level envelope. 100 = log-compressed envelope. Higher values help quieter gated notes become reachable.")
        grow += 1
        self._param_slider_row(gate_frame, grow, "Stop hysteresis %", "param_gate_stop_hysteresis_pct", DEFAULT_GATE_STOP_HYSTERESIS_PCT, 1.0, 100.0, tooltip="Stop threshold as a percent of the start threshold. Lower values keep the note active longer through slow decays or internal motion.")
        grow += 1
        self._choice_row(gate_frame, grow, "Start placement", "param_gate_start_placement", ["local attack", "threshold"], DEFAULT_GATE_START_PLACEMENT, tooltip="Choose whether the written slice start stays at the threshold crossing or snaps forward to the strongest local attack inside the gated region.")
        grow += 1
        self._number_with_suffix_row(gate_frame, grow, "Min duration", "param_gate_min_duration", DEFAULT_GATE_SPLIT_MIN_DURATION, "samples", tooltip="Minimum slice length. Helps the gate ignore short internal dips or noise.")
        grow += 1
        include_first_gate_var = tk.BooleanVar(value=False)
        self.global_vars["param_gate_include_first_zone"] = include_first_gate_var
        include_first_gate_cb = ttk.Checkbutton(gate_frame, text="Include first zone from start", variable=include_first_gate_var)
        include_first_gate_cb.grid(row=grow, column=0, columnspan=2, sticky="w", padx=4, pady=2)
        add_tooltip(include_first_gate_cb, "When enabled, gate mode creates an initial slice from the zone start to the first valid gated note region. When disabled, the first slice starts on that first gated region.")
        zrow += 1

        grid_frame = ttk.Frame(zone_box)
        grid_frame.grid(row=zrow, column=0, sticky="ew", padx=0, pady=(4, 0))
        grid_frame.columnconfigure(1, weight=1)
        self.split_mode_sections["grid"] = grid_frame
        grow = 0

        self._number_with_suffix_row(grid_frame, grow, "Tempo", "param_grid_tempo", "100", "BPM", tooltip="Tempo used in grid mode. Decimal values are accepted.")
        grow += 1
        duration_units = ["beat(s)", "bar(s)"]
        self._number_unit_row(grid_frame, grow, "Start every", "param_grid_every_number", "param_grid_every_unit", "1", "bar(s)", duration_units, tooltip="Grid split spacing in tempo mode.")
        grow += 1
        self._number_unit_row(grid_frame, grow, "End after", "param_grid_end_after_number", "param_grid_end_after_unit", "3", "beat(s)", duration_units, tooltip="Default zone duration in grid mode.")
        zrow += 1

        row += 1

        # FOR EACH ZONE
        per_zone_box = ttk.LabelFrame(parent, text="FOR EACH ZONE")
        per_zone_box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=(4, 8))
        per_zone_box.columnconfigure(2, weight=1)
        prow = 0

        start_end_var = self._checkbox_row(per_zone_box, prow, "Start / End refinement", "start_end_refine", tooltip="Refine SampleStart and SampleEnd for each zone.", command=self._refresh_visibility_rules)
        prow += 1
        start_end_options = ttk.Frame(per_zone_box)
        start_end_options.grid(row=prow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        start_end_options.columnconfigure(2, weight=1)
        subrow = 0
        self._param_row(start_end_options, subrow, "Stop when release goes under threshold", "param_release_threshold", DEFAULT_REFINE_RELEASE_THRESHOLD, tooltip="Envelope threshold used to detect the effective end of each zone.")
        subrow += 1
        self._number_unit_row(
            start_end_options,
            subrow,
            "Tail margin",
            "param_release_tail_number",
            "param_release_tail_unit",
            DEFAULT_REFINE_TAIL_NUMBER,
            DEFAULT_REFINE_TAIL_UNIT,
            ["samples", "ms", "sec", "%"],
            tooltip="Extra margin kept after the first sustained quiet point, unless another activity starts first."
        )
        subrow += 1
        self._param_row(start_end_options, subrow, "Next activity threshold", "param_next_activity_threshold", DEFAULT_REFINE_NEXT_ACTIVITY_THRESHOLD, tooltip="Envelope threshold used to decide where the next activity starts. Stop is capped at that exact point; use Shift stop by to move it earlier or later.")
        subrow += 1
        self._number_unit_tempo_row(
            start_end_options,
            subrow,
            "Shift start by",
            "param_shift_start_number",
            "param_shift_start_unit",
            "param_shift_start_tempo",
            DEFAULT_REFINE_SHIFT_START_NUMBER,
            DEFAULT_REFINE_SHIFT_START_UNIT,
            DEFAULT_REFINE_SHIFT_START_TEMPO,
            ["samples", "ms", "sec", "%", "beat(s)"],
            tooltip="Offset applied after detection to move the refined start earlier or later."
        )
        subrow += 1
        self._number_unit_tempo_row(
            start_end_options,
            subrow,
            "Shift stop by",
            "param_shift_stop_number",
            "param_shift_stop_unit",
            "param_shift_stop_tempo",
            "0",
            "samples",
            "120",
            ["samples", "ms", "sec", "%", "beat(s)"],
            tooltip="Offset applied after detection."
        )
        self._register_visibility_rule(start_end_var, start_end_options)
        prow += 1

        normalize_var = self._checkbox_row(per_zone_box, prow, "Volume normalization", "normalize", tooltip="Normalize by changing Sampler zone volume, never the source WAV.")
        prow += 1
        normalize_options = ttk.Frame(per_zone_box)
        normalize_options.grid(row=prow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        normalize_options.columnconfigure(5, weight=1)
        ttk.Label(normalize_options, text="Use").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        normalize_mode_var = tk.StringVar(value="RMS")
        self.global_vars["param_normalize_mode"] = normalize_mode_var
        normalize_combo = ttk.Combobox(normalize_options, textvariable=normalize_mode_var, values=["RMS", "peak", "LUFS"], state="readonly", width=12)
        normalize_combo.grid(row=0, column=1, sticky="w", padx=4, pady=3)
        add_tooltip(normalize_combo, "Normalize each zone by RMS, peak, or approximate integrated LUFS.")
        ttk.Label(normalize_options, text="Amount").grid(row=0, column=2, sticky="w", padx=(12, 4), pady=3)
        normalize_amount_var = tk.StringVar(value="100")
        self.global_vars["param_normalize_amount_pct"] = normalize_amount_var
        normalize_amount_slider = tk.DoubleVar(value=100.0)
        normalize_amount_entry = ttk.Entry(normalize_options, textvariable=normalize_amount_var, width=6)
        normalize_amount_entry.grid(row=0, column=3, sticky="w", padx=(0, 6), pady=3)
        amount_scale = ttk.Scale(normalize_options, variable=normalize_amount_slider, from_=0.0, to=100.0, orient="horizontal")
        amount_scale.grid(row=0, column=4, columnspan=2, sticky="ew", padx=(0, 4), pady=3)
        add_tooltip(normalize_amount_entry, "0 keeps the current zone volume. 100 applies full normalization.")
        add_tooltip(amount_scale, "0 keeps the current zone volume. 100 applies full normalization.")

        def sync_norm_slider(*_args):
            if getattr(self, "_suspend_slider_sync", False):
                return
            self._suspend_slider_sync = True
            try:
                normalize_amount_var.set("{:.1f}".format(normalize_amount_slider.get()))
            finally:
                self._suspend_slider_sync = False

        def sync_norm_entry(*_args):
            if getattr(self, "_suspend_slider_sync", False):
                return
            value = max(0.0, min(100.0, parse_number_from_text(normalize_amount_var.get(), 100.0)))
            self._suspend_slider_sync = True
            try:
                normalize_amount_slider.set(value)
            finally:
                self._suspend_slider_sync = False

        normalize_amount_slider.trace_add("write", sync_norm_slider)
        normalize_amount_var.trace_add("write", sync_norm_entry)

        def set_norm_scale_from_event(event):
            width = max(1, amount_scale.winfo_width())
            normalize_amount_slider.set(max(0.0, min(100.0, (event.x / float(width)) * 100.0)))
            return "break"

        def on_norm_scale_mousewheel(event):
            delta = 0
            if getattr(event, "num", None) == 4:
                delta = 1
            elif getattr(event, "num", None) == 5:
                delta = -1
            else:
                raw = getattr(event, "delta", 0)
                delta = 1 if raw > 0 else -1 if raw < 0 else 0
            if delta:
                normalize_amount_slider.set(max(0.0, min(100.0, float(normalize_amount_slider.get()) + delta)))
            return "break"

        amount_scale.bind("<Button-1>", set_norm_scale_from_event)
        amount_scale.bind("<B1-Motion>", set_norm_scale_from_event)
        amount_scale.bind("<MouseWheel>", on_norm_scale_mousewheel)
        amount_scale.bind("<Button-4>", on_norm_scale_mousewheel)
        amount_scale.bind("<Button-5>", on_norm_scale_mousewheel)
        sync_norm_entry()
        self._register_visibility_rule(normalize_var, normalize_options)
        prow += 1

        loop_var = self._checkbox_row(per_zone_box, prow, "Loop", "loop_detection", tooltip="Detect sustain loop start/end from the current zone audio.", command=self._refresh_visibility_rules)
        prow += 1
        loop_options = ttk.Frame(per_zone_box)
        loop_options.grid(row=prow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        loop_options.columnconfigure(2, weight=1)
        subrow = 0
        self._number_unit_row(
            loop_options,
            subrow,
            "Start",
            "param_sustain_loop_start_pct",
            "param_sustain_loop_start_unit",
            "50",
            "%",
            ["%", "samples", "ms", "sec"],
            tooltip="Sustain loop start target inside the duration between zone start and stop."
        )
        subrow += 1
        self._number_unit_row(
            loop_options,
            subrow,
            "End",
            "param_sustain_loop_end_pct",
            "param_sustain_loop_end_unit",
            "75",
            "%",
            ["%", "samples", "ms", "sec"],
            tooltip="Sustain loop end target inside the duration between zone start and stop."
        )
        subrow += 1
        sustain_crossfade_policy_var = self._choice_row(
            loop_options,
            subrow,
            "Crossfade",
            "param_sustain_crossfade_policy",
            LOOP_CROSSFADE_POLICY_LABELS,
            "No fade",
            tooltip="Choose the sustain-loop fade behavior first, then search for the best loop points under that fade."
        )
        subrow += 1
        sustain_crossfade_custom = ttk.Frame(loop_options)
        sustain_crossfade_custom.grid(row=subrow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        sustain_crossfade_custom.columnconfigure(2, weight=1)
        self._number_unit_row(
            sustain_crossfade_custom,
            0,
            "Crossfade value",
            "param_sustain_crossfade_custom_number",
            "param_sustain_crossfade_custom_unit",
            "25",
            "%",
            ["%", "samples", "ms"],
            tooltip="Used only when Crossfade is set to Custom."
        )
        self._register_visibility_rule(
            sustain_crossfade_policy_var,
            sustain_crossfade_custom,
            predicate=lambda value: str(value).strip() == "Custom"
        )
        subrow += 1
        self._number_unit_row(
            loop_options,
            subrow,
            "Loop-point search range",
            "param_sustain_loop_search_number",
            "param_sustain_loop_search_unit",
            "25",
            "%",
            ["%", "samples", "ms"],
            tooltip="How far the sustain-loop search is allowed to move away from the target percentages while optimizing the seam."
        )
        subrow += 1
        self._choice_row(loop_options, subrow, "Type", "param_sustain_loop_mode", list(SUSTAIN_MODE_VALUES.keys()), "on", tooltip="Mode written to the sustain section when detection finds a usable result.")
        subrow += 1
        self._checkbox_row(loop_options, subrow, "Detect loop detunes", "loop_detune_detection", tooltip="Estimate sustain-loop detune from the looped audio itself and write the sustain loop Detune field.")
        subrow += 1
        self._register_visibility_rule(loop_var, loop_options)
        prow += 1

        release_loop_var = self._checkbox_row(per_zone_box, prow, "Release loop", "release_loop_detection", tooltip="Enable release-loop processing and preview. When active, the tool detects release-loop points from the stable tail after the played note has ended.", command=self._refresh_visibility_rules)
        prow += 1
        release_loop_options = ttk.Frame(per_zone_box)
        release_loop_options.grid(row=prow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        release_loop_options.columnconfigure(2, weight=1)
        subrow = 0
        self._choice_row(
            release_loop_options,
            subrow,
            "Based on",
            "param_release_loop_start_reference",
            ["start to end", "loop-end to end", "note-end to end"],
            "note-end to end",
            tooltip="Release-loop end is always the sample end. This chooses the span used to interpret the Start value."
        )
        subrow += 1
        self._number_unit_row(
            release_loop_options,
            subrow,
            "Start",
            "param_release_loop_start_pct",
            "param_release_loop_start_unit",
            "85",
            "%",
            ["%", "samples", "ms", "sec"],
            tooltip="Release-loop end is always the sample end. % is relative to the chosen base span, and signed values are allowed."
        )
        subrow += 1
        release_crossfade_policy_var = self._choice_row(
            release_loop_options,
            subrow,
            "Crossfade",
            "param_release_crossfade_policy",
            LOOP_CROSSFADE_POLICY_LABELS,
            "No fade",
            tooltip="Choose the release-loop fade behavior first, then search for the best loop points under that fade."
        )
        subrow += 1
        release_crossfade_custom = ttk.Frame(release_loop_options)
        release_crossfade_custom.grid(row=subrow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        release_crossfade_custom.columnconfigure(2, weight=1)
        self._number_unit_row(
            release_crossfade_custom,
            0,
            "Crossfade value",
            "param_release_crossfade_custom_number",
            "param_release_crossfade_custom_unit",
            "25",
            "%",
            ["%", "samples", "ms"],
            tooltip="Used only when Crossfade is set to Custom."
        )
        self._register_visibility_rule(
            release_crossfade_policy_var,
            release_crossfade_custom,
            predicate=lambda value: str(value).strip() == "Custom"
        )
        subrow += 1
        self._number_unit_row(
            release_loop_options,
            subrow,
            "Loop-point search range",
            "param_release_loop_search_number",
            "param_release_loop_search_unit",
            "10",
            "%",
            ["%", "samples", "ms"],
            tooltip="How far the release-loop search is allowed to move away from the target percentage while optimizing the seam."
        )
        subrow += 1
        self._choice_row(release_loop_options, subrow, "Release mode", "param_release_loop_mode", list(RELEASE_MODE_VALUES.keys()), "on", tooltip="Mode written to the release section when detection finds a usable result.")
        subrow += 1
        self._checkbox_row(release_loop_options, subrow, "Detect release loop detunes", "release_loop_detune_detection", tooltip="Estimate release-loop detune from the looped audio itself and write the release loop Detune field.")
        subrow += 1
        self._register_visibility_rule(release_loop_var, release_loop_options)
        prow += 1

        ttk.Label(per_zone_box, text="Pitch detection", font=("", 9, "bold")).grid(row=prow, column=0, columnspan=3, sticky="w", padx=4, pady=(8, 3))
        prow += 1
        self._checkbox_row(per_zone_box, prow, "Detect root note", "pitch_detection_root", tooltip="Estimate the zone pitch and write RootKey.", command=self._refresh_pitch_detection_visibility)
        prow += 1
        self._checkbox_row(per_zone_box, prow, "Detect detune", "pitch_detection_detune", tooltip="Estimate fine pitch and write zone detune in direct signed cents (-50 to +50). Positive values mean the sample is played sharper.", command=self._refresh_pitch_detection_visibility)
        prow += 1
        pitch_detection_options = ttk.Frame(per_zone_box)
        pitch_detection_options.grid(row=prow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        pitch_detection_options.columnconfigure(2, weight=1)
        self.pitch_detection_options_frame = pitch_detection_options
        subrow = 0
        self._param_row(pitch_detection_options, subrow, "Diapason Hz", "param_diapason_hz", DEFAULT_DIAPASON_HZ, tooltip="Reference tuning used to interpret detected pitch. 440 = standard A4. Raise or lower this if recordings are consistently sharp or flat.")
        subrow += 1
        self._number_unit_row(
            pitch_detection_options,
            subrow,
            "Tune window start",
            "param_pitch_window_start_number",
            "param_pitch_window_start_unit",
            DEFAULT_PITCH_WINDOW_START_NUMBER,
            DEFAULT_PITCH_WINDOW_START_UNIT,
            ["samples", "ms", "sec", "%"],
            tooltip="Start of the audio region used for pitch detection, measured inside each current zone or slice.",
        )
        subrow += 1
        self._number_unit_row(
            pitch_detection_options,
            subrow,
            "Tune window stop",
            "param_pitch_window_stop_number",
            "param_pitch_window_stop_unit",
            DEFAULT_PITCH_WINDOW_STOP_NUMBER,
            DEFAULT_PITCH_WINDOW_STOP_UNIT,
            ["samples", "ms", "sec", "%"],
            tooltip="End of the audio region used for pitch detection, measured inside each current zone or slice.",
        )
        prow += 1

        row += 1

        # MAPPING & PLAYBACK
        mapping_box = ttk.LabelFrame(parent, text="MAPPING & PLAYBACK")
        mapping_box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=(4, 8))
        mapping_box.columnconfigure(2, weight=1)
        mrow = 0

        spread_root_var = self._checkbox_row(mapping_box, mrow, "Spread key zones", "spread_root", tooltip="Assign KeyRange values from RootKey using the selected spread mode.")
        mrow += 1
        spread_root_options = ttk.Frame(mapping_box)
        spread_root_options.grid(row=mrow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        spread_root_options.columnconfigure(3, weight=1)
        self._choice_row(spread_root_options, 0, "Mode", "param_key_spread_mode", ["around root key", "spread evenly", "first note + interval"], "around root key", tooltip="around root key uses neighboring root midpoints. spread evenly fills a chosen key span evenly across the detected roots. first note + interval uses the current zone order and generates evenly spaced note centers from a chosen starting note.")
        spread_evenly_row = ttk.Frame(spread_root_options)
        spread_evenly_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        spread_evenly_row.columnconfigure(1, weight=1)
        self._param_row(spread_evenly_row, 0, "Min key", "param_key_spread_min", "0", tooltip="Lowest key used by the even spread mode.")
        self._param_row(spread_evenly_row, 1, "Max key", "param_key_spread_max", "127", tooltip="Highest key used by the even spread mode.")
        spread_interval_row = ttk.Frame(spread_root_options)
        spread_interval_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        spread_interval_row.columnconfigure(3, weight=1)
        self._param_row(spread_interval_row, 0, "First note", "param_key_spread_first_note", "0", tooltip="Starting MIDI note used by first note + interval mode.")
        self.key_spread_first_note_label_var = tk.StringVar(value=midi_key_to_note_label(0))
        ttk.Label(spread_interval_row, textvariable=self.key_spread_first_note_label_var).grid(row=0, column=2, sticky="w", padx=(0, 4), pady=3)
        self._param_row(spread_interval_row, 1, "Interval", "param_key_spread_interval", "1", tooltip="Distance in semitones between successive generated note centers.")
        self._param_row(spread_interval_row, 2, "n times", "param_key_spread_repeat_count", "1", tooltip="Repeat each generated note center this many consecutive zones before moving by the interval.")
        try:
            self.global_vars["param_key_spread_first_note"].trace_add("write", lambda *_args: self.update_key_spread_first_note_label())
        except Exception:
            pass
        self.update_key_spread_first_note_label()
        self._register_visibility_rule(spread_root_var, spread_root_options)
        self._register_visibility_rule(
            self.global_vars["param_key_spread_mode"],
            spread_evenly_row,
            predicate=lambda value: str(value).strip().lower() == "spread evenly",
        )
        self._register_visibility_rule(
            self.global_vars["param_key_spread_mode"],
            spread_interval_row,
            predicate=lambda value: str(value).strip().lower() == "first note + interval",
        )
        mrow += 1
        self._checkbox_row(mapping_box, mrow, "Set key / velo / chain / detune from filename", "filename_mapping", tooltip="Parse permissive filename tokens like P064 V110 C001 D050 from the sample filename or zone name, and write RootKey, VelocityRange, SelectorRange, and Detune directly.")
        mrow += 1
        multiple_notes_var = self._checkbox_row(mapping_box, mrow, "Multiple notes case", "multiple_notes_case", tooltip="How to handle several zones sharing the same playback area.")
        mrow += 1
        multiple_notes_options = ttk.Frame(mapping_box)
        multiple_notes_options.grid(row=mrow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        multiple_notes_options.columnconfigure(2, weight=1)
        self._choice_row(multiple_notes_options, 0, "Mode", "param_multiple_notes_mode", ["layer", "spread velocity", "sort velocity", "detect velocity", "chain"], "layer", tooltip="layer stacks without changing VelocityRange. spread velocity uses current order. sort velocity first sorts by measured loudness, then applies the same gamma spread. detect velocity derives the velocity boundaries directly from measured note strength. chain spreads SelectorRange across zones sharing the same key and velocity area.")
        gamma_row = ttk.Frame(multiple_notes_options)
        gamma_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        gamma_row.columnconfigure(1, weight=1)
        self._param_row(gamma_row, 0, "Gamma", "param_velocity_gamma", "1.0", tooltip="Non-linear velocity distribution for spread velocity. gamma < 1 gives lower velocities more range; gamma > 1 gives higher velocities more range.")
        auto_volume_vel_scale_row = ttk.Frame(multiple_notes_options)
        auto_volume_vel_scale_row.grid(row=2, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        auto_volume_vel_scale_var = self._checkbox_row(auto_volume_vel_scale_row, 0, "Auto Volume>Velocity %", "auto_volume_vel_scale", tooltip="Set VolumeVelScale automatically from the average number of velocity layers per note. Example: 4 layers per note -> 25%.")
        self._register_visibility_rule(multiple_notes_var, multiple_notes_options)
        self._register_visibility_rule(
            self.global_vars["param_multiple_notes_mode"],
            gamma_row,
            predicate=lambda value: str(value).strip().lower() in ("spread velocity", "sort velocity"),
        )
        self._register_visibility_rule(
            self.global_vars["param_multiple_notes_mode"],
            auto_volume_vel_scale_row,
            predicate=lambda value: str(value).strip().lower() in ("spread velocity", "sort velocity", "detect velocity"),
        )
        mrow += 1

        zone_crossfades_var = self._checkbox_row(mapping_box, mrow, "Crossfade between zones", "zone_crossfades", tooltip="Expand adjacent key, velocity, or selector ranges and keep the original edges as the fade core.")
        mrow += 1
        zone_crossfades_options = ttk.Frame(mapping_box)
        zone_crossfades_options.grid(row=mrow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        zone_crossfades_options.columnconfigure(2, weight=1)
        self._choice_row(zone_crossfades_options, 0, "Mode", "param_zone_crossfade_mode", ["none", "all", "notes", "velo", "chain"], "none", tooltip="Which range dimension receives crossfades.")
        zone_crossfade_amount_row = ttk.Frame(zone_crossfades_options)
        zone_crossfade_amount_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        zone_crossfade_amount_row.columnconfigure(1, weight=1)
        self._number_unit_row(zone_crossfade_amount_row, 0, "Amount", "param_zone_crossfade_amount", "param_zone_crossfade_unit", "0", "%", ["%", "steps"], tooltip="Crossfade amount as a percentage of the narrower adjacent zone width, or as an absolute number of steps in the chosen mapping dimension.")
        self._register_visibility_rule(zone_crossfades_var, zone_crossfades_options)
        self._register_visibility_rule(
            self.global_vars["param_zone_crossfade_mode"],
            zone_crossfade_amount_row,
            predicate=lambda value: str(value).strip().lower() != "none",
        )
        mrow += 1

        sort_zones_var = self._checkbox_row(mapping_box, mrow, "Sort zones", "sort_zones", tooltip="Reorder zones using up to three successive criteria.")
        mrow += 1
        sort_zones_options = ttk.Frame(mapping_box)
        sort_zones_options.grid(row=mrow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        sort_zones_options.columnconfigure(2, weight=1)
        sort_choices = ["none", "keys", "velocity", "chain", "file name", "start timing in audio file"]
        self._choice_row(sort_zones_options, 0, "By 1", "param_sort_zones_1", sort_choices, "keys", tooltip="Primary zone sort criterion.")
        self._choice_row(sort_zones_options, 1, "By 2", "param_sort_zones_2", sort_choices, "velocity", tooltip="Secondary zone sort criterion.")
        self._choice_row(sort_zones_options, 2, "By 3", "param_sort_zones_3", sort_choices, "chain", tooltip="Third zone sort criterion.")
        self._register_visibility_rule(sort_zones_var, sort_zones_options)
        mrow += 1

        row += 1

        # DEFAULT PRESET SETTINGS
        preset_box = ttk.LabelFrame(parent, text="DEFAULT PRESET SETTINGS")
        preset_box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=(4, 8))
        preset_box.columnconfigure(2, weight=1)
        drow = 0

        default_tune_scale_var = self._checkbox_row(preset_box, drow, "Tune scale", "default_tune_scale", store=self.global_update, tooltip="Write the same TuneScale value to every zone after any split, so newly created slices inherit it too.")
        drow += 1
        default_tune_scale_options = ttk.Frame(preset_box)
        default_tune_scale_options.grid(row=drow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        default_tune_scale_options.columnconfigure(2, weight=1)
        self._param_row(default_tune_scale_options, 0, "Value", "param_default_tune_scale", "100", tooltip="Sampler pitch scale / TuneScale value applied to all zones.")
        self._register_visibility_rule(default_tune_scale_var, default_tune_scale_options)
        drow += 1

        self._choice_row(
            preset_box,
            drow,
            "Voices",
            "voices",
            VOICE_COUNT_CHOICES,
            "14",
            self.global_update,
            "voices",
            tooltip="Maximum number of simultaneous voices."
        )
        drow += 1
        self._bool_value_row(preset_box, drow, "Round robin", "rr", True, self.global_update, "rr", tooltip="Enable or disable round robin playback.")
        drow += 1
        self._choice_row(
            preset_box,
            drow,
            "Round robin type",
            "rr_mode",
            list(ROUND_ROBIN_MODE_LABEL_TO_VALUE.keys()),
            "forward",
            self.global_update,
            "rr_mode",
            tooltip="Round robin playback order."
        )
        drow += 1
        self._choice_row(
            preset_box,
            drow,
            "Round robin reset",
            "rr_reset",
            list(ROUND_ROBIN_RESET_LABEL_TO_VALUE.keys()),
            "none",
            self.global_update,
            "rr_reset",
            tooltip="Reset period for round robin playback."
        )
        drow += 1
        self._entry_row(preset_box, drow, "Round robin seed", "rr_seed", self.global_vars, self.global_update, "rr_seed")
        drow += 1
        generic_lfo_var = self._checkbox_row(preset_box, drow, "LFO / routing parameters", "generic_lfo", store=self.global_update, tooltip="Expose the preset LFO Manual parameters and modulation-routing values directly, and synthesize missing LFO/routing blocks when needed.")
        drow += 1
        self.generic_lfo_frame = ttk.Frame(preset_box)
        self.generic_lfo_frame.grid(row=drow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        self.generic_lfo_frame.columnconfigure(0, weight=1)
        self._register_visibility_rule(generic_lfo_var, self.generic_lfo_frame)
        drow += 1

        planned_envelope_time_var = self._checkbox_row(preset_box, drow, "Envelope in ms", "planned_envelope_time", store=self.global_update, tooltip="Write the global amplitude-envelope timing values.")
        drow += 1
        planned_envelope_time_options = ttk.Frame(preset_box)
        planned_envelope_time_options.grid(row=drow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        planned_envelope_time_options.columnconfigure(2, weight=1)
        self._inline_params_row(planned_envelope_time_options, 0, [
            ("A", "param_env_attack_ms", "0.2", 7),
            ("D", "param_env_decay_ms", "1000", 7),
            ("S", "param_env_sustain", "1", 7),
            ("R", "param_env_release_ms", "20", 7),
        ], tooltip="Amplitude envelope values in ms except sustain level.")
        self._register_visibility_rule(planned_envelope_time_var, planned_envelope_time_options)
        drow += 1

        planned_envelope_shape_var = self._checkbox_row(preset_box, drow, "Envelope shape", "planned_envelope_shape", store=self.global_update, tooltip="Write the global amplitude-envelope slope values.")
        drow += 1
        planned_envelope_shape_options = ttk.Frame(preset_box)
        planned_envelope_shape_options.grid(row=drow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        planned_envelope_shape_options.columnconfigure(2, weight=1)
        self._inline_params_row(planned_envelope_shape_options, 0, [
            ("A %", "param_env_attack_shape", "0", 7),
            ("D %", "param_env_decay_shape", "0", 7),
            ("R %", "param_env_release_shape", "0", 7),
        ], tooltip="Envelope shape percentages.")
        self._register_visibility_rule(planned_envelope_shape_var, planned_envelope_shape_options)
        drow += 1

        generic_filter_var = self._checkbox_row(preset_box, drow, "Filter settings", "generic_filter", store=self.global_update, tooltip="Expose the preset filter and shaper parameters directly, and synthesize missing slot structures when needed.")
        drow += 1
        self.generic_filter_frame = ttk.Frame(preset_box)
        self.generic_filter_frame.grid(row=drow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        self.generic_filter_frame.columnconfigure(0, weight=1)
        self._register_visibility_rule(generic_filter_var, self.generic_filter_frame)
        drow += 1

        generic_aux_env_var = self._checkbox_row(preset_box, drow, "Aux envelope parameters", "generic_aux_env", store=self.global_update, tooltip="Expose aux envelope parameters directly, including modulation destinations, and synthesize the missing slot structure when needed.")
        drow += 1
        self.generic_aux_env_frame = ttk.Frame(preset_box)
        self.generic_aux_env_frame.grid(row=drow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        self.generic_aux_env_frame.columnconfigure(0, weight=1)
        self._register_visibility_rule(generic_aux_env_var, self.generic_aux_env_frame)
        drow += 1

        generic_pitch_env_var = self._checkbox_row(preset_box, drow, "Pitch envelope parameters", "generic_pitch_env", store=self.global_update, tooltip="Expose pitch envelope parameters directly and synthesize the missing slot structure when needed.")
        drow += 1
        self.generic_pitch_env_frame = ttk.Frame(preset_box)
        self.generic_pitch_env_frame.grid(row=drow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        self.generic_pitch_env_frame.columnconfigure(0, weight=1)
        self._register_visibility_rule(generic_pitch_env_var, self.generic_pitch_env_frame)
        drow += 1

        generic_sub_osc_var = self._checkbox_row(preset_box, drow, "Sub oscillator parameters", "generic_sub_osc", store=self.global_update, tooltip="Expose sub oscillator parameters directly and synthesize the missing slot structure when needed.")
        drow += 1
        self.generic_sub_osc_frame = ttk.Frame(preset_box)
        self.generic_sub_osc_frame.grid(row=drow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        self.generic_sub_osc_frame.columnconfigure(0, weight=1)
        self._register_visibility_rule(generic_sub_osc_var, self.generic_sub_osc_frame)
        drow += 1

        drow = self._build_default_preset_simple_sections(preset_box, drow)

        row += 1

        # FILE OPS
        file_ops_box = ttk.LabelFrame(parent, text="FILE OPS")
        file_ops_box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=(4, 8))
        file_ops_box.columnconfigure(2, weight=1)
        frow = 0

        planned_rename_zones_var = self._checkbox_row(file_ops_box, frow, "Rename zones", "planned_rename_zones", enabled=False, tooltip="Not implemented yet.")
        frow += 1
        planned_rename_zones_options = ttk.Frame(file_ops_box)
        planned_rename_zones_options.grid(row=frow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        planned_rename_zones_options.columnconfigure(2, weight=1)
        self._param_row(planned_rename_zones_options, 0, "Pattern", "param_zone_rename_pattern", "[note]_[vel]_[idx]", tooltip="Prepared for a future zone-rename workflow.")
        self._register_visibility_rule(planned_rename_zones_var, planned_rename_zones_options)
        frow += 1
        rewrite_rel_var = self._checkbox_row(file_ops_box, frow, "Rewrite relative sample paths", "rewrite_sample_relative_paths", tooltip="Recompute each zone RelativePath from the current sample location to the current ADV location.")
        frow += 1

        relink_samples_var = self._checkbox_row(file_ops_box, frow, "Relink samples from folder", "relink_samples", tooltip="Search a folder recursively by sample basename and relink matching zones.")
        frow += 1
        relink_samples_options = ttk.Frame(file_ops_box)
        relink_samples_options.grid(row=frow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        relink_samples_options.columnconfigure(2, weight=1)
        self._param_row(relink_samples_options, 0, "Folder", "param_sample_relink_folder", "", tooltip="Folder searched recursively for matching sample filenames.")
        self._bool_param_row(relink_samples_options, 1, "Write relative path", "param_sample_relink_relative", True, tooltip="Also rewrite RelativePath when relinking.")
        self._register_visibility_rule(relink_samples_var, relink_samples_options)
        frow += 1

        rename_samples_var = self._checkbox_row(file_ops_box, frow, "Copy / rename / relink samples", "rename_relink_samples", tooltip="Safely copy unique sample files into a target folder, rename them, and relink the preset to the copied files.")
        frow += 1
        rename_samples_options = ttk.Frame(file_ops_box)
        rename_samples_options.grid(row=frow, column=0, columnspan=3, sticky="ew", padx=0, pady=0)
        rename_samples_options.columnconfigure(2, weight=1)
        self._param_row(rename_samples_options, 0, "Folder", "param_sample_copy_folder", "", tooltip="Destination folder for copied and renamed sample files.")
        self._param_row(rename_samples_options, 1, "Pattern", "param_sample_copy_pattern", "[sample]", tooltip="Supported tokens: [preset], [sample], [zone], [idx]. One file is created per unique source sample.")
        self._bool_param_row(rename_samples_options, 2, "Write relative path", "param_sample_copy_relative", True, tooltip="Also rewrite RelativePath when relinking to the copied files.")
        self._register_visibility_rule(rename_samples_var, rename_samples_options)
        frow += 1

        row += 1

        # INFO
        info_box = ttk.LabelFrame(parent, text="INFO")
        info_box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=4, pady=(4, 8))
        info_box.columnconfigure(1, weight=1)
        irow = 0

        self.creator_var = tk.StringVar()
        self.zone_count_var = tk.StringVar()

        ttk.Label(info_box, text="Creator").grid(row=irow, column=0, sticky="w", padx=4, pady=3)
        ttk.Label(info_box, textvariable=self.creator_var, wraplength=620).grid(row=irow, column=1, sticky="w", padx=4, pady=3)
        irow += 1

        ttk.Label(info_box, text="Zone count").grid(row=irow, column=0, sticky="w", padx=4, pady=3)
        ttk.Label(info_box, textvariable=self.zone_count_var).grid(row=irow, column=1, sticky="w", padx=4, pady=3)

        self._set_split_mode_visibility()
        self._refresh_visibility_rules()

    # -------------------------------------------------------------------------
    # Template save/load
    # -------------------------------------------------------------------------

    def collect_template(self):
        return {
            "version": "1.6.0",
            "comments": self.template_comments_var.get(),
            "global_values": {k: v.get() for k, v in self.global_vars.items()},
            "global_update": {k: v.get() for k, v in self.global_update.items()},
            "processing_update": {k: v.get() for k, v in self.processing_update.items()},
        }

    def apply_default_global_baseline(self):
        if not DEFAULT_TOOL_TEMPLATE:
            return
        self.template_comments_var.set(str(DEFAULT_TOOL_TEMPLATE.get("comments", "")))
        for store_name, store in [
            ("global_values", self.global_vars),
            ("global_update", self.global_update),
            ("processing_update", self.processing_update),
        ]:
            values = DEFAULT_TOOL_TEMPLATE.get(store_name, {})
            for k, val in values.items():
                if k not in store:
                    continue
                if store_name == "global_values":
                    store[k].set(val)
                else:
                    store[k].set(bool(val))
        if "param_split_mode" in self.global_vars:
            split_mode = self.global_vars["param_split_mode"].get()
            if split_mode == "off":
                self.global_vars["param_split_mode"].set("detect")
                if "split_zones" in self.processing_update:
                    self.processing_update["split_zones"].set(False)
            elif split_mode in ("detection", "gate"):
                self.global_vars["param_split_mode"].set("detect")
        self._set_split_mode_visibility()
        self._refresh_visibility_rules()
        self.schedule_waveform_refresh()

    def refresh_template_library(self, selected_path=None):
        try:
            TEMPLATE_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        template_paths = sorted(TEMPLATE_LIBRARY_DIR.glob("*.json"), key=lambda p: p.name.lower())
        self.template_library_paths = {path.name: path for path in template_paths}

        values = [""] + [path.name for path in template_paths]
        if hasattr(self, "template_library_combo"):
            self._suspend_template_library_event = True
            try:
                self.template_library_combo["values"] = values
                if selected_path is not None:
                    try:
                        selected_resolved = Path(selected_path).resolve()
                    except Exception:
                        selected_resolved = Path(selected_path)
                    selected_name = next((path.name for path in template_paths if path.resolve() == selected_resolved), "")
                    self.template_library_var.set(selected_name)
                elif self.template_library_var.get() not in values:
                    self.template_library_var.set("")
            finally:
                self._suspend_template_library_event = False

    def load_template_path(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.apply_template(data)
        self.log_insert("Template loaded: {}\n".format(path))
        self.refresh_template_library(selected_path=path)

    def on_template_library_selected(self, _event=None):
        if self._suspend_template_library_event:
            return

        selected_name = self.template_library_var.get().strip()
        if not selected_name:
            return

        path = self.template_library_paths.get(selected_name)
        if path is None:
            self.refresh_template_library()
            return

        try:
            self.load_template_path(path)
            self.status_var.set("Template loaded: {}".format(selected_name))
        except Exception as e:
            self.show_error("Could not load template", e)

    def apply_template(self, data):
        self.template_comments_var.set(str(data.get("comments", "")))
        for store_name, store in [
            ("global_values", self.global_vars),
        ]:
            values = data.get(store_name, {})
            for k, val in values.items():
                if k in store:
                    store[k].set(val)

        for store_name, store in [
            ("global_update", self.global_update),
            ("processing_update", self.processing_update),
        ]:
            values = data.get(store_name, {})
            for k, val in values.items():
                if k in store:
                    store[k].set(bool(val))

        if "param_split_mode" in self.global_vars:
            split_mode = self.global_vars["param_split_mode"].get()
            if split_mode == "off":
                self.global_vars["param_split_mode"].set("detect")
                if "split_zones" in self.processing_update:
                    self.processing_update["split_zones"].set(False)
            elif split_mode in ("detection", "gate"):
                self.global_vars["param_split_mode"].set("detect")

        self._set_split_mode_visibility()
        self._refresh_visibility_rules()
        self.schedule_waveform_refresh()

    def save_template_dialog(self):
        path = filedialog.asksaveasfilename(
            title="Save processing template",
            initialdir=str(TEMPLATE_LIBRARY_DIR),
            defaultextension=".json",
            filetypes=[("JSON template", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            data = self.collect_template()
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log_insert("Template saved: {}\n".format(path))
            self.refresh_template_library(selected_path=path)
        except Exception as e:
            self.show_error("Could not save template", e)

    def load_template_dialog(self):
        path = filedialog.askopenfilename(
            title="Load processing template",
            initialdir=str(TEMPLATE_LIBRARY_DIR),
            filetypes=[("JSON template", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            self.load_template_path(path)
        except Exception as e:
            self.show_error("Could not load template", e)

    # -------------------------------------------------------------------------
    # Debug / dump tools
    # -------------------------------------------------------------------------

    def log_current_summary(self):
        if self.model is None:
            messagebox.showwarning("No file", "Open an .adv first.")
            return
        data = self.model.dump_summary()
        self.log_insert(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def export_debug_json_dialog(self):
        if self.model is None:
            messagebox.showwarning("No file", "Open an .adv first.")
            return

        default_name = "adv_debug_dump.json"
        if self.adv_path is not None:
            default_name = self.adv_path.stem + "_debug_dump.json"

        path = filedialog.asksaveasfilename(
            title="Export debug JSON",
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            data = self.model.dump_summary()
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log_insert("Debug JSON exported: {}\n".format(path))
        except Exception as e:
            self.show_error("Could not export debug JSON", e)

    def export_midi_test_dialog(self):
        if self.model is None:
            messagebox.showwarning("No file", "Open an .adv first.")
            return

        default_name = "MIDI_test.mid"
        if self.adv_path is not None:
            default_name = self.adv_path.stem + "_MIDI_test.mid"

        path = filedialog.asksaveasfilename(
            title="Export MIDI_test",
            initialfile=default_name,
            defaultextension=".mid",
            filetypes=[("MIDI file", "*.mid"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            plan_info = build_midi_test_plan(self.model, self.waveform_cache, tempo_bpm=100.0, selector_cc=1)
            plan_events = [dict(item, use_selector_cc=plan_info["use_selector_cc"]) for item in plan_info["events"]]
            midi_events = build_midi_test_events(plan_events, tempo_bpm=plan_info["tempo_bpm"], selector_cc=plan_info["selector_cc"])
            write_midi_file(path, midi_events, tempo_bpm=plan_info["tempo_bpm"], track_name="MIDI_test")
            self.log_insert(
                "MIDI_test exported: {} (tempo={} BPM, selector_cc={}, selector_used={}, events={})\n".format(
                    path,
                    int(plan_info["tempo_bpm"]),
                    plan_info["selector_cc"],
                    plan_info["use_selector_cc"],
                    len(plan_info["events"]),
                )
            )
            if plan_info["round_robin_random"]:
                self.log_insert("Warning: round robin mode is random, so identical trigger repeats cannot guarantee hearing each layer exactly once.\n")
        except Exception as e:
            self.show_error("Could not export MIDI_test", e)

    # -------------------------------------------------------------------------
    # File loading / saving
    # -------------------------------------------------------------------------

    def log_insert(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def open_file_dialog(self):
        path = filedialog.askopenfilename(
            title="Open Ableton Sampler ADV",
            filetypes=[("Ableton Device Preset", "*.adv"), ("All files", "*.*")]
        )
        if path:
            self.load_adv(Path(path))

    def dropped_paths_from_event(self, event):
        raw = str(event.data or "").strip()
        if not raw:
            return []
        try:
            parts = list(self.root.tk.splitlist(raw))
        except Exception:
            parts = [raw]
        cleaned = []
        for part in parts:
            text = str(part).strip()
            if text.startswith("{") and text.endswith("}"):
                text = text[1:-1]
            if text:
                cleaned.append(Path(text))
        return cleaned

    def on_drop(self, event):
        paths = self.dropped_paths_from_event(event)
        if not paths:
            return

        try:
            for path in paths:
                suffix = path.suffix.lower()
                if suffix == ".adv":
                    self.load_adv(path)
                elif path_looks_like_audio(path):
                    self.add_dropped_audio_file(path)
                else:
                    raise RuntimeError("Unsupported dropped file type: {}".format(path))
        except Exception as e:
            self.show_error("Could not handle dropped file", e)

    def load_adv(self, path):
        try:
            tree = AdvCodec.load(path)
            model = SamplerAdvModel(tree, source_path=path)

            self.adv_path = path
            self.model = model
            self.current_zone_index = None
            self.clear_waveform_caches(reset_audio=True)
            self.reset_waveform_view()
            self.rebuild_generic_lfo_fields()
            self.rebuild_generic_filter_fields()
            self.rebuild_generic_aux_env_fields()
            self.rebuild_generic_pitch_env_fields()
            self.rebuild_generic_sub_osc_fields()

            self.path_var.set(str(path))
            self.creator_var.set(model.creator())
            self.zone_count_var.set(str(model.zone_count()))

            self.refresh_zone_list()
            self.clear_zone_editor()
            self.load_global_settings()
            if model.zone_count() > 0:
                self.select_zone_index(0)

            self.status_var.set("Loaded: {} zones - {}".format(model.zone_count(), path.name))
            self.log_insert("Loaded: {}\n".format(path))
            self.log_insert("Zone count: {}\n".format(model.zone_count()))
        except Exception as e:
            self.show_error("Could not load ADV", e)

    def new_empty_session(self):
        self.model = None
        self.adv_path = None
        self.current_zone_index = None
        self.clear_waveform_caches(reset_audio=True)
        self.reset_waveform_view()
        self.path_var.set("")
        self.creator_var.set("")
        self.zone_count_var.set("0")
        self.refresh_zone_list()
        self.clear_zone_editor()
        self.apply_default_global_baseline()
        self.status_var.set("New empty session.")
        self.log_insert("Started new empty session.\n")

    def refresh_loaded_model_ui(self, source_label=None):
        if self.model is None:
            return
        self.clear_waveform_caches(reset_audio=False)
        if self.adv_path is not None:
            self.path_var.set(str(self.adv_path))
        else:
            self.path_var.set(source_label or "<unsaved>")
        self.creator_var.set(self.model.creator())
        self.zone_count_var.set(str(self.model.zone_count()))
        self.refresh_zone_list()
        self.clear_zone_editor()
        self.load_global_settings()
        if self.model.zone_count() > 0:
            self.select_zone_index(self.model.zone_count() - 1)

    def update_key_spread_first_note_label(self):
        if not hasattr(self, "key_spread_first_note_label_var"):
            return
        raw = self.global_vars.get("param_key_spread_first_note")
        value = raw.get() if raw is not None else "0"
        midi_note = clamp_int(parse_number_from_text(value, 0), 0, 127)
        self.key_spread_first_note_label_var.set(midi_key_to_note_label(midi_note))

    def configure_zone_for_audio_file(self, zone, audio_path, zone_name=None):
        audio_path = Path(audio_path).resolve()
        sample_count, sample_rate = read_audio_file_metadata(audio_path)
        zone_name = zone_name or audio_path.stem

        set_value(zone, "Name", zone_name)
        set_value(zone, "SampleStart", 0)
        set_value(zone, "SampleEnd", sample_count)
        set_value(zone, "RootKey", 60)
        set_value(zone, "Detune", 0)
        set_value(zone, "TuneScale", 100)
        set_value_if_exists(zone, "Panorama", 0)
        set_value_if_exists(zone, "Volume", "1.00000000")

        for range_tag, defaults in (
            ("KeyRange", {"Min": "0", "Max": "127", "CrossfadeMin": "0", "CrossfadeMax": "127"}),
            ("VelocityRange", {"Min": "1", "Max": "127", "CrossfadeMin": "1", "CrossfadeMax": "127"}),
            ("SelectorRange", {"Min": "0", "Max": "127", "CrossfadeMin": "0", "CrossfadeMax": "127"}),
        ):
            range_node = child(zone, range_tag)
            if range_node is not None:
                for key, value in defaults.items():
                    set_value_if_exists(range_node, key, value)

        for loop_tag in ("SustainLoop", "ReleaseLoop"):
            loop_node = child(zone, loop_tag)
            if loop_node is not None:
                set_value_if_exists(loop_node, "Start", 0)
                set_value_if_exists(loop_node, "End", sample_count)
                set_value_if_exists(loop_node, "Mode", 0)
                set_value_if_exists(loop_node, "Crossfade", 0)
                set_value_if_exists(loop_node, "Detune", 0)

        relative_path = audio_path.name
        if self.adv_path is not None:
            relative_path = os.path.relpath(str(audio_path), str(self.adv_path.parent)).replace("\\", "/")
        elif self.model is not None and self.model.source_path is not None:
            relative_path = os.path.relpath(str(audio_path), str(self.model.source_path.parent)).replace("\\", "/")

        self.model.set_zone_sample_reference(
            zone,
            absolute_path=str(audio_path),
            relative_path=relative_path,
            relative_path_type="6",
        )

        sample_ref = child(zone, "SampleRef")
        if sample_ref is not None:
            set_value_if_exists(sample_ref, "DefaultDuration", sample_count)
            set_value_if_exists(sample_ref, "DefaultSampleRate", sample_rate)
            set_value_if_exists(sample_ref, "SamplesToAutoWarp", 1)
            set_value_if_exists(sample_ref, "LastModDate", int(audio_path.stat().st_mtime))
            file_ref = self.model.sample_file_ref(zone)
            if file_ref is not None:
                set_value_if_exists(file_ref, "OriginalFileSize", int(audio_path.stat().st_size))
                set_value_if_exists(file_ref, "OriginalCrc", 0)
                set_value_if_exists(file_ref, "SourceHint", "")

    def create_model_from_audio_file(self, audio_path):
        tree = AdvCodec.load_default_scaffold()
        model = SamplerAdvModel(tree, source_path=None)
        apply_hardcoded_scratch_preset_defaults(model)
        if model.zone_count() == 0:
            raise RuntimeError("Default ADV scaffold does not contain a usable zone template.")
        zone = model.get_zone(0)
        self.model = model
        self.adv_path = None
        user_name_node = find_first_value_node_by_tag(model.root, "UserName")
        if user_name_node is not None:
            user_name_node.set("Value", audio_path.stem)
        self.configure_zone_for_audio_file(zone, audio_path, zone_name=audio_path.stem)
        model.refresh()

    def append_audio_zone_to_model(self, audio_path):
        if self.model is None or self.model.zone_count() == 0:
            self.create_model_from_audio_file(audio_path)
            return

        template_index = self.current_zone_index if self.current_zone_index is not None else 0
        template_zone = copy.deepcopy(self.model.get_zone(template_index))
        self.model.set_zone_id(template_zone, self.model.next_zone_id())
        self.configure_zone_for_audio_file(template_zone, audio_path, zone_name=audio_path.stem)
        self.model.append_zone(template_zone)

    def add_dropped_audio_file(self, audio_path):
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError("Dropped audio file not found: {}".format(audio_path))

        self.append_audio_zone_to_model(audio_path)
        self.reset_waveform_view()
        self.refresh_loaded_model_ui(source_label="<unsaved from audio>")
        self.status_var.set("Loaded audio as zone: {}".format(audio_path.name))
        self.log_insert("Loaded audio as zone: {}\n".format(audio_path))

    def save_adv(self, path):
        AdvCodec.write(self.model.tree, path)
        self.model.source_path = Path(path)
        self.status_var.set("Saved: {}".format(path))
        self.log_insert("Saved: {}\n".format(path))

    def apply_all_pending_changes(self):
        """
        Apply all currently supported GUI edits to the in-memory XML tree.

        Current behavior:
        - selected-zone manual values are applied if a zone is selected
        - structural and audio processors run next
        - global values are applied last
        """
        if self.current_zone_index is not None:
            self.apply_current_zone_to_xml()

        global_values = self.collect_global_values()
        processing_flags = {k: v.get() for k, v in self.processing_update.items()}
        self.status_var.set("Processing...")

        total_changes = SamplerProcessors.run_enabled_processors(
            self.model,
            self.current_zone_index,
            global_values,
            processing_flags,
            log_func=self.log_insert,
        )

        self.apply_global_settings_to_xml()

        # The model may have changed structurally.
        self.model.refresh()
        self.clear_waveform_caches(reset_audio=False)
        self.refresh_zone_list()
        self.zone_count_var.set(str(self.model.zone_count()))
        if self.model.zone_count() > 0:
            if self.current_zone_index is None:
                self.select_zone_index(0)
            else:
                self.select_zone_index(min(self.current_zone_index, self.model.zone_count() - 1))
        else:
            self.current_zone_index = None
            self.clear_zone_editor()

        enabled_processing = SamplerProcessors.enabled_processing_flags(self.processing_update)
        if enabled_processing:
            self.log_insert("Enabled processing flags: {}\n".format(", ".join(enabled_processing)))
        self.log_insert("Processing summary: {} change(s).\n".format(total_changes))
        if self.adv_path is not None:
            self.status_var.set("Processed {} zone(s) from {}".format(self.model.zone_count(), self.adv_path.name))

    def apply_changes_only(self):
        if self.model is None:
            messagebox.showwarning("No file", "Open an .adv or drop an audio file first.")
            return

        try:
            self.apply_all_pending_changes()
            messagebox.showinfo("Done", "Applied changes in memory.")
        except Exception as e:
            self.show_error("Could not apply changes", e)

    def save_current_as(self):
        if self.model is None:
            messagebox.showwarning("No file", "Open an .adv or drop an audio file first.")
            return

        default_name = "untitled_processed.adv"
        if self.adv_path is not None:
            default_name = self.adv_path.stem + "_processed.adv"
        else:
            user_name_node = find_first_value_node_by_tag(self.model.root, "UserName")
            if user_name_node is not None:
                raw_name = user_name_node.attrib.get("Value", "").strip()
                if raw_name:
                    default_name = sanitize_filename_component(raw_name, "untitled") + ".adv"
        out_path = filedialog.asksaveasfilename(
            title="Apply and save ADV as",
            initialfile=default_name,
            defaultextension=".adv",
            filetypes=[("Ableton Device Preset", "*.adv"), ("All files", "*.*")]
        )
        if not out_path:
            return

        try:
            out_path = Path(out_path)
            self.save_adv(out_path)
            self.adv_path = out_path
            self.path_var.set(str(out_path))
            messagebox.showinfo("Done", "Saved:\n{}".format(out_path))
        except Exception as e:
            self.show_error("Could not save as", e)

    def overwrite_with_backup(self):
        if self.model is None or self.adv_path is None:
            messagebox.showwarning("No file", "Open an .adv first.")
            return

        try:
            backup_dir = self.adv_path.parent / "_adv_backups"
            backup_dir.mkdir(exist_ok=True)

            backup_path = backup_dir / self.adv_path.name
            counter = 1
            while backup_path.exists():
                backup_path = backup_dir / (self.adv_path.stem + "_" + str(counter) + self.adv_path.suffix)
                counter += 1

            shutil.copy2(self.adv_path, backup_path)
            self.save_adv(self.adv_path)

            self.log_insert("Backup written: {}\n".format(backup_path))
            messagebox.showinfo("Done", "Wrote backup and overwrote:\n{}".format(self.adv_path))

        except Exception as e:
            self.show_error("Could not overwrite", e)

    def delete_selected_zone(self):
        if self.model is None or self.current_zone_index is None:
            messagebox.showwarning("No zone", "Select a zone first.")
            return

        try:
            removed_index = int(self.current_zone_index)
            self.model.delete_zone(removed_index)
            self.clear_waveform_caches(reset_audio=False)
            self.refresh_zone_list()
            self.zone_count_var.set(str(self.model.zone_count()))
            if self.model.zone_count() > 0:
                self.select_zone_index(min(removed_index, self.model.zone_count() - 1))
            else:
                self.current_zone_index = None
                self.clear_zone_editor()
            self.log_insert("Deleted zone: {}\n".format(removed_index))
            self.status_var.set("Deleted zone {}".format(removed_index))
        except Exception as e:
            self.show_error("Could not delete zone", e)

    # -------------------------------------------------------------------------
    # Zone UI
    # -------------------------------------------------------------------------

    def refresh_zone_list(self):
        self.zone_list.delete(0, "end")
        if self.model is None:
            return
        for i in range(self.model.zone_count()):
            summary = self.model.read_zone_summary(i)
            self.zone_list.insert("end", "{} - {}".format(i, summary["name"]))

    def select_zone_index(self, index):
        if self.model is None or self.model.zone_count() == 0:
            self.current_zone_index = None
            self.zone_list.selection_clear(0, "end")
            self.clear_zone_editor()
            self.schedule_waveform_refresh()
            return

        index = max(0, min(int(index), self.model.zone_count() - 1))
        self.current_zone_index = index
        self.reset_waveform_view()
        self.zone_list.selection_clear(0, "end")
        self.zone_list.selection_set(index)
        self.zone_list.see(index)
        self.load_zone_into_editor(index)

    def clear_zone_editor(self):
        for store in (self.zone_vars, self.range_vars, self.loop_vars):
            for var in store.values():
                var.set("")
        self.sample_path_var.set("")
        self.relative_path_var.set("")
        self.reset_waveform_view()
        self.schedule_waveform_refresh()

    def on_zone_select(self, event=None):
        selected = self.zone_list.curselection()
        if not selected:
            self.current_zone_index = None
            self.schedule_waveform_refresh()
            return
        self.select_zone_index(int(selected[0]))

    def load_zone_into_editor(self, index):
        z = self.model.get_zone(index)
        summary = self.model.read_zone_summary(index)

        self.zone_vars["name"].set(summary["name"])
        self.zone_vars["volume_db"].set("{:.4f}".format(summary["volume_db"]))
        self.zone_vars["root_key"].set(summary["root_key"])
        self.zone_vars["detune"].set(summary["detune"])
        self.zone_vars["tune_scale"].set(summary["tune_scale"])
        self.zone_vars["sample_start"].set(summary["sample_start"])
        self.zone_vars["sample_end"].set(summary["sample_end"])

        for source_key, prefix in [
            ("key_range", "key"),
            ("velocity_range", "vel"),
            ("selector_range", "sel"),
        ]:
            vals = summary[source_key]
            for sub in ("min", "max", "xfade_min", "xfade_max"):
                self.range_vars[prefix + "_" + sub].set(vals[sub])

        for source_key, prefix in [
            ("sustain_loop", "sustain"),
            ("release_loop", "release"),
        ]:
            vals = summary[source_key]
            for sub in ("start", "end", "mode", "crossfade", "detune"):
                if sub == "mode":
                    self.loop_vars[prefix + "_" + sub].set(loop_mode_label_from_value(prefix, vals[sub]))
                else:
                    self.loop_vars[prefix + "_" + sub].set(vals[sub])

        self.sample_path_var.set(summary["sample_path"])
        self.relative_path_var.set(summary["relative_path"])
        self.schedule_waveform_refresh()

    def collect_zone_values(self):
        return {k: v.get() for k, v in self.zone_vars.items()}

    def collect_range_values(self):
        return {k: v.get() for k, v in self.range_vars.items()}

    def collect_loop_values(self):
        return {k: v.get() for k, v in self.loop_vars.items()}

    def apply_current_zone_to_xml(self):
        if self.current_zone_index is None:
            return

        self.model.apply_zone_values(
            self.current_zone_index,
            self.collect_zone_values(),
            self.collect_range_values(),
            self.collect_loop_values(),
        )

        self.model.refresh()
        self.refresh_zone_list()
        self.zone_list.selection_clear(0, "end")
        self.zone_list.selection_set(self.current_zone_index)
        self.log_insert("Applied selected zone: {}\n".format(self.current_zone_index))
        self.schedule_waveform_refresh()

    def current_editor_zone_audio_context(self):
        if self.model is None or self.current_zone_index is None:
            raise RuntimeError("Select a zone first.")
        zone = self.model.get_zone(self.current_zone_index)
        sample_path = self.model.resolve_sample_file(zone)
        full_audio, sample_rate = self.waveform_cache.read_file_mono(sample_path)

        zone_start = int(parse_number_from_text(self.zone_vars.get("sample_start", tk.StringVar(value=get_value(zone, "SampleStart", "0"))).get(), parse_number_from_text(get_value(zone, "SampleStart", "0"), 0)))
        zone_end = int(parse_number_from_text(self.zone_vars.get("sample_end", tk.StringVar(value=get_value(zone, "SampleEnd", str(len(full_audio))))).get(), parse_number_from_text(get_value(zone, "SampleEnd", str(len(full_audio))), len(full_audio))))
        zone_start = max(0, min(zone_start, max(0, len(full_audio) - 1)))
        zone_end = max(zone_start + 1, min(zone_end, len(full_audio)))
        root_key = clamp_int(parse_number_from_text(self.zone_vars.get("root_key", tk.StringVar(value=get_value(zone, "RootKey", "60"))).get(), parse_number_from_text(get_value(zone, "RootKey", "60"), 60)), 0, 127)

        return {
            "zone": zone,
            "sample_path": sample_path,
            "sample_rate": int(sample_rate),
            "full_audio": full_audio,
            "zone_start": int(zone_start),
            "zone_end": int(zone_end),
            "root_key": int(root_key),
        }

    def detect_current_loop_detune(self, prefix):
        loop_key_prefix = "sustain" if prefix == "sustain" else "release"
        loop_label = "sustain" if prefix == "sustain" else "release"
        try:
            context = self.current_editor_zone_audio_context()
            diapason_hz = parse_number_from_text(self.global_vars.get("param_diapason_hz", tk.StringVar(value=DEFAULT_DIAPASON_HZ)).get(), 440.0)
            loop_start = int(parse_number_from_text(self.loop_vars["{}_start".format(loop_key_prefix)].get(), context["zone_start"]))
            loop_end = int(parse_number_from_text(self.loop_vars["{}_end".format(loop_key_prefix)].get(), context["zone_end"]))
            loop_start = max(context["zone_start"], min(loop_start, context["zone_end"] - 1))
            loop_end = max(loop_start + 1, min(loop_end, context["zone_end"]))

            zone_samples = context["full_audio"][context["zone_start"]:context["zone_end"]]
            loop_samples = context["full_audio"][loop_start:loop_end]
            info = AudioAnalysis.estimate_loop_detune_info(
                zone_samples,
                loop_samples,
                context["sample_rate"],
                fallback_root_key=context["root_key"],
                diapason_hz=diapason_hz,
            )
            if info is None:
                raise RuntimeError("Could not estimate loop detune from the current {} loop.".format(loop_label))

            detune_value = int(round(info["detune_cents"]))
            self.loop_vars["{}_detune".format(loop_key_prefix)].set(str(detune_value))
            self.status_var.set("Detected {} loop detune: {} cents".format(loop_label, detune_value))
            self.log_insert(
                "Detected {} loop detune for zone {}: {} cents (target {:.2f} Hz, loop {:.2f} Hz, method={})\n".format(
                    loop_label,
                    self.current_zone_index,
                    detune_value,
                    info["target_hz"],
                    info["loop_hz"],
                    info["method"],
                )
            )
        except Exception as e:
            self.show_error("Could not detect {} loop detune".format(loop_label), e)

    def schedule_waveform_refresh(self, *_args):
        if not hasattr(self, "waveform_canvas"):
            return
        if self.waveform_refresh_after_id is not None:
            try:
                self.root.after_cancel(self.waveform_refresh_after_id)
            except Exception:
                pass
        self.waveform_refresh_after_id = self.root.after(30, self.update_waveform_preview)

    def draw_waveform_message(self, title, detail=""):
        if not hasattr(self, "waveform_canvas"):
            return

        canvas = self.waveform_canvas
        canvas.delete("all")
        width = max(40, int(canvas.winfo_width() or 220))
        height = max(40, int(canvas.winfo_height() or 108))
        canvas.create_rectangle(0, 0, width, height, fill="#162028", outline="")
        canvas.create_text(width / 2.0, height / 2.0 - 8, text=title, fill="#d8e1e8", font=("", 10, "bold"))
        if detail:
            canvas.create_text(width / 2.0, height / 2.0 + 12, text=detail, fill="#9bb0bf", font=("", 8))

    def waveform_zone_cache_key(self, zone_audio):
        return (
            str(zone_audio.sample_path),
            int(zone_audio.sample_rate),
            int(zone_audio.zone_start),
            int(zone_audio.zone_end),
            int(len(zone_audio.samples)),
        )

    def get_cached_waveform_analysis(self, cache_key, build_func):
        if cache_key not in self.waveform_analysis_cache:
            self.waveform_analysis_cache[cache_key] = build_func()
        return self.waveform_analysis_cache[cache_key]

    def current_waveform_overlay_flags(self):
        split_enabled = bool(self.processing_update.get("split_zones", tk.BooleanVar(value=False)).get())
        split_mode = self.global_vars.get("param_split_mode", tk.StringVar(value="detect")).get()
        return {
            "split_detection": split_enabled and split_mode == "detection",
            "split_gate": split_enabled and split_mode in ("gate", "detect"),
            "split_grid": split_enabled and split_mode == "grid",
            "refine": bool(self.processing_update.get("start_end_refine", tk.BooleanVar(value=False)).get()),
            "sustain_loop": bool(self.processing_update.get("loop_detection", tk.BooleanVar(value=False)).get()),
            "release_loop": bool(self.processing_update.get("release_loop_detection", tk.BooleanVar(value=False)).get()),
            "sustain_crossfade": bool(self.processing_update.get("loop_detection", tk.BooleanVar(value=False)).get()),
            "release_crossfade": bool(self.processing_update.get("release_loop_detection", tk.BooleanVar(value=False)).get()),
        }

    def current_detection_split_preview(self, samples, sample_rate):
        sensitivity = parse_number_from_text(
            self.global_vars.get("param_split_sensitivity", tk.StringVar(value=DEFAULT_DETECTION_SPLIT_SENSITIVITY)).get(),
            parse_number_from_text(DEFAULT_DETECTION_SPLIT_SENSITIVITY, 0.5),
        )
        profile_compression_pct = parse_number_from_text(
            self.global_vars.get("param_split_profile_compression", tk.StringVar(value=DEFAULT_DETECTION_PROFILE_COMPRESSION)).get(),
            parse_number_from_text(DEFAULT_DETECTION_PROFILE_COMPRESSION, 0.0),
        )
        min_duration = int(
            parse_number_from_text(
                self.global_vars.get("param_min_duration", tk.StringVar(value=DEFAULT_DETECTION_SPLIT_MIN_DURATION)).get(),
                parse_number_from_text(DEFAULT_DETECTION_SPLIT_MIN_DURATION, 1000),
            )
        )
        include_first_zone = bool(self.global_vars.get("param_split_include_first_zone", tk.BooleanVar(value=False)).get())
        onsets = AudioAnalysis.detect_onsets(
            samples,
            sample_rate,
            sensitivity=sensitivity,
            min_duration_samples=min_duration,
            profile_compression_pct=profile_compression_pct,
        )
        bounds = SamplerProcessors.split_boundaries_from_onsets(
            0,
            len(samples),
            onsets,
            min_duration,
            include_first_zone=include_first_zone,
        )

        if len(bounds) <= 1:
            bounds = [(0, len(samples))]
        return onsets, bounds

    def current_gate_split_preview(self, samples, sample_rate):
        sensitivity = parse_number_from_text(
            self.global_vars.get("param_gate_sensitivity", tk.StringVar(value=DEFAULT_GATE_SPLIT_SENSITIVITY)).get(),
            parse_number_from_text(DEFAULT_GATE_SPLIT_SENSITIVITY, 0.35),
        )
        profile_compression_pct = parse_number_from_text(
            self.global_vars.get("param_gate_profile_compression", tk.StringVar(value=DEFAULT_GATE_PROFILE_COMPRESSION)).get(),
            parse_number_from_text(DEFAULT_GATE_PROFILE_COMPRESSION, 50.0),
        )
        stop_hysteresis_pct = parse_number_from_text(
            self.global_vars.get("param_gate_stop_hysteresis_pct", tk.StringVar(value=DEFAULT_GATE_STOP_HYSTERESIS_PCT)).get(),
            parse_number_from_text(DEFAULT_GATE_STOP_HYSTERESIS_PCT, 60.0),
        )
        start_placement = str(self.global_vars.get("param_gate_start_placement", tk.StringVar(value=DEFAULT_GATE_START_PLACEMENT)).get()).strip()
        min_duration = int(
            parse_number_from_text(
                self.global_vars.get("param_gate_min_duration", tk.StringVar(value=DEFAULT_GATE_SPLIT_MIN_DURATION)).get(),
                parse_number_from_text(DEFAULT_GATE_SPLIT_MIN_DURATION, 2000),
            )
        )
        include_first_zone = bool(self.global_vars.get("param_gate_include_first_zone", tk.BooleanVar(value=False)).get())
        onsets = AudioAnalysis.detect_gate_onsets(
            samples,
            sample_rate,
            sensitivity=sensitivity,
            min_duration_samples=min_duration,
            profile_compression_pct=profile_compression_pct,
            stop_hysteresis_pct=stop_hysteresis_pct,
            start_placement=start_placement,
        )
        bounds = SamplerProcessors.split_boundaries_from_onsets(
            0,
            len(samples),
            onsets,
            min_duration,
            include_first_zone=include_first_zone,
        )

        if len(bounds) <= 1:
            bounds = [(0, len(samples))]
        return onsets, bounds

    def current_preview_slice_bounds(self, zone_audio, samples, overlay_flags):
        if overlay_flags["split_detection"]:
            onsets, bounds = self.current_detection_split_preview(samples, zone_audio.sample_rate)
            return bounds, onsets, []
        if overlay_flags["split_gate"]:
            onsets, bounds = self.current_gate_split_preview(samples, zone_audio.sample_rate)
            return bounds, onsets, []
        if overlay_flags["split_grid"]:
            grid_markers = self.current_grid_split_markers(zone_audio)
            if not grid_markers:
                return [(0, len(samples))], [], []
            return [(int(start), int(end)) for start, end in grid_markers], [], grid_markers
        return [(0, len(samples))], [], []

    def current_refine_preview_params(self, sample_rate, sample_count):
        release_threshold = parse_number_from_text(
            self.global_vars.get("param_release_threshold", tk.StringVar(value=DEFAULT_REFINE_RELEASE_THRESHOLD)).get(),
            parse_number_from_text(DEFAULT_REFINE_RELEASE_THRESHOLD, 0.0005),
        )
        release_tail_margin = max(
            0,
            AudioAnalysis.parse_number_unit_samples(
                self.global_vars.get("param_release_tail_number", tk.StringVar(value=DEFAULT_REFINE_TAIL_NUMBER)).get(),
                self.global_vars.get("param_release_tail_unit", tk.StringVar(value=DEFAULT_REFINE_TAIL_UNIT)).get(),
                sample_rate,
                sample_count,
            ),
        )
        next_activity_threshold = parse_number_from_text(
                        self.global_vars.get("param_next_activity_threshold", tk.StringVar(value=DEFAULT_REFINE_NEXT_ACTIVITY_THRESHOLD)).get(),
            release_threshold,
        )
        shift_start = AudioAnalysis.parse_number_unit_samples(
            self.global_vars.get("param_shift_start_number", tk.StringVar(value=DEFAULT_REFINE_SHIFT_START_NUMBER)).get(),
            self.global_vars.get("param_shift_start_unit", tk.StringVar(value=DEFAULT_REFINE_SHIFT_START_UNIT)).get(),
            sample_rate,
            sample_count,
            tempo_bpm=self.global_vars.get("param_shift_start_tempo", tk.StringVar(value=DEFAULT_REFINE_SHIFT_START_TEMPO)).get(),
        )
        shift_stop = AudioAnalysis.parse_number_unit_samples(
            self.global_vars.get("param_shift_stop_number", tk.StringVar(value=DEFAULT_REFINE_SHIFT_STOP_NUMBER)).get(),
            self.global_vars.get("param_shift_stop_unit", tk.StringVar(value=DEFAULT_REFINE_SHIFT_STOP_UNIT)).get(),
            sample_rate,
            sample_count,
            tempo_bpm=self.global_vars.get("param_shift_stop_tempo", tk.StringVar(value=DEFAULT_REFINE_SHIFT_STOP_TEMPO)).get(),
        )
        return release_threshold, release_tail_margin, next_activity_threshold, shift_start, shift_stop

    def predict_loop_preview_for_slice(self, slice_samples, sample_rate, prefix, sustain_loop_info=None):
        start_number = self.global_vars.get("param_{}_loop_start_pct".format(prefix), tk.StringVar(value="25")).get()
        start_unit = self.global_vars.get("param_{}_loop_start_unit".format(prefix), tk.StringVar(value="%")).get()
        default_search_number = "25" if prefix == "sustain" else "10"
        search_range_number = self.global_vars.get("param_{}_loop_search_number".format(prefix), tk.StringVar(value=default_search_number)).get()
        search_range_unit = self.global_vars.get("param_{}_loop_search_unit".format(prefix), tk.StringVar(value="%")).get()
        crossfade_policy = self.global_vars.get("param_{}_crossfade_policy".format(prefix), tk.StringVar(value="No fade")).get()
        crossfade_custom_number = self.global_vars.get("param_{}_crossfade_custom_number".format(prefix), tk.StringVar(value="25")).get()
        crossfade_custom_unit = self.global_vars.get("param_{}_crossfade_custom_unit".format(prefix), tk.StringVar(value="%")).get()
        diapason_hz = parse_number_from_text(self.global_vars.get("param_diapason_hz", tk.StringVar(value=DEFAULT_DIAPASON_HZ)).get(), 440.0)

        pitch_hz = AudioAnalysis.detect_pitch_hz(slice_samples, sample_rate)
        release_loop_uses_absolute_start = False
        if prefix == "release":
            release_loop_uses_absolute_start = True
            release_threshold = parse_number_from_text(
                self.global_vars.get("param_release_threshold", tk.StringVar(value=DEFAULT_REFINE_RELEASE_THRESHOLD)).get(),
                parse_number_from_text(DEFAULT_REFINE_RELEASE_THRESHOLD, 0.0005),
            )
            next_activity_threshold = parse_number_from_text(
                self.global_vars.get("param_next_activity_threshold", tk.StringVar(value=DEFAULT_REFINE_NEXT_ACTIVITY_THRESHOLD)).get(),
                release_threshold,
            )
            release_region_start = AudioAnalysis.detect_release_region_start(
                slice_samples,
                release_threshold=release_threshold,
                next_activity_threshold=next_activity_threshold,
            )
            start_reference = str(self.global_vars.get("param_release_loop_start_reference", tk.StringVar(value="note-end to end")).get()).strip().lower()
            sustain_loop_end_rel = None
            if sustain_loop_info is not None:
                try:
                    sustain_loop_end_rel = int(sustain_loop_info.get("end", 0))
                except Exception:
                    sustain_loop_end_rel = None
            basis_start = AudioAnalysis.release_loop_basis_start(
                slice_samples,
                sample_rate,
                start_reference,
                sustain_loop_end_rel=sustain_loop_end_rel,
                release_region_start=release_region_start,
            )
            basis_span = max(1, len(slice_samples) - int(basis_start))
            search_range_samples = AudioAnalysis.parse_number_unit_samples(
                search_range_number,
                search_range_unit,
                sample_rate,
                basis_span,
            )
            search_range_samples = min(int(search_range_samples), int(sample_rate * WAVEFORM_PREVIEW_LOOP_SEARCH_CAP_SECONDS))
            target_offset = AudioAnalysis.parse_number_unit_samples(
                start_number,
                start_unit,
                sample_rate,
                basis_span,
            )
            target_start_sample = int(basis_start) + int(target_offset)
            loop_info = AudioAnalysis.find_release_loop_to_sample_end(
                slice_samples,
                sample_rate,
                target_start_sample=target_start_sample,
                search_range_samples=search_range_samples,
                fade_policy=crossfade_policy,
                fade_custom_number=crossfade_custom_number,
                fade_custom_unit=crossfade_custom_unit,
                pitch_hz=pitch_hz,
            )
        else:
            end_number = self.global_vars.get("param_{}_loop_end_pct".format(prefix), tk.StringVar(value="75")).get()
            end_unit = self.global_vars.get("param_{}_loop_end_unit".format(prefix), tk.StringVar(value="%")).get()
            search_range_samples = AudioAnalysis.parse_number_unit_samples(
                search_range_number,
                search_range_unit,
                sample_rate,
                len(slice_samples),
            )
            search_range_samples = min(int(search_range_samples), int(sample_rate * WAVEFORM_PREVIEW_LOOP_SEARCH_CAP_SECONDS))
            target_start_sample = AudioAnalysis.parse_number_unit_samples(
                start_number,
                start_unit,
                sample_rate,
                len(slice_samples),
            )
            target_end_sample = AudioAnalysis.parse_number_unit_samples(
                end_number,
                end_unit,
                sample_rate,
                len(slice_samples),
            )
            loop_info = AudioAnalysis.find_loop_points(
                slice_samples,
                sample_rate,
                target_start_sample=target_start_sample,
                target_end_sample=target_end_sample,
                search_range_samples=search_range_samples,
                fade_policy=crossfade_policy,
                fade_custom_number=crossfade_custom_number,
                fade_custom_unit=crossfade_custom_unit,
                pitch_hz=pitch_hz,
            )
        if loop_info is None:
            return None

        loop_offset = int(release_region_start) if prefix == "release" and release_region_start is not None and not release_loop_uses_absolute_start else 0
        loop_start = int(loop_offset + loop_info["start"])
        loop_end = int(loop_offset + loop_info["end"])
        loop_length = max(1, loop_end - loop_start)
        crossfade = max(0, min(loop_length // 2, int(loop_info.get("crossfade", 0))))

        detune_value = 0
        detune_enabled = bool(
            self.processing_update.get(
                "loop_detune_detection" if prefix == "sustain" else "release_loop_detune_detection",
                tk.BooleanVar(value=False),
            ).get()
        )
        if detune_enabled:
            fallback_root = None
            if pitch_hz is not None:
                _midi_float, fallback_root, _cents = AudioAnalysis.frequency_to_midi_parts(pitch_hz, diapason_hz=diapason_hz)
            detune_info = AudioAnalysis.estimate_loop_detune_info(
                slice_samples,
                slice_samples[loop_start:loop_end],
                sample_rate,
                fallback_root_key=fallback_root,
                diapason_hz=diapason_hz,
            )
            if detune_info is not None:
                detune_value = int(round(detune_info["detune_cents"]))

        return {
            "start": loop_start,
            "end": loop_end,
            "crossfade": int(crossfade),
            "detune": int(detune_value),
        }

    def current_editor_loop_preview(self, prefix, zone_audio):
        if prefix == "sustain":
            start_key = "sustain_start"
            end_key = "sustain_end"
            crossfade_key = "sustain_crossfade"
            detune_key = "sustain_detune"
        else:
            start_key = "release_start"
            end_key = "release_end"
            crossfade_key = "release_crossfade"
            detune_key = "release_detune"

        if start_key not in self.loop_vars or end_key not in self.loop_vars or crossfade_key not in self.loop_vars:
            return None

        loop_start = clamp_int(
            parse_number_from_text(self.loop_vars[start_key].get(), zone_audio.zone_start),
            zone_audio.zone_start,
            max(zone_audio.zone_start, zone_audio.zone_end - 1),
        )
        loop_end = clamp_int(
            parse_number_from_text(self.loop_vars[end_key].get(), zone_audio.zone_end),
            loop_start + 1,
            zone_audio.zone_end,
        )
        loop_length = max(1, loop_end - loop_start)
        crossfade = clamp_loop_crossfade(zone_audio.zone_start, loop_start, loop_end, parse_number_from_text(self.loop_vars[crossfade_key].get(), 0))

        return (0, len(zone_audio.samples), {
            "start": int(loop_start - zone_audio.zone_start),
            "end": int(loop_end - zone_audio.zone_start),
            "crossfade": int(crossfade),
            "detune": clamp_int(parse_number_from_text(self.loop_vars.get(detune_key, tk.StringVar(value="0")).get(), 0), -1200, 1200),
        })

    def current_preview_slice_annotations(self, slice_bounds, samples, sample_rate):
        pitch_color = "#8fe3ff"
        detune_color = "#ffb3c7"
        velocity_color = "#8ddc6f"
        chain_color = "#f4c96b"
        annotations = [{"items": []} for _ in slice_bounds]
        diapason_hz = parse_number_from_text(self.global_vars.get("param_diapason_hz", tk.StringVar(value=DEFAULT_DIAPASON_HZ)).get(), 440.0)

        if bool(self.processing_update.get("pitch_detection_root", tk.BooleanVar(value=False)).get()) or bool(self.processing_update.get("pitch_detection_detune", tk.BooleanVar(value=False)).get()):
            for idx, (slice_start, slice_end) in enumerate(slice_bounds):
                slice_samples = samples[slice_start:slice_end]
                if len(slice_samples) < max(256, sample_rate // 40):
                    continue
                params = {
                    "param_pitch_window_start_number": self.global_vars.get("param_pitch_window_start_number", tk.StringVar(value=DEFAULT_PITCH_WINDOW_START_NUMBER)).get(),
                    "param_pitch_window_start_unit": self.global_vars.get("param_pitch_window_start_unit", tk.StringVar(value=DEFAULT_PITCH_WINDOW_START_UNIT)).get(),
                    "param_pitch_window_stop_number": self.global_vars.get("param_pitch_window_stop_number", tk.StringVar(value=DEFAULT_PITCH_WINDOW_STOP_NUMBER)).get(),
                    "param_pitch_window_stop_unit": self.global_vars.get("param_pitch_window_stop_unit", tk.StringVar(value=DEFAULT_PITCH_WINDOW_STOP_UNIT)).get(),
                }
                window_start, window_stop = AudioAnalysis.pitch_window_bounds(len(slice_samples), sample_rate, params)
                freq_hz = AudioAnalysis.detect_pitch_hz(slice_samples[window_start:window_stop], sample_rate)
                if freq_hz is None:
                    continue
                _midi_float, detected_root, detected_cents = AudioAnalysis.frequency_to_midi_parts(freq_hz, diapason_hz=diapason_hz)
                if bool(self.processing_update.get("pitch_detection_root", tk.BooleanVar(value=False)).get()):
                    annotations[idx]["items"].append((midi_key_to_note_label(detected_root), pitch_color))
                if bool(self.processing_update.get("pitch_detection_detune", tk.BooleanVar(value=False)).get()):
                    annotations[idx]["items"].append(("({:+.0f})".format(detected_cents), detune_color))

        if bool(self.processing_update.get("multiple_notes_case", tk.BooleanVar(value=False)).get()):
            mode = str(self.global_vars.get("param_multiple_notes_mode", tk.StringVar(value="layer")).get()).strip().lower()
            if mode == "detect velocity":
                strengths = []
                valid_indices = []
                for idx, (slice_start, slice_end) in enumerate(slice_bounds):
                    slice_samples = samples[slice_start:slice_end]
                    if len(slice_samples) == 0:
                        continue
                    strengths.append(AudioAnalysis.estimate_note_strength(slice_samples, sample_rate))
                    valid_indices.append(idx)
                if strengths:
                    order = sorted(range(len(strengths)), key=lambda local_idx: (strengths[local_idx], local_idx))
                    ranges = SamplerProcessors.velocity_ranges_from_scores([strengths[local_idx] for local_idx in order])
                    for ranked_local_idx, (mn, mx) in zip(order, ranges):
                        idx = valid_indices[ranked_local_idx]
                        annotations[idx]["items"].append(("V{}-{}".format(mn, mx), velocity_color))
            elif mode == "spread velocity":
                gamma = parse_number_from_text(self.global_vars.get("param_velocity_gamma", tk.StringVar(value="1.0")).get(), 1.0)
                n = len(slice_bounds)
                if n > 0:
                    ranges = SamplerProcessors.spread_velocity_ranges_for_count(n, gamma=gamma)
                    for idx, (mn, mx) in enumerate(ranges):
                        annotations[idx]["items"].append(("V{}-{}".format(mn, mx), velocity_color))
            elif mode == "sort velocity":
                gamma = parse_number_from_text(self.global_vars.get("param_velocity_gamma", tk.StringVar(value="1.0")).get(), 1.0)
                strengths = []
                valid_indices = []
                for idx, (slice_start, slice_end) in enumerate(slice_bounds):
                    slice_samples = samples[slice_start:slice_end]
                    if len(slice_samples) == 0:
                        continue
                    strengths.append(AudioAnalysis.estimate_note_strength(slice_samples, sample_rate))
                    valid_indices.append(idx)
                if strengths:
                    order = sorted(range(len(strengths)), key=lambda local_idx: (strengths[local_idx], local_idx))
                    ranges = SamplerProcessors.spread_velocity_ranges_for_count(len(strengths), gamma=gamma)
                    for rank_position, ranked_local_idx in enumerate(order):
                        idx = valid_indices[ranked_local_idx]
                        mn, mx = ranges[rank_position]
                        annotations[idx]["items"].append(("V{}-{}".format(mn, mx), velocity_color))
            elif mode == "chain":
                ranges = SamplerProcessors.chain_ranges_for_count(len(slice_bounds))
                for idx, (mn, mx) in enumerate(ranges):
                    annotations[idx]["items"].append(("C{}-{}".format(mn, mx), chain_color))

        return annotations

    def waveform_sample_to_x(self, sample_offset, sample_count, left, plot_width):
        sample_count = max(1, int(sample_count))
        sample_offset = max(0, min(int(sample_offset), sample_count))
        return left + int(round((sample_offset / float(sample_count)) * plot_width))

    def draw_waveform_range(self, left, top, bottom, plot_width, sample_count, start_sample, end_sample, fill, outline="", stipple="gray25"):
        start_x = self.waveform_sample_to_x(start_sample, sample_count, left, plot_width)
        end_x = self.waveform_sample_to_x(end_sample, sample_count, left, plot_width)
        if end_x <= start_x:
            end_x = start_x + 1
        self.waveform_canvas.create_rectangle(
            start_x,
            top,
            end_x,
            bottom,
            fill=fill,
            outline=outline,
            stipple=stipple,
        )
        return start_x, end_x

    def draw_waveform_triangle(self, left, top, bottom, plot_width, sample_count, start_sample, end_sample, fill, direction="up", outline="", stipple="gray25"):
        start_x = self.waveform_sample_to_x(start_sample, sample_count, left, plot_width)
        end_x = self.waveform_sample_to_x(end_sample, sample_count, left, plot_width)
        if end_x <= start_x:
            end_x = start_x + 1

        if str(direction).strip().lower() == "down":
            points = [start_x, top, end_x, top, end_x, bottom]
        else:
            points = [start_x, bottom, end_x, top, end_x, bottom]

        self.waveform_canvas.create_polygon(
            points,
            fill=fill,
            outline=outline,
            stipple=stipple,
        )
        return start_x, end_x

    def draw_analysis_profile(self, canvas, left, plot_width, sample_count, view_start, offsets, values, lane_top, lane_bottom, color, threshold_lines=None):
        if values is None or len(values) < 2:
            return

        max_value = float(np.max(values))
        if max_value <= 1e-12:
            return

        canvas.create_rectangle(left, lane_top, left + plot_width, lane_bottom, fill="#112029", outline="")
        profile_height = max(1.0, float(lane_bottom - lane_top))
        points = []
        for offset, value in zip(offsets, values):
            x = self.waveform_sample_to_x(int(offset) - view_start, sample_count, left, plot_width)
            y = lane_bottom - ((float(value) / max_value) * profile_height)
            points.extend((x, y))
        if len(points) >= 4:
            canvas.create_line(*points, fill=color, width=1)

        for threshold_value, threshold_color, dash in threshold_lines or []:
            if threshold_value is None:
                continue
            y = lane_bottom - ((float(threshold_value) / max_value) * profile_height)
            canvas.create_line(left, y, left + plot_width, y, fill=threshold_color, dash=dash)

    def current_detection_profile_overlay(self, samples, sample_rate):
        compression = parse_number_from_text(
            self.global_vars.get("param_split_profile_compression", tk.StringVar(value=DEFAULT_DETECTION_PROFILE_COMPRESSION)).get(),
            parse_number_from_text(DEFAULT_DETECTION_PROFILE_COMPRESSION, 0.0),
        )
        frame_size = min(4096, max(512, sample_rate // 20))
        hop_size = max(64, frame_size // 8)
        envelope, offsets = AudioAnalysis.frame_rms(samples, frame_size=frame_size, hop_size=hop_size)
        if len(envelope) < 3:
            return None
        smoothed = AudioAnalysis.moving_average(envelope, 5)
        profiled = AudioAnalysis.split_profile_compression(smoothed, compression)
        centered_offsets = [int(offset + (frame_size // 2)) for offset in offsets]
        return centered_offsets, profiled

    def current_gate_profile_overlay(self, samples, sample_rate):
        sensitivity = parse_number_from_text(
            self.global_vars.get("param_gate_sensitivity", tk.StringVar(value=DEFAULT_GATE_SPLIT_SENSITIVITY)).get(),
            parse_number_from_text(DEFAULT_GATE_SPLIT_SENSITIVITY, 0.35),
        )
        compression = parse_number_from_text(
            self.global_vars.get("param_gate_profile_compression", tk.StringVar(value=DEFAULT_GATE_PROFILE_COMPRESSION)).get(),
            parse_number_from_text(DEFAULT_GATE_PROFILE_COMPRESSION, 50.0),
        )
        hysteresis_pct = parse_number_from_text(
            self.global_vars.get("param_gate_stop_hysteresis_pct", tk.StringVar(value=DEFAULT_GATE_STOP_HYSTERESIS_PCT)).get(),
            parse_number_from_text(DEFAULT_GATE_STOP_HYSTERESIS_PCT, 60.0),
        )
        frame_size = min(4096, max(512, sample_rate // 20))
        hop_size = max(64, frame_size // 8)
        envelope, offsets = AudioAnalysis.frame_rms(samples, frame_size=frame_size, hop_size=hop_size)
        if len(envelope) < 3:
            return None
        smoothed = AudioAnalysis.moving_average(envelope, 5)
        profiled = AudioAnalysis.split_profile_compression(smoothed, compression)
        start_threshold = max(0.01, min(0.99, float(sensitivity)))
        stop_threshold = start_threshold * max(0.01, min(1.0, float(hysteresis_pct) / 100.0))
        centered_offsets = [int(offset + (frame_size // 2)) for offset in offsets]
        return centered_offsets, profiled, start_threshold, stop_threshold

    def current_grid_split_markers(self, zone_audio):
        bpm = parse_number_from_text(self.global_vars.get("param_grid_tempo", tk.StringVar(value="100")).get(), 100.0)
        every_text = "{} {}".format(
            self.global_vars.get("param_grid_every_number", tk.StringVar(value="1")).get(),
            self.global_vars.get("param_grid_every_unit", tk.StringVar(value="bar(s)")).get()
        )
        end_after_text = "{} {}".format(
            self.global_vars.get("param_grid_end_after_number", tk.StringVar(value="3")).get(),
            self.global_vars.get("param_grid_end_after_unit", tk.StringVar(value="beat(s)")).get()
        )

        every_beats = duration_text_to_beats(every_text)
        end_after_beats = duration_text_to_beats(end_after_text)
        if bpm <= 0 or every_beats <= 0 or end_after_beats <= 0:
            return []

        samples_per_beat = zone_audio.sample_rate * 60.0 / bpm
        step_samples = max(1, int(round(every_beats * samples_per_beat)))
        duration_samples = max(1, int(round(end_after_beats * samples_per_beat)))

        markers = []
        pos = 0
        while pos < len(zone_audio.samples):
            zone_end = min(len(zone_audio.samples), pos + duration_samples)
            markers.append((int(pos), int(zone_end)))
            pos += step_samples
            if len(markers) > 2048:
                break

        return markers

    def update_waveform_preview(self):
        self.waveform_refresh_after_id = None

        if self.model is None:
            self.draw_waveform_message("No ADV loaded")
            return

        if self.current_zone_index is None:
            self.draw_waveform_message("Select a zone", "Waveform preview uses the current zone only.")
            return

        if np is None or sf is None or signal is None:
            self.draw_waveform_message("Waveform unavailable", "Install numpy, soundfile, and scipy.")
            return

        try:
            zone = self.model.get_zone(self.current_zone_index)
            zone_audio = self.waveform_cache.get_zone_audio(self.model, zone)
            samples = np.asarray(zone_audio.samples, dtype=np.float32)
            full_samples = np.asarray(zone_audio.audio, dtype=np.float32)
        except Exception as e:
            self.draw_waveform_message("Waveform unavailable", str(e))
            return

        if len(samples) == 0:
            self.draw_waveform_message("Empty zone audio")
            return

        canvas = self.waveform_canvas
        canvas.delete("all")
        width = max(80, int(canvas.winfo_width() or 220))
        height = max(60, int(canvas.winfo_height() or 108))
        left = 8
        top = 8
        right = width - 8
        bottom = height - 18
        plot_width = max(8, right - left)
        plot_height = max(8, bottom - top)
        center_y = top + (plot_height / 2.0)
        view_start, view_end = self.ensure_waveform_view_state(zone_audio)
        display_samples = full_samples[view_start:view_end]
        if len(display_samples) == 0:
            self.draw_waveform_message("Waveform unavailable", "Empty viewport")
            return
        sample_count = max(1, len(display_samples) - 1)
        zone_cache_key = self.waveform_zone_cache_key(zone_audio)
        overlay_flags = self.current_waveform_overlay_flags()

        canvas.create_rectangle(0, 0, width, height, fill="#162028", outline="")
        canvas.create_rectangle(left, top, right, bottom, outline="#31424f")
        canvas.create_line(left, center_y, right, center_y, fill="#24333f")

        zone_left_x = self.waveform_sample_to_x(zone_audio.zone_start - view_start, sample_count, left, plot_width)
        zone_right_x = self.waveform_sample_to_x(zone_audio.zone_end - view_start, sample_count, left, plot_width)
        self.draw_waveform_range(
            left,
            top,
            bottom,
            plot_width,
            sample_count,
            zone_audio.zone_start - view_start,
            zone_audio.zone_end - view_start,
            fill="#1e2f39",
            outline="",
            stipple="gray25",
        )
        canvas.create_line(zone_left_x, top, zone_left_x, bottom, fill="#4a6a7b", dash=(3, 2))
        canvas.create_line(zone_right_x, top, zone_right_x, bottom, fill="#4a6a7b", dash=(3, 2))

        analysis_lane_top = top + 2
        analysis_lane_bottom = top + 16
        if overlay_flags["split_detection"]:
            profile_overlay = self.get_cached_waveform_analysis(
                ("split_profile", "detection", zone_cache_key, self.global_vars.get("param_split_sensitivity", tk.StringVar(value=DEFAULT_DETECTION_SPLIT_SENSITIVITY)).get(), self.global_vars.get("param_split_profile_compression", tk.StringVar(value=DEFAULT_DETECTION_PROFILE_COMPRESSION)).get()),
                lambda: self.current_detection_profile_overlay(samples, zone_audio.sample_rate),
            )
            if profile_overlay is not None:
                offsets, values = profile_overlay
                self.draw_analysis_profile(
                    canvas,
                    left,
                    plot_width,
                    sample_count,
                    view_start - zone_audio.zone_start,
                    offsets,
                    values,
                    analysis_lane_top,
                    analysis_lane_bottom,
                    "#ffb347",
                    threshold_lines=[],
                )
        elif overlay_flags["split_gate"]:
            profile_overlay = self.get_cached_waveform_analysis(
                (
                    "split_profile",
                    "gate",
                    zone_cache_key,
                    self.global_vars.get("param_gate_sensitivity", tk.StringVar(value=DEFAULT_GATE_SPLIT_SENSITIVITY)).get(),
                    self.global_vars.get("param_gate_profile_compression", tk.StringVar(value=DEFAULT_GATE_PROFILE_COMPRESSION)).get(),
                    self.global_vars.get("param_gate_stop_hysteresis_pct", tk.StringVar(value=DEFAULT_GATE_STOP_HYSTERESIS_PCT)).get(),
                ),
                lambda: self.current_gate_profile_overlay(samples, zone_audio.sample_rate),
            )
            if profile_overlay is not None:
                offsets, values, start_threshold, stop_threshold = profile_overlay
                self.draw_analysis_profile(
                    canvas,
                    left,
                    plot_width,
                    sample_count,
                    view_start - zone_audio.zone_start,
                    offsets,
                    values,
                    analysis_lane_top,
                    analysis_lane_bottom,
                    "#74d99f",
                    threshold_lines=[
                        (start_threshold, "#baf0cc", (3, 2)),
                        (stop_threshold, "#7abf95", (2, 2)),
                    ],
                )

        slice_bounds, onsets, grid_markers = self.current_preview_slice_bounds(zone_audio, samples, overlay_flags)
        slice_annotations = self.current_preview_slice_annotations(slice_bounds, samples, zone_audio.sample_rate)
        lane_bottom = bottom
        lane_height = 8

        if overlay_flags["refine"]:
            release_threshold, release_tail_margin, next_activity_threshold, shift_start, shift_stop = self.current_refine_preview_params(
                zone_audio.sample_rate,
                len(samples),
            )
            for slice_index, (slice_start, slice_end) in enumerate(slice_bounds):
                slice_samples = samples[slice_start:slice_end]
                if len(slice_samples) == 0:
                    continue
                rel_start, rel_end = self.get_cached_waveform_analysis(
                    (
                        "refine",
                        zone_cache_key,
                        int(slice_start),
                        int(slice_end),
                        round(float(release_threshold), 8),
                        int(release_tail_margin),
                        round(float(next_activity_threshold), 8),
                        int(shift_start),
                        int(shift_stop),
                    ),
                    lambda slice_samples=slice_samples: AudioAnalysis.detect_activity_bounds(
                        slice_samples,
                        release_threshold=release_threshold,
                        tail_margin_samples=release_tail_margin,
                        next_activity_threshold=next_activity_threshold,
                    ),
                )
                raw_rel_start = max(0, min(rel_start, len(slice_samples) - 1))
                raw_rel_end = max(raw_rel_start + 1, min(rel_end, len(slice_samples)))
                rel_start = max(0, min(raw_rel_start + shift_start, len(slice_samples) - 1))
                rel_end = max(rel_start + 1, min(raw_rel_end + shift_stop, len(slice_samples)))
                raw_abs_start = zone_audio.zone_start + slice_start + raw_rel_start
                raw_abs_end = zone_audio.zone_start + slice_start + raw_rel_end
                abs_start = zone_audio.zone_start + slice_start + rel_start
                abs_end = zone_audio.zone_start + slice_start + rel_end
                if shift_start != 0:
                    raw_start_x = self.waveform_sample_to_x(raw_abs_start - view_start, sample_count, left, plot_width)
                    canvas.create_line(raw_start_x, top, raw_start_x, bottom, fill="#2c6a4a", dash=(2, 2))
                if shift_stop != 0:
                    raw_end_x = self.waveform_sample_to_x(raw_abs_end - view_start, sample_count, left, plot_width)
                    canvas.create_line(raw_end_x, top, raw_end_x, bottom, fill="#2c6a4a", dash=(2, 2))
                start_x, end_x = self.draw_waveform_range(
                    left,
                    bottom - 12,
                    bottom - 2,
                    plot_width,
                    sample_count,
                    abs_start - view_start,
                    abs_end - view_start,
                    fill="#2f8f5b",
                    outline="",
                    stipple="gray25",
                )
                canvas.create_line(start_x, top, start_x, bottom, fill="#53c98b", dash=(4, 2))
                canvas.create_line(end_x, top, end_x, bottom, fill="#53c98b", dash=(4, 2))
                if len(slice_bounds) == 1 or slice_index == 0:
                    canvas.create_text(start_x + 3, top + 10, anchor="w", text="start", fill="#53c98b", font=("", 8))
                    canvas.create_text(end_x - 3, top + 10, anchor="e", text="stop", fill="#53c98b", font=("", 8))

        peak = float(np.max(np.abs(display_samples)))
        if peak <= 1e-9:
            canvas.create_line(left, center_y, right, center_y, fill="#7fd1ff")
        else:
            bins = np.linspace(0, len(display_samples), plot_width + 1, dtype=np.int64)
            amp_scale = (plot_height * 0.46) / peak
            for x in range(plot_width):
                start = int(bins[x])
                end = int(bins[x + 1])
                if end <= start:
                    end = min(len(display_samples), start + 1)
                chunk = display_samples[start:end]
                if len(chunk) == 0:
                    continue
                mn = float(np.min(chunk))
                mx = float(np.max(chunk))
                y1 = center_y - (mx * amp_scale)
                y2 = center_y - (mn * amp_scale)
                canvas.create_line(left + x, y1, left + x, y2, fill="#7fd1ff")

        predicted_sustain_loops = []
        predicted_release_loops = []
        use_predicted_slice_loops = overlay_flags["split_detection"] or overlay_flags["split_gate"] or overlay_flags["split_grid"]
        if overlay_flags["sustain_loop"] or overlay_flags["sustain_crossfade"]:
            if use_predicted_slice_loops:
                for slice_start, slice_end in slice_bounds:
                    slice_samples = samples[slice_start:slice_end]
                    if len(slice_samples) == 0:
                        continue
                    loop_info = self.get_cached_waveform_analysis(
                        (
                            "loop",
                            "sustain",
                            zone_cache_key,
                            int(slice_start),
                            int(slice_end),
                            self.global_vars.get("param_sustain_loop_start_pct", tk.StringVar(value="25")).get(),
                            self.global_vars.get("param_sustain_loop_end_pct", tk.StringVar(value="75")).get(),
                            self.global_vars.get("param_sustain_loop_search_number", tk.StringVar(value="25")).get(),
                            self.global_vars.get("param_sustain_loop_search_unit", tk.StringVar(value="%")).get(),
                            self.global_vars.get("param_sustain_crossfade_policy", tk.StringVar(value="No fade")).get(),
                            self.global_vars.get("param_sustain_crossfade_custom_number", tk.StringVar(value="25")).get(),
                            self.global_vars.get("param_sustain_crossfade_custom_unit", tk.StringVar(value="%")).get(),
                            bool(self.processing_update.get("loop_detune_detection", tk.BooleanVar(value=False)).get()),
                        ),
                        lambda slice_samples=slice_samples: self.predict_loop_preview_for_slice(slice_samples, zone_audio.sample_rate, "sustain"),
                    )
                    if loop_info is not None:
                        predicted_sustain_loops.append((slice_start, slice_end, loop_info))
            else:
                loop_info = self.get_cached_waveform_analysis(
                    (
                        "loop",
                        "sustain",
                        zone_cache_key,
                        0,
                        len(samples),
                        self.global_vars.get("param_sustain_loop_start_pct", tk.StringVar(value="25")).get(),
                        self.global_vars.get("param_sustain_loop_end_pct", tk.StringVar(value="75")).get(),
                        self.global_vars.get("param_sustain_loop_search_number", tk.StringVar(value="25")).get(),
                        self.global_vars.get("param_sustain_loop_search_unit", tk.StringVar(value="%")).get(),
                        self.global_vars.get("param_sustain_crossfade_policy", tk.StringVar(value="No fade")).get(),
                        self.global_vars.get("param_sustain_crossfade_custom_number", tk.StringVar(value="25")).get(),
                        self.global_vars.get("param_sustain_crossfade_custom_unit", tk.StringVar(value="%")).get(),
                        bool(self.processing_update.get("loop_detune_detection", tk.BooleanVar(value=False)).get()),
                    ),
                    lambda: self.predict_loop_preview_for_slice(samples, zone_audio.sample_rate, "sustain"),
                )
                if loop_info is not None:
                    predicted_sustain_loops.append((0, len(samples), loop_info))

        if overlay_flags["release_loop"] or overlay_flags["release_crossfade"]:
            if use_predicted_slice_loops:
                for idx, (slice_start, slice_end) in enumerate(slice_bounds):
                    slice_samples = samples[slice_start:slice_end]
                    if len(slice_samples) == 0:
                        continue
                    sustain_loop_info = None
                    if idx < len(predicted_sustain_loops):
                        sustain_entry = predicted_sustain_loops[idx]
                        if sustain_entry[0] == slice_start and sustain_entry[1] == slice_end:
                            sustain_loop_info = sustain_entry[2]
                    loop_info = self.get_cached_waveform_analysis(
                        (
                            "loop",
                            "release",
                            zone_cache_key,
                            int(slice_start),
                            int(slice_end),
                            self.global_vars.get("param_release_loop_start_reference", tk.StringVar(value="note-end to end")).get(),
                            self.global_vars.get("param_release_loop_start_pct", tk.StringVar(value="25")).get(),
                            self.global_vars.get("param_release_loop_search_number", tk.StringVar(value="10")).get(),
                            self.global_vars.get("param_release_loop_search_unit", tk.StringVar(value="%")).get(),
                            self.global_vars.get("param_release_crossfade_policy", tk.StringVar(value="No fade")).get(),
                            self.global_vars.get("param_release_crossfade_custom_number", tk.StringVar(value="25")).get(),
                            self.global_vars.get("param_release_crossfade_custom_unit", tk.StringVar(value="%")).get(),
                            bool(self.processing_update.get("release_loop_detune_detection", tk.BooleanVar(value=False)).get()),
                            int(sustain_loop_info.get("end", 0)) if sustain_loop_info is not None else -1,
                        ),
                        lambda slice_samples=slice_samples, sustain_loop_info=sustain_loop_info: self.predict_loop_preview_for_slice(slice_samples, zone_audio.sample_rate, "release", sustain_loop_info=sustain_loop_info),
                    )
                    if loop_info is not None:
                        predicted_release_loops.append((slice_start, slice_end, loop_info))
            else:
                sustain_loop_info = None
                if predicted_sustain_loops:
                    sustain_entry = predicted_sustain_loops[0]
                    if isinstance(sustain_entry, tuple) and len(sustain_entry) == 3:
                        sustain_loop_info = sustain_entry[2]
                loop_info = self.get_cached_waveform_analysis(
                    (
                        "loop",
                        "release",
                        zone_cache_key,
                        0,
                        len(samples),
                        self.global_vars.get("param_release_loop_start_reference", tk.StringVar(value="note-end to end")).get(),
                        self.global_vars.get("param_release_loop_start_pct", tk.StringVar(value="25")).get(),
                        self.global_vars.get("param_release_loop_search_number", tk.StringVar(value="10")).get(),
                        self.global_vars.get("param_release_loop_search_unit", tk.StringVar(value="%")).get(),
                        self.global_vars.get("param_release_crossfade_policy", tk.StringVar(value="No fade")).get(),
                        self.global_vars.get("param_release_crossfade_custom_number", tk.StringVar(value="25")).get(),
                        self.global_vars.get("param_release_crossfade_custom_unit", tk.StringVar(value="%")).get(),
                        bool(self.processing_update.get("release_loop_detune_detection", tk.BooleanVar(value=False)).get()),
                        int(sustain_loop_info.get("end", 0)) if sustain_loop_info is not None else -1,
                    ),
                    lambda sustain_loop_info=sustain_loop_info: self.predict_loop_preview_for_slice(samples, zone_audio.sample_rate, "release", sustain_loop_info=sustain_loop_info),
                )
                if loop_info is not None:
                    predicted_release_loops.append((0, len(samples), loop_info))

        if overlay_flags["sustain_loop"] or overlay_flags["release_loop"]:
            sustain_lane_top = lane_bottom - lane_height
            sustain_lane_bottom = lane_bottom
            release_lane_top = lane_bottom - (lane_height * 2) - 2
            release_lane_bottom = lane_bottom - lane_height - 2

            loop_draw_specs = []
            if overlay_flags["sustain_loop"]:
                loop_draw_specs.append((predicted_sustain_loops, "#b04fd6", "S", sustain_lane_top, sustain_lane_bottom))
            if overlay_flags["release_loop"]:
                loop_draw_specs.append((predicted_release_loops, "#e0679c", "R", release_lane_top, release_lane_bottom))

            for loop_entries, fill, label, lane_top, lane_bottom_local in loop_draw_specs:
                for entry_index, (slice_start, _slice_end, loop_vals) in enumerate(loop_entries):
                    rel_loop_start = zone_audio.zone_start + slice_start + int(loop_vals["start"])
                    rel_loop_end = zone_audio.zone_start + slice_start + int(loop_vals["end"])
                    rel_loop_start = max(0, min(rel_loop_start, len(full_samples) - 1))
                    rel_loop_end = max(rel_loop_start + 1, min(rel_loop_end, len(full_samples)))
                    start_x, _end_x = self.draw_waveform_range(
                        left,
                        lane_top,
                        lane_bottom_local,
                        plot_width,
                        sample_count,
                        rel_loop_start - view_start,
                        rel_loop_end - view_start,
                        fill=fill,
                        outline="",
                        stipple="gray25",
                    )
                    if len(slice_bounds) == 1 or entry_index == 0:
                        canvas.create_text(start_x + 4, lane_top - 2, anchor="w", text=label, fill=fill, font=("", 8, "bold"))
                    detune_value = int(loop_vals.get("detune", 0) or 0)
                    if detune_value != 0:
                        canvas.create_text(start_x + 16, lane_top - 2, anchor="w", text="({:+d})".format(detune_value), fill="#ffb3c7", font=("", 7))

        for loop_entries, enabled_flag, top_a, bottom_a, top_b, bottom_b, fill in (
            (predicted_sustain_loops, overlay_flags["sustain_crossfade"], lane_bottom - lane_height, lane_bottom, lane_bottom - lane_height, lane_bottom, "#ffd166"),
            (predicted_release_loops, overlay_flags["release_crossfade"], lane_bottom - (lane_height * 2) - 2, lane_bottom - lane_height - 2, lane_bottom - (lane_height * 2) - 2, lane_bottom - lane_height - 2, "#ffb86b"),
        ):
            if not enabled_flag:
                continue
            for slice_start, _slice_end, loop_vals in loop_entries:
                crossfade = int(loop_vals.get("crossfade", 0) or 0)
                if crossfade <= 0:
                    continue
                rel_loop_start = zone_audio.zone_start + slice_start + int(loop_vals["start"])
                rel_loop_end = zone_audio.zone_start + slice_start + int(loop_vals["end"])
                # Show the overlap span both before loop end and before loop start.
                for lane_top, lane_bottom_local, cf_start, cf_end, direction in (
                    (top_a, bottom_a, rel_loop_end - crossfade, rel_loop_end, "up"),
                    (top_b, bottom_b, rel_loop_start - crossfade, rel_loop_start, "up"),
                ):
                    cf_start = max(0, min(cf_start, len(full_samples) - 1))
                    cf_end = max(cf_start + 1, min(cf_end, len(full_samples)))
                    self.draw_waveform_triangle(
                        left,
                        lane_top,
                        lane_bottom_local,
                        plot_width,
                        sample_count,
                        cf_start - view_start,
                        cf_end - view_start,
                        fill=fill,
                        direction=direction,
                        outline="",
                        stipple="gray25",
                    )

        detection_sensitivity = parse_number_from_text(
            self.global_vars.get("param_split_sensitivity", tk.StringVar(value=DEFAULT_DETECTION_SPLIT_SENSITIVITY)).get(),
            parse_number_from_text(DEFAULT_DETECTION_SPLIT_SENSITIVITY, 0.5),
        )
        detection_compression = parse_number_from_text(
            self.global_vars.get("param_split_profile_compression", tk.StringVar(value=DEFAULT_DETECTION_PROFILE_COMPRESSION)).get(),
            parse_number_from_text(DEFAULT_DETECTION_PROFILE_COMPRESSION, 0.0),
        )
        gate_sensitivity = parse_number_from_text(
            self.global_vars.get("param_gate_sensitivity", tk.StringVar(value=DEFAULT_GATE_SPLIT_SENSITIVITY)).get(),
            parse_number_from_text(DEFAULT_GATE_SPLIT_SENSITIVITY, 0.35),
        )
        gate_compression = parse_number_from_text(
            self.global_vars.get("param_gate_profile_compression", tk.StringVar(value=DEFAULT_GATE_PROFILE_COMPRESSION)).get(),
            parse_number_from_text(DEFAULT_GATE_PROFILE_COMPRESSION, 50.0),
        )
        gate_hysteresis = parse_number_from_text(
            self.global_vars.get("param_gate_stop_hysteresis_pct", tk.StringVar(value=DEFAULT_GATE_STOP_HYSTERESIS_PCT)).get(),
            parse_number_from_text(DEFAULT_GATE_STOP_HYSTERESIS_PCT, 60.0),
        )
        if overlay_flags["split_detection"]:
            for onset in onsets:
                x = self.waveform_sample_to_x((zone_audio.zone_start + onset) - view_start, sample_count, left, plot_width)
                canvas.create_line(x, top, x, bottom, fill="#ffb347")
                canvas.create_polygon(
                    x - 4, top + 2,
                    x + 4, top + 2,
                    x, top + 9,
                    fill="#ffb347",
                    outline=""
                )
        elif overlay_flags["split_gate"]:
            for onset in onsets:
                x = self.waveform_sample_to_x((zone_audio.zone_start + onset) - view_start, sample_count, left, plot_width)
                canvas.create_line(x, top, x, bottom, fill="#74d99f")
                canvas.create_polygon(
                    x - 4, top + 2,
                    x + 4, top + 2,
                    x, top + 9,
                    fill="#74d99f",
                    outline=""
                )
        elif overlay_flags["split_grid"]:
            for idx, (grid_start, grid_end) in enumerate(grid_markers, start=1):
                x = self.waveform_sample_to_x((zone_audio.zone_start + grid_start) - view_start, sample_count, left, plot_width)
                canvas.create_line(x, top, x, bottom, fill="#6fb8ff")
                canvas.create_polygon(
                    x - 4, top + 2,
                    x + 4, top + 2,
                    x, top + 9,
                    fill="#6fb8ff",
                    outline=""
                )
                end_x = self.waveform_sample_to_x((zone_audio.zone_start + grid_end) - view_start, sample_count, left, plot_width)
                canvas.create_line(end_x, bottom - 10, end_x, bottom, fill="#6fb8ff", dash=(2, 2))

        zone_name = get_value(zone, "Name", "zone")
        canvas.create_text(left + 2, height - 9, anchor="w", text=zone_name, fill="#d8e1e8", font=("", 8, "bold"))

        for (slice_start, slice_end), annotation in zip(slice_bounds, slice_annotations):
            items = annotation.get("items", [])
            if not items:
                continue
            slice_center = slice_start + max(0, (slice_end - slice_start) // 2)
            x = self.waveform_sample_to_x((zone_audio.zone_start + slice_center) - view_start, sample_count, left, plot_width)
            for item_index, (text, color) in enumerate(items[:5]):
                canvas.create_text(x, top + 20 + (item_index * 9), anchor="center", text=text, fill=color, font=("", 7))

        info_parts = []
        if overlay_flags["split_detection"]:
            info_parts.append("splits: {}".format(len(onsets)))
            info_parts.append("thr: {:.3f}".format(detection_sensitivity))
            info_parts.append("lin/log: {:.0f}%".format(detection_compression))
        elif overlay_flags["split_gate"]:
            info_parts.append("gates: {}".format(len(onsets)))
            info_parts.append("thr: {:.3f}".format(gate_sensitivity))
            info_parts.append("lin/log: {:.0f}%".format(gate_compression))
            info_parts.append("hyst: {:.0f}%".format(gate_hysteresis))
        elif overlay_flags["split_grid"]:
            info_parts.append("grid: {}".format(len(grid_markers)))
        if overlay_flags["refine"]:
            info_parts.append("stop thr: {:.4f}".format(parse_number_from_text(self.global_vars.get("param_release_threshold", tk.StringVar(value=DEFAULT_REFINE_RELEASE_THRESHOLD)).get(), 0.0005)))
            info_parts.append("next: {:.4f}".format(parse_number_from_text(self.global_vars.get("param_next_activity_threshold", tk.StringVar(value=DEFAULT_REFINE_NEXT_ACTIVITY_THRESHOLD)).get(), 0.0003)))
            shift_start_number = self.global_vars.get("param_shift_start_number", tk.StringVar(value=DEFAULT_REFINE_SHIFT_START_NUMBER)).get()
            shift_start_unit = self.global_vars.get("param_shift_start_unit", tk.StringVar(value=DEFAULT_REFINE_SHIFT_START_UNIT)).get()
            shift_stop_number = self.global_vars.get("param_shift_stop_number", tk.StringVar(value=DEFAULT_REFINE_SHIFT_STOP_NUMBER)).get()
            shift_stop_unit = self.global_vars.get("param_shift_stop_unit", tk.StringVar(value=DEFAULT_REFINE_SHIFT_STOP_UNIT)).get()
            info_parts.append("shift: {}{} / {}{}".format(shift_start_number, shift_start_unit, shift_stop_number, shift_stop_unit))
        if overlay_flags["sustain_loop"]:
            info_parts.append("loop: S")
        if overlay_flags["release_loop"]:
            info_parts.append("loop: R")
        if overlay_flags["sustain_crossfade"]:
            info_parts.append("xfade: S")
        if overlay_flags["release_crossfade"]:
            info_parts.append("xfade: R")
        if view_start != zone_audio.zone_start or view_end != zone_audio.zone_end:
            info_parts.append("view: {}-{}".format(view_start, view_end))
        if info_parts:
            canvas.create_text(
                right - 2,
                height - 9,
                anchor="e",
                text="  ".join(info_parts),
                fill="#9bb0bf",
                font=("", 8),
            )

    def reset_waveform_view(self):
        self.waveform_view_state = None

    def clear_waveform_caches(self, reset_audio=False):
        self.waveform_analysis_cache.clear()
        if reset_audio:
            self.waveform_cache.clear()

    def ensure_waveform_view_state(self, zone_audio):
        view_key = (
            str(zone_audio.sample_path),
            int(zone_audio.sample_rate),
            int(len(zone_audio.audio)),
            int(zone_audio.zone_start),
            int(zone_audio.zone_end),
        )
        if self.waveform_view_state is None or self.waveform_view_state.get("key") != view_key:
            self.waveform_view_state = {
                "key": view_key,
                "start": int(zone_audio.zone_start),
                "end": int(zone_audio.zone_end),
            }

        audio_length = max(1, int(len(zone_audio.audio)))
        start = clamp_int(self.waveform_view_state.get("start", zone_audio.zone_start), 0, max(0, audio_length - 1))
        end = clamp_int(self.waveform_view_state.get("end", zone_audio.zone_end), start + 1, audio_length)
        if end <= start:
            end = min(audio_length, start + 1)
        self.waveform_view_state["start"] = start
        self.waveform_view_state["end"] = end
        return start, end

    def on_waveform_mousewheel(self, event):
        if self.model is None or self.current_zone_index is None:
            return "break"
        if np is None or sf is None or signal is None:
            return "break"

        try:
            zone = self.model.get_zone(self.current_zone_index)
            zone_audio = self.waveform_cache.get_zone_audio(self.model, zone)
        except Exception:
            return "break"

        delta = getattr(event, "delta", 0)
        if delta == 0 and getattr(event, "num", None) in (4, 5):
            delta = 120 if event.num == 4 else -120
        if delta == 0:
            return "break"

        view_start, view_end = self.ensure_waveform_view_state(zone_audio)
        current_length = max(1, view_end - view_start)
        full_length = max(1, len(zone_audio.audio))
        zone_length = max(1, zone_audio.zone_end - zone_audio.zone_start)
        min_length = min(full_length, max(64, int(round(zone_length * 0.02))))
        zoom_factor = 0.8 if delta > 0 else 1.25
        new_length = int(round(current_length * zoom_factor))
        new_length = max(min_length, min(full_length, new_length))

        canvas_width = max(1, int(self.waveform_canvas.winfo_width() or 1))
        left = 8
        right = max(left + 1, canvas_width - 8)
        usable_width = max(1, right - left)
        pointer_x = max(left, min(int(getattr(event, "x", left)), right))
        fraction = (pointer_x - left) / float(usable_width)
        anchor_sample = view_start + (fraction * current_length)
        new_start = int(round(anchor_sample - (fraction * new_length)))
        new_end = new_start + new_length
        if new_start < 0:
            new_end -= new_start
            new_start = 0
        if new_end > full_length:
            new_start -= (new_end - full_length)
            new_end = full_length
        new_start = max(0, new_start)
        new_end = max(new_start + 1, min(full_length, new_end))

        self.waveform_view_state["start"] = new_start
        self.waveform_view_state["end"] = new_end
        self.schedule_waveform_refresh()
        return "break"

    def _rebuild_generic_group_frame(self, frame_attr_name, dynamic_keys_attr, groups, empty_message):
        frame = getattr(self, frame_attr_name, None)
        if frame is None:
            return

        for key in list(getattr(self, dynamic_keys_attr, [])):
            self.global_vars.pop(key, None)
        setattr(self, dynamic_keys_attr, [])

        inner = getattr(frame, "inner", frame)
        for widget in list(inner.winfo_children()):
            widget.destroy()

        if self.model is None:
            ttk.Label(inner, text=empty_message).grid(row=0, column=0, sticky="w", padx=4, pady=4)
            return

        built_groups = []
        for title, value_kind, key_prefix, params in groups:
            if params:
                built_groups.append((title, value_kind, key_prefix, params))

        if not built_groups:
            ttk.Label(inner, text=empty_message).grid(row=0, column=0, sticky="w", padx=4, pady=4)
            return

        row = 0
        for title, _value_kind, key_prefix, params in built_groups:
            ttk.Label(inner, text=title, font=("", 9, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(6 if row else 2, 2))
            row += 1
            for path, value in params:
                enum_id = enum_id_for_path(path)
                if enum_id == "__hidden__":
                    continue
                key = key_prefix + path
                label = path.split("/", 1)[1] if "/" in path else path
                tooltip = "Value written directly to {}".format(path)
                if enum_id:
                    self._choice_row(inner, row, label, key, enum_choices(enum_id), enum_label_from_value(enum_id, value), tooltip=tooltip)
                else:
                    self._param_row(inner, row, label, key, float_to_text(value), self.global_vars, tooltip=tooltip)
                getattr(self, dynamic_keys_attr).append(key)
                row += 1

    def rebuild_generic_lfo_fields(self):
        if self.model is None:
            self._rebuild_generic_group_frame(
                "generic_lfo_frame",
                "dynamic_lfo_keys",
                [],
                "Open an ADV to inspect modulation parameters.",
            )
            return
        groups = []
        for base_path in ("Lfo", "AuxLfos.0", "AuxLfos.0/Slot/Value/SimplerAuxLfo", "AuxLfos.1", "AuxLfos.1/Slot/Value/SimplerAuxLfo"):
            if base_path in OPTIONAL_GENERIC_MANUAL_BASES and not generic_manual_group_has_existing_content(self.model.root, base_path):
                continue
            params = merged_template_manual_paths(self.model.root, base_path)
            if params:
                groups.append((base_path, "manual", "param_lfo_manual::", params))
        for base_path in (
            "KeyDst",
            "VelDst",
            "RelVelDst",
            "MidiCtrl.0",
            "MidiCtrl.1",
            "MidiCtrl.2",
            "MidiCtrl.3",
            "MidiCtrl.4",
            "MidiCtrl.5",
            "MidiCtrl.6",
            "MidiCtrl.7",
            "AuxLfos.0/Slot/Value/SimplerAuxLfo/ModDst",
            "AuxLfos.1/Slot/Value/SimplerAuxLfo/ModDst",
        ):
            if base_path in OPTIONAL_GENERIC_VALUE_BASES and not generic_value_group_has_existing_content(self.model.root, base_path):
                continue
            params = merged_template_value_paths(self.model.root, base_path)
            if params:
                groups.append((base_path, "value", "param_lfo_value::", params))
        self._rebuild_generic_group_frame(
            "generic_lfo_frame",
            "dynamic_lfo_keys",
            groups,
            "Open an ADV to inspect modulation parameters.",
        )

    def rebuild_generic_filter_fields(self):
        if self.model is None:
            self._rebuild_generic_group_frame(
                "generic_filter_frame",
                "dynamic_filter_keys",
                [],
                "Open an ADV to inspect filter parameters.",
            )
            return
        groups = []
        for base_path in ("Filter", "Shaper"):
            params = merged_template_manual_paths(self.model.root, base_path)
            if params:
                groups.append((base_path, "manual", "param_filter_manual::", params))
        for base_path in ("Filter",):
            params = list_value_parameter_paths(self.model.root, base_path)
            value_only = [(path, value) for path, value in params if path.endswith("CurrentOverlay") or path.endswith("ScrollPosition")]
            if value_only:
                groups.append((base_path + " extra", "value", "param_filter_value::", value_only))
        self._rebuild_generic_group_frame(
            "generic_filter_frame",
            "dynamic_filter_keys",
            groups,
            "Open an ADV to inspect filter parameters.",
        )

    def rebuild_generic_aux_env_fields(self):
        if self.model is None:
            self._rebuild_generic_group_frame(
                "generic_aux_env_frame",
                "dynamic_aux_env_keys",
                [],
                "Open an ADV to inspect aux envelope parameters.",
            )
            return
        groups = []
        manual_params = merged_template_manual_paths(self.model.root, "AuxEnv")
        if manual_params:
            groups.append(("AuxEnv", "manual", "param_aux_env_manual::", manual_params))
        value_params = merged_template_value_paths(self.model.root, "AuxEnv/Slot/Value/SimplerAuxEnvelope/ModDst")
        if value_params:
            groups.append(("AuxEnv ModDst", "value", "param_aux_env_value::", value_params))
        self._rebuild_generic_group_frame(
            "generic_aux_env_frame",
            "dynamic_aux_env_keys",
            groups,
            "Open an ADV to inspect aux envelope parameters.",
        )

    def rebuild_generic_pitch_env_fields(self):
        if self.model is None:
            self._rebuild_generic_group_frame(
                "generic_pitch_env_frame",
                "dynamic_pitch_env_keys",
                [],
                "Open an ADV to inspect pitch envelope parameters.",
            )
            return
        groups = []
        manual_params = merged_template_manual_paths(self.model.root, "Pitch/Envelope")
        if manual_params:
            groups.append(("Pitch/Envelope", "manual", "param_pitch_env_manual::", manual_params))
        self._rebuild_generic_group_frame(
            "generic_pitch_env_frame",
            "dynamic_pitch_env_keys",
            groups,
            "Open an ADV to inspect pitch envelope parameters.",
        )

    def rebuild_generic_sub_osc_fields(self):
        if self.model is None:
            self._rebuild_generic_group_frame(
                "generic_sub_osc_frame",
                "dynamic_sub_osc_keys",
                [],
                "Open an ADV to inspect sub oscillator parameters.",
            )
            return
        groups = []
        manual_params = merged_template_manual_paths(self.model.root, "Player/SubOsc")
        if manual_params:
            groups.append(("Player/SubOsc", "manual", "param_sub_osc_manual::", manual_params))
        self._rebuild_generic_group_frame(
            "generic_sub_osc_frame",
            "dynamic_sub_osc_keys",
            groups,
            "Open an ADV to inspect sub oscillator parameters.",
        )

    # -------------------------------------------------------------------------
    # Global values
    # -------------------------------------------------------------------------

    def load_global_settings(self):
        if self.model is None:
            return

        g = self.model.read_global_summary()
        self.global_vars["voices"].set(g["voices"])
        if "param_default_tune_scale" in self.global_vars and g.get("default_tune_scale", "") != "":
            self.global_vars["param_default_tune_scale"].set(float_to_text(g["default_tune_scale"]))
        self.global_vars["rr"].set(str(g["round_robin"]).strip().lower() == "true")
        self.global_vars["rr_mode"].set(ROUND_ROBIN_MODE_VALUE_TO_LABEL.get(g["round_robin_mode"], g["round_robin_mode"]))
        self.global_vars["rr_reset"].set(ROUND_ROBIN_RESET_VALUE_TO_LABEL.get(g["round_robin_reset_period"], g["round_robin_reset_period"]))
        self.global_vars["rr_seed"].set(g["round_robin_random_seed"])
        if "param_default_loop_mode" in self.global_vars and g.get("default_loop_mode", "") in SUSTAIN_MODE_VALUES.values():
            self.global_vars["param_default_loop_mode"].set(loop_mode_label_from_value("sustain", g["default_loop_mode"]))
        if "param_default_release_loop_mode" in self.global_vars and g.get("default_release_loop_mode", "") in RELEASE_MODE_VALUES.values():
            self.global_vars["param_default_release_loop_mode"].set(loop_mode_label_from_value("release", g["default_release_loop_mode"]))
        for summary_key, global_key in (
            ("env_attack_ms", "param_env_attack_ms"),
            ("env_decay_ms", "param_env_decay_ms"),
            ("env_sustain", "param_env_sustain"),
            ("env_release_ms", "param_env_release_ms"),
            ("env_attack_shape", "param_env_attack_shape"),
            ("env_decay_shape", "param_env_decay_shape"),
            ("env_release_shape", "param_env_release_shape"),
        ):
            if summary_key in g and global_key in self.global_vars and g[summary_key] != "":
                self.global_vars[global_key].set(g[summary_key])
        for spec in iter_default_preset_field_specs():
            if spec["key"] not in self.global_vars:
                continue
            value = self.model.read_default_preset_field(spec)
            if spec["kind"] == "bool":
                if isinstance(value, bool):
                    self.global_vars[spec["key"]].set(value)
                else:
                    self.global_vars[spec["key"]].set(str(value).strip().lower() == "true")
            else:
                if spec.get("enum_id"):
                    self.global_vars[spec["key"]].set(enum_label_from_value(spec["enum_id"], value))
                else:
                    self.global_vars[spec["key"]].set(float_to_text(value))

    def collect_global_values(self):
        return {k: v.get() for k, v in self.global_vars.items()}

    def collect_global_update_flags(self):
        return {k: v.get() for k, v in self.global_update.items()}

    def apply_global_settings_to_xml(self):
        if self.model is None:
            return
        self.model.apply_global_values(
            self.collect_global_values(),
            self.collect_global_update_flags(),
            log_func=self.log_insert,
        )

    # -------------------------------------------------------------------------
    # Error display
    # -------------------------------------------------------------------------

    def show_error(self, title, error):
        details = traceback.format_exc()
        self.log_insert("ERROR: {}\n{}\n".format(error, details))
        messagebox.showerror(title, "{}".format(error))


def main():
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    SamplerAdvGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
