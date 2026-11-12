#!/usr/bin/env python3
"""Phase 1 hardware check: camera.

Run on the Pi:  python scripts/check_camera.py [--index 0]

Checks, in order:
  1. Cameras detected, model, sensor modes.
  2. A full-resolution still can be captured (saved to check_output/).
  3. Real frame rate + timestamp jitter at preview resolution.
  4. Exposure, analogue gain, white balance AND focus can be LOCKED and stay
     fixed while the scene changes. This is the core requirement for
     wigglegrams: all 4 frames must share identical settings. Wave your hand
     in front of the lens / change lighting during this step.

Nothing here is used by the app; it's a diagnostic. The lock logic will be
reimplemented properly in the capture layer in phase 2.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

OK, WARN, FAIL = "  [ OK ]", "  [WARN]", "  [FAIL]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("check_output"))
    ap.add_argument("--lock-seconds", type=float, default=6.0)
    args = ap.parse_args()

    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        print(f"{FAIL} picamera2 not importable ({exc}). Run scripts/setup_pi.sh "
              "and make sure the venv uses --system-site-packages.")
        return 1

    failures = 0

    # 1. Detection -----------------------------------------------------------
    print("\n== 1. Detection")
    cams = Picamera2.global_camera_info()
    if not cams:
        print(f"{FAIL} no cameras. Check the ribbon cable and `rpicam-hello --list-cameras`.")
        return 1
    for i, c in enumerate(cams):
        print(f"  camera {i}: {c}")
    picam2 = Picamera2(args.index)
    props = picam2.camera_properties
    print(f"  model={props.get('Model')} pixel_array={props.get('PixelArraySize')}")
    print("  sensor modes:")
    for m in picam2.sensor_modes:
        print(f"    {m['size']} @ {m['fps']:.1f} fps, {m['bit_depth']}-bit, crop={m['crop_limits']}")
    has_af = "AfMode" in picam2.camera_controls
    print(f"  autofocus: {'yes' if has_af else 'no (fixed focus)'}")

    try:
        # 2. Still -------------------------------------------------------------
        print("\n== 2. Full-resolution still")
        picam2.configure(picam2.create_still_configuration())
        picam2.start()
        time.sleep(2)  # let AE/AWB converge
        args.out.mkdir(parents=True, exist_ok=True)
        still_path = args.out / "still.jpg"
        t0 = time.monotonic()
        picam2.capture_file(str(still_path))
        print(f"{OK} saved {still_path} ({still_path.stat().st_size // 1024} KiB) "
              f"in {(time.monotonic() - t0) * 1000:.0f} ms")
        picam2.stop()

        # 3. Frame rate --------------------------------------------------------
        print("\n== 3. Frame rate at preview resolution (1280x720)")
        picam2.configure(picam2.create_preview_configuration(main={"size": (1280, 720)}))
        picam2.start()
        time.sleep(1)
        ts = [picam2.capture_metadata()["SensorTimestamp"] for _ in range(90)]
        deltas_ms = [(b - a) / 1e6 for a, b in zip(ts, ts[1:])]
        mean = statistics.mean(deltas_ms)
        jitter = statistics.pstdev(deltas_ms)
        print(f"{OK if 1000 / mean >= 29 else WARN} {1000 / mean:.1f} fps "
              f"(frame interval {mean:.2f} ms, jitter {jitter:.2f} ms)")

        # 4. Lock --------------------------------------------------------------
        print("\n== 4. Exposure / gain / white balance / focus lock")
        if has_af:
            from libcamera import controls
            picam2.set_controls({"AfMode": controls.AfModeEnum.Auto})
            focused = picam2.autofocus_cycle()
            print(f"  autofocus cycle: {'success' if focused else 'did not converge'}")
        md = picam2.capture_metadata()
        lock = {
            "AeEnable": False,
            "AwbEnable": False,
            "ExposureTime": md["ExposureTime"],
            "AnalogueGain": md["AnalogueGain"],
            "ColourGains": tuple(md["ColourGains"]),
        }
        if has_af:
            lock["AfMode"] = controls.AfModeEnum.Manual
            lock["LensPosition"] = md.get("LensPosition", 1.0)
        print(f"  locking to: {lock}")
        picam2.set_controls(lock)
        for _ in range(10):  # controls take a few frames to apply
            picam2.capture_metadata()

        print(f"  >>> Wave your hand / change the lighting for {args.lock_seconds:.0f} s <<<")
        samples = []
        t_end = time.monotonic() + args.lock_seconds
        while time.monotonic() < t_end:
            samples.append(picam2.capture_metadata())

        def spread(key, idx=None):
            vals = [s[key][idx] if idx is not None else s[key] for s in samples if key in s]
            return (max(vals) - min(vals)) / max(abs(statistics.mean(vals)), 1e-9) if vals else None

        checks = {
            "ExposureTime": spread("ExposureTime"),
            "AnalogueGain": spread("AnalogueGain"),
            "ColourGains[R]": spread("ColourGains", 0),
            "ColourGains[B]": spread("ColourGains", 1),
        }
        if has_af:
            checks["LensPosition"] = spread("LensPosition")
        lux = [s["Lux"] for s in samples if "Lux" in s]
        if lux:
            print(f"  scene brightness varied {min(lux):.0f}..{max(lux):.0f} lux "
                  f"({'good, the scene changed' if max(lux) > 1.3 * min(lux) else 'little change: lock not really stressed'})")
        for name, rel in checks.items():
            if rel is None:
                print(f"{WARN} {name}: not reported in metadata")
            elif rel <= 0.01:
                print(f"{OK} {name} held fixed (spread {rel * 100:.2f}%)")
            else:
                print(f"{FAIL} {name} drifted by {rel * 100:.1f}% while locked")
                failures += 1
    finally:
        picam2.stop()
        picam2.close()

    print(f"\n== Result: {'PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
