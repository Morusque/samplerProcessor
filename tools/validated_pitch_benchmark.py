import argparse
import importlib.util
import json
import math
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "sampler_adv_processor.py"
SPEC = importlib.util.spec_from_file_location("sampler_adv_processor", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


DEFAULT_PRESETS = (
    "matryomin merged synth strings 01.adv",
    "shruti box looping MS 01.adv",
    "cello arco vib backForthLoop MS 01.adv",
)


def median(values):
    return float(statistics.median(values)) if values else None


def zone_pitch_reference(zone):
    root = int(MODULE.parse_number_from_text(MODULE.get_value(zone, "RootKey", "0"), 0))
    detune = float(MODULE.parse_number_from_text(MODULE.get_value(zone, "Detune", "0"), 0.0))
    return root + (detune / 100.0)


def midi_float_from_hz(freq_hz, diapason_hz=440.0):
    return 69.0 + (12.0 * math.log2(float(freq_hz) / float(diapason_hz)))


def evaluate_preset(adv_path, correction):
    model = MODULE.SamplerAdvModel(MODULE.AdvCodec.load(adv_path), source_path=adv_path)
    cache = MODULE.ZoneAudioCache()
    rows = []
    errors = []
    no_pitch = 0

    for index in range(model.zone_count()):
        zone = model.get_zone(index)
        try:
            audio = cache.get_zone_audio(model, zone)
        except Exception:
            no_pitch += 1
            continue

        freq_hz = MODULE.AudioAnalysis.detect_pitch_hz(
            audio.samples,
            audio.sample_rate,
            harmonic_correction=correction,
        )
        if freq_hz is None:
            no_pitch += 1
            continue

        detected = midi_float_from_hz(freq_hz)
        reference = zone_pitch_reference(zone)
        error = detected - reference
        errors.append(error)
        if abs(error) >= 0.75:
            _midi_float, root, cents = MODULE.AudioAnalysis.frequency_to_midi_parts(freq_hz)
            rows.append(
                {
                    "zone": index,
                    "reference": round(reference, 3),
                    "detected": round(detected, 3),
                    "error_st": round(error, 3),
                    "detected_root": root,
                    "detected_detune": round(cents, 1),
                    "reference_root": MODULE.get_value(zone, "RootKey", ""),
                    "reference_detune": MODULE.get_value(zone, "Detune", ""),
                }
            )

    return {
        "preset": adv_path.name,
        "zones": model.zone_count(),
        "pitched": len(errors),
        "no_pitch": no_pitch,
        "median_abs_st": median([abs(error) for error in errors]),
        "max_abs_st": max([abs(error) for error in errors], default=None),
        "bad_ge_0_75st": sum(1 for error in errors if abs(error) >= 0.75),
        "outliers": rows,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark pitch detection against validated ADV presets.")
    parser.add_argument(
        "--correction",
        choices=("standard", "extended"),
        default="standard",
        help="Pitch harmonic correction mode.",
    )
    parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Preset filename inside testPresets01 Project/adv presets. Can be repeated.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    adv_dir = ROOT / "testPresets01 Project" / "adv presets"
    names = args.preset or list(DEFAULT_PRESETS)
    results = [evaluate_preset(adv_dir / name, args.correction) for name in names]

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return

    for result in results:
        print(
            "{preset}: zones={zones} pitched={pitched} no_pitch={no_pitch} "
            "median_abs={median_abs_st:.3f} max_abs={max_abs_st:.3f} bad>=0.75={bad_ge_0_75st}".format(
                **result
            )
        )
        for row in result["outliers"][:12]:
            print(
                "  zone {zone}: ref={reference} detected={detected} err={error_st} "
                "root {reference_root}->{detected_root} detune {reference_detune}->{detected_detune}".format(
                    **row
                )
            )


if __name__ == "__main__":
    main()
