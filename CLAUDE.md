# JiggleCam — CLAUDE.md

A handheld Raspberry Pi 5 camera that captures 4 horizontally offset views at the
same instant, aligns them on a chosen subject, and exports a looping wigglegram
(frame order 1-2-3-4-3-2) as GIF and MP4. It should feel like a normal camera:
fullscreen touch UI, live preview, shutter, gallery, playback, settings.

## Working agreement (from the owner)
- Explain the design and tradeoffs. The owner makes the big decisions: **ask before
  choosing frameworks, file formats or sync strategies.**
- Work in small, testable phases. **Do not build later phases ahead of time.**
- Code must run on the Pi itself. Flag anything that only works on a desktop.
- Keep this file updated whenever a decision changes.

## Status
**Current phase: 1** (repo setup, hardware checks, minimal fullscreen preview).
Written, not yet verified on hardware.

| Phase | Scope | State |
|---|---|---|
| 1 | Repo, CLAUDE.md, camera + touch checks, fullscreen live preview | code written, needs Pi verification |
| 2 | `CaptureSource` interface, `SingleCameraSource`, save 4-frame sets | not started |
| 3 | Tap-to-select subject, translation alignment, crop, GIF + MP4 | not started |
| 4 | Gallery, playback, settings, delete/export | not started |
| 5 | GPIO shutter + battery abstraction (stubbed) | not started |
| 6 | Real 4-camera backend | waiting on hardware |

## Hardware
- Raspberry Pi 5, 4 GB. OS: **Raspberry Pi OS Lite (Bookworm 64-bit)**: no desktop.
- One camera module: ❓ model not confirmed yet (affects whether focus must be locked).
- Touchscreen: ❓ model, resolution, DSI/HDMI not confirmed yet.
- Later: 4 cameras via (a) a quad-camera HAT on one CSI port, or (b) 2 CSI ports plus
  networked Pi Zero nodes. ❓ not decided. Also a GPIO shutter button and battery.

## Decisions

| Decision | Choice | Why | Status |
|---|---|---|---|
| OS | Raspberry Pi OS Lite, Qt draws straight to the screen via `eglfs` (DRM/KMS) and reads touch itself | Boots straight into the app like a camera, ~200–400 MB more free RAM, nothing competing with the camera. Storage saving is minor. Costs: debugging only over SSH, rotation/touch set via env vars. We switched now so the preview risk shows up in phase 1. It did: the GL widget can't run under eglfs (see Preview). | **decided by owner** |
| Language | Python 3.11 | Camera preview runs on the GPU inside picamera2, so latency matches C++. Heavy processing runs in OpenCV's C++ code. Sync is a hardware/libcamera matter, not a language matter. Much faster to develop. The cost is ~2–4 s startup, which can be hidden by running as a service. | proposed by Claude, owner said "start building" |
| Camera API | picamera2 (from apt) | Official, matches the system libcamera, ships Qt preview widgets | same |
| UI toolkit | PyQt6 (PyQt5 if 6 is missing), chosen in `jigglecam/ui/qt_compat.py`, which also tells picamera2 to use it (`PICAMERA2_QT_BINDING`) | Current picamera2 supports several bindings and loads its widgets lazily. Mixing bindings in one process breaks. | proposed by Claude |
| Preview | `QPicamera2` (CPU/software) by default. `gl` falls back to software automatically under eglfs. | **Found Nov 2026 in picamera2's source:** its GL widgets need an X11 or Wayland display server. On Lite with eglfs they can't work, and a failed OpenGL import shows up as `NameError: _get_qglpicamera2`. | **decided by owner (Nov 2026)**: software preview, which runs at a steady 30 fps on the Pi. The viewfinder always shows **one** camera (with 4 cameras: one chosen lens). |
| Config format | TOML (`config/default.toml` + gitignored `config/local.toml`) | Easy to edit by hand; reader built into Python 3.11. Phase 4 settings writes will need `tomli-w` or a separate JSON settings file. ❓ owner to confirm | **open** |
| Env | apt packages + `.venv --system-site-packages` | picamera2 must come from apt | fixed |
| Status bar placement | Below the preview, not overlaid | Qt widgets don't draw reliably over the GL native surface. Use picamera2 `set_overlay()` for overlays later. | fixed |

### Preview options on Lite (option 1 chosen; 2 and 3 kept for reference)
1. **Software `QPicamera2` under eglfs** (chosen: steady 30 fps). Each frame is copied into Qt by the CPU.
   Probably fine if the preview stream is about screen size. Measure fps and CPU first (`top`).
2. **Lite + a tiny kiosk Wayland compositor (`cage`)** that runs only our app. picamera2's
   Wayland GL widget then works (zero-copy GPU preview). Costs one extra package and a
   slightly more complex launch; still no desktop.
3. **Our own GL widget for eglfs** (import the camera's dmabufs into Qt's EGL context).
   Zero-copy and no compositor, but it's code we have to write and maintain.

Open design notes for phase 2 (not built yet):
- `CaptureSource` should expose a **preview stream** separate from `capture() → 4 frames + metadata`.
  With 4 cameras the preview will come from one camera (HAT: crop of the combined frame;
  nodes: the local CSI camera).
- 4 offset crops of one frame have **no parallax**, so they can't exercise alignment.
  Options: burst captures while sliding the camera, or a `FolderSource` that loads real
  4-image sets from disk. ❓ owner to decide
- Lock AE, AWB **and AF** (if the camera has autofocus) before every 4-frame capture.

## Layout
```
config/default.toml        default config (phase-1 keys only)
jigglecam/__main__.py      entry point: python -m jigglecam [--windowed] [--software] [--config X]
jigglecam/config.py        TOML layering -> frozen dataclasses; unknown keys are errors
jigglecam/platform_env.py  sets Qt eglfs env (DRM card, rotation) before any Qt import
jigglecam/capture/picam.py open one camera for preview; FrameRateMeter
jigglecam/ui/qt_compat.py  pick the Qt binding picamera2 uses; import Qt only from here
jigglecam/ui/app.py        fullscreen preview window, hold-to-exit button, fps readout
scripts/setup_pi.sh        one-time Pi setup (apt + venv)
scripts/check_camera.py    detection, still, fps/jitter, AE/AWB/AF lock test
scripts/check_touch.py     display/touch mapping + Qt binding report
tests/                     pytest (pure-Python parts only)
```
Module boundaries: `capture/` is the only module that talks to the camera (the UI
gets the Picamera2 object only to hand it to the preview widget). `processing/`,
`storage/` and `hw/` arrive in phases 2–5. The UI must never block on capture or processing.

## Running (on the Pi)
```bash
bash scripts/setup_pi.sh          # once
source .venv/bin/activate
python scripts/check_camera.py    # wave a hand in front of the lens during step 4
python scripts/check_touch.py     # tap all 4 crosshairs; hold the button to exit
python -m jigglecam               # fullscreen preview; hold "hold to exit" 1 s, or Esc
python -m jigglecam --windowed    # windowed with a visible cursor, for debugging
pytest                            # config tests (also run on a desktop)
```
On Lite everything runs straight from an SSH session: with no desktop present,
`platform_env.py` sets `QT_QPA_PLATFORM=eglfs` and Qt takes over the physical screen.
- Black screen or a "could not find DRM device" error: set `display.kms_device`
  (e.g. `"/dev/dri/card1"`) in `config/local.toml`. `ls /sys/class/drm/` shows which
  card has the connected screen.
- To debug Qt's eglfs side: `QT_DEBUG_PLUGINS=1` and `QT_LOGGING_RULES="qt.qpa.*=true"`.
- Setting `QT_QPA_PLATFORM` yourself overrides all of this.

## First-time Pi setup (Raspberry Pi Imager)
OS: Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**. In OS customisation, set:
- hostname (`jigglecam`)
- user and password
- Wi-Fi and locale
- **Services → enable SSH**, ideally with public-key auth

Then `ssh <user>@jigglecam.local`, clone the repo, and run `bash scripts/setup_pi.sh`.
The camera is auto-detected (`camera_auto_detect=1`). A non-official DSI or SPI touchscreen
may need a `dtoverlay=` line in `/boot/firmware/config.txt`.

## Phase 1 verification checklist
- [ ] `setup_pi.sh` completes; sanity check prints the Qt binding
- [ ] `check_camera.py` PASS; record fps, autofocus yes/no, and whether the lock held
- [ ] `check_touch.py`: taps land on the crosshairs (≤ ~10 px), and "touch" events (not just "mouse") are reported
- [ ] `python -m jigglecam` fullscreen at ≥ 30 fps; hold-to-exit works
- [x] ~~GL preview works under eglfs~~: it can't (needs X11/Wayland, see Decisions)
- [x] Software preview under eglfs: steady 30 fps (CPU % not yet recorded)
- [ ] Screen and touch rotation agree (`display.rotation`)
- [ ] Preview latency: film a phone stopwatch next to the screen and record the delay here
- [ ] Record results + the Qt binding/platform used in this file

## Desktop-only caveats
- `pytest` and `check_touch.py --windowed` run on a desktop (they need PyQt). Everything else needs the Pi.
- On a desktop with `DISPLAY`/`WAYLAND_DISPLAY` set, Qt uses the desktop instead of eglfs.
  That's handy for UI work, but it is **not** the path the camera uses.
