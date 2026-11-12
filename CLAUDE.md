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
**Current phase: 2 + camera screen, verified on the Pi** (capture works; exposure-cap
issue open, see below). **Plus, pulled forward from phase 4 by the owner: menu, library
and read-only settings**: written and tested against a fake camera, not yet on the Pi.

Open issue from the first Pi capture: in dim light the viewfinder picks exposures
> 33 ms (preview mode allows down to ~12 fps), but the 30 fps capture mode caps
exposure at ~32.7 ms, so frames come out ~0.6 EV darker and are marked "lock
unverified". Fix options offered: cap the viewfinder at 30 fps, or trade exposure
time for gain at capture. ❓ owner hasn't chosen.

| Phase | Scope | State |
|---|---|---|
| 1 | Repo, CLAUDE.md, camera + touch checks, fullscreen live preview | done: preview at a steady 30 fps on the Pi |
| 2 | `CaptureSource` interface, `SingleCameraSource`, save 4-frame sets, plus camera screen (shutter, last-shot thumbnail) | works on the Pi; exposure-cap issue open |
| 3 | Tap-to-select subject, translation alignment, crop, GIF + MP4 | not started |
| 4 | Gallery, playback, settings, delete/export | partly done early: menu, library (grid, raw wiggle playback, delete), read-only settings. Still to do: editable settings, export, aligned playback |
| 5 | GPIO shutter + battery abstraction (stubbed) | not started |
| 6 | Real 4-camera backend | waiting on hardware |

## Hardware
- Raspberry Pi 5, 4 GB. OS: **Raspberry Pi OS Lite (Bookworm 64-bit)**: no desktop.
- One camera module: ❓ model not confirmed. Defaults assume Camera Module 3 (16:9,
  autofocus); the code handles fixed-focus cameras too.
- Touchscreen: **800x480**, landscape. ❓ model and DSI/HDMI not confirmed.
- Later: 4 cameras via (a) a quad-camera HAT on one CSI port, or (b) 2 CSI ports plus
  networked Pi Zero nodes. ❓ not decided (see `capture/quad_hat.py`, `capture/networked.py`).
  Also a GPIO shutter button and battery.

## Decisions

| Decision | Choice | Why | Status |
|---|---|---|---|
| OS | Raspberry Pi OS Lite, Qt draws straight to the screen via `eglfs` (DRM/KMS) and reads touch itself | Boots straight into the app like a camera, ~200–400 MB more free RAM, nothing competing with the camera. Storage saving is minor. Costs: debugging only over SSH, rotation/touch set via env vars. | **owner** |
| Language | Python 3.11 | Preview latency matches C++ (picamera2 does the camera work), heavy processing runs in compiled libraries, sync is a hardware/libcamera matter. Much faster to develop. Cost: ~2–4 s startup. | proposed by Claude, accepted |
| Camera API | picamera2 (from apt) | Official, matches the system libcamera, ships Qt preview widgets | accepted |
| UI toolkit | PyQt6 (PyQt5 if 6 is missing), chosen in `ui/qt_compat.py`, which also tells picamera2 to use it (`PICAMERA2_QT_BINDING`) | Current picamera2 supports several bindings and loads its widgets lazily. Mixing bindings in one process breaks. | proposed by Claude |
| Preview | Software `QPicamera2` | picamera2's GL widgets need an X11 or Wayland display server, so they can't work under eglfs. A failed OpenGL import shows up as `NameError: _get_qglpicamera2`. `gl` in config falls back to software automatically. | **owner**: steady 30 fps |
| Viewfinder | Always **one** lens | With 4 cameras the viewfinder shows one chosen camera | **owner** |
| Simulating 4 views (1 camera) | **Burst of 4 consecutive frames** (~33 ms apart). Slide the camera sideways while shooting to get parallax. | 4 crops of one frame have no parallax and can't test alignment | **owner** |
| Capture set format | **Folder per shot: `frame_1..4.jpg` + `thumb.jpg` + `set.json`**, JPEG quality 95, written atomically (temp folder + rename) | Easy to inspect/copy. `thumb.jpg` was added by Claude for the UI. Schema is in `storage/sets.py`. | **owner** (thumb: Claude) |
| Storage location | `~/jigglecam-captures` (`storage.root`) | Outside the git checkout | Claude, easy to change |
| Capture mechanics | Lock AE/AWB/AF from the viewfinder's metadata → `switch_mode` to a capture config with those values fixed → drop frames until the metadata confirms the lock → keep N consecutive frames → switch back | One code path for exposure lock + burst. The viewfinder blacks out briefly (~0.3 s?, measure). Viewfinder and capture use the same 16:9 aspect / sensor mode, so exposure carries over 1:1. | Claude, needs Pi verification |
| Threading | `CaptureController`: one capture thread + one storage thread; events go to Qt via a signal | UI never blocks. The next shot can start while the previous one is saving. | Claude |
| Shutter abstraction | `CaptureController.trigger()` is the single entry point | Screen button now, GPIO in phase 5, same call | Claude |
| Shutter placement | Right-edge side bar (112 px): hold-✕ exit, status, round shutter, last-shot thumbnail, fps | Phone-like, thumb-reachable in landscape | **owner** |
| Navigation | "☰ Menu" at the top of the side bar opens a **slide-over panel** over the dimmed viewfinder: Library, Settings, hold-to-exit. Tapping the last-shot thumbnail opens that shot. Screens live in one `QStackedWidget` (`MainWindow`). | Exit moved from the side bar into the menu | **owner** (panel), Claude (thumbnail tap, stack) |
| Library | Thumbnail grid (4 columns, newest first, drag to scroll) → viewer that loops the **raw, unaligned** frames 1-2-3-4-3-2, tap/Pause to stop and step views with ◀ ▶, Delete with a full-screen confirm | Alignment is phase 3; delete is permanent (no trash) | **owner** |
| Settings | **Read-only info** for now: camera, storage used/free, display, version | Defers the settings save-format decision until something is editable | **owner** |
| Camera while another screen is open | Keeps streaming | Instant return to the viewfinder; saving continues in the background. Costs some CPU (software preview still converts frames). | Claude |
| Viewer decoding | PIL JPEG draft mode down to ~800x450 on a worker thread | Several times faster than full decode, and the UI never waits | Claude |
| Config format | TOML (`config/default.toml` + gitignored `config/local.toml`) | Easy to edit by hand, built into Python 3.11. Phase 4 settings writes need `tomli-w` or a separate JSON file. | ❓ **open** (owner hasn't confirmed) |
| Env | apt packages + `.venv --system-site-packages` | picamera2 must come from apt | fixed |

### Preview alternatives (not chosen, kept for reference)
- **Lite + `cage`** (a kiosk Wayland compositor that runs only our app): picamera2's
  Wayland GL widget would then work, giving a zero-copy GPU preview.
- **Our own GL widget for eglfs**: import the camera's dmabufs into Qt's EGL context.

## Layout
```
config/default.toml          default config (all keys documented inline)
jigglecam/__main__.py        entry point: python -m jigglecam [--windowed] [--software] [--config X]
jigglecam/config.py          TOML layering -> frozen dataclasses; unknown keys are errors
jigglecam/platform_env.py    sets Qt eglfs env (DRM card, rotation) before any Qt import
jigglecam/controller.py      CaptureController: shutter entry point, capture + storage threads
jigglecam/capture/base.py    CaptureSource interface, Frame/FrameMeta/FrameSet/ExposureLock
jigglecam/capture/single.py  SingleCameraSource: lock + burst + return to viewfinder
jigglecam/capture/quad_hat.py, networked.py   stubs + design notes for phase 6 (incl. sync options)
jigglecam/capture/picam.py   small Picamera2 helpers, FrameRateMeter
jigglecam/storage/sets.py    SetStore: save/list/load capture folders (format documented here)
jigglecam/ui/qt_compat.py    choose the Qt binding, load picamera2 preview widgets; import Qt only from here
jigglecam/ui/app.py          MainWindow (screen stack + navigation), choose_preview, run()
jigglecam/ui/camera.py       CameraScreen (viewfinder + side bar) and the slide-over MenuPanel
jigglecam/ui/library.py      LibraryScreen (thumbnail grid) and SetViewer (wiggle playback, delete)
jigglecam/ui/settings.py     SettingsScreen (read-only info) and gather_info()
jigglecam/ui/widgets.py      HoldButton, ConfirmOverlay, top bar, touch scrolling
jigglecam/ui/frames.py       wiggle_order(), fast JPEG decode for the screen (no Qt)
scripts/setup_pi.sh          one-time Pi setup (apt + venv)
scripts/check_camera.py      detection, still, fps/jitter, AE/AWB/AF lock test
scripts/check_touch.py       display/touch mapping + Qt binding report
tests/                       pytest; tests/fakes.py has a FakePicamera2
```
Module boundaries:
- `capture/` is the only module that talks to the camera. The UI gets
  `source.preview_camera` only to hand it to the preview widget.
- `storage/` and `controller.py` have no Qt.
- `processing/` (phase 3) and `hw/` (phase 5) don't exist yet.
- The UI must never block on capture or processing.

## Running (on the Pi)
```bash
bash scripts/setup_pi.sh          # once (re-run after pulling: new apt packages)
source .venv/bin/activate
python scripts/check_camera.py    # wave a hand in front of the lens during step 4
python scripts/check_touch.py     # tap all 4 crosshairs; hold the button to exit
python -m jigglecam               # camera screen; tap the shutter; ☰ Menu -> hold to exit, or Esc
python -m jigglecam --windowed    # windowed with a visible cursor, for debugging
pytest                            # all tests use fakes; they also run on a desktop
```
Captures land in `~/jigglecam-captures/<date_time>/`. Copy them to a PC with
`scp -r <user>@jigglecam.local:jigglecam-captures .`

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

## Verification checklists
Phase 1:
- [x] Software preview under eglfs: steady 30 fps
- [ ] `check_camera.py` PASS; record camera model, autofocus yes/no, and whether the lock held
- [ ] `check_touch.py`: taps land on the crosshairs (≤ ~10 px), and real "touch" events are reported
- [ ] Preview latency (film a phone stopwatch next to the screen)

Phase 2 + camera screen:
- [ ] Shutter → flash → "Saving…" → "Saved"; thumbnail updates; viewfinder resumes
- [ ] Status shows spread ≈ 100 ms and **no** "⚠ lock unverified"
- [ ] `set.json`: all 4 frames have identical exposure_time_us / analogue_gain / colour_gains / lens_position
- [ ] Viewfinder blackout duration feels acceptable (record it)
- [ ] Rapid tapping never crashes; a second tap during capture is ignored
- [ ] Sliding the camera sideways while shooting gives visibly offset frames

Menu, library, settings:
- [ ] ☰ Menu slides in smoothly; tapping the dimmed area closes it; hold-to-exit quits
- [ ] Library grid scrolls by dragging with a finger, and a tap opens the shot (a drag doesn't)
- [ ] Viewer opens in well under a second and loops 1-2-3-4-3-2; Pause + ◀ ▶ step views
- [ ] Delete → confirm removes the folder; the camera thumbnail updates
- [ ] Settings shows the real camera model and free space on the SD card
- [ ] Back on the camera screen the viewfinder is still live at ~30 fps

## Desktop-only caveats
- `pytest` and `check_touch.py --windowed` run on a desktop (they need PyQt, numpy and
  Pillow). Everything else needs the Pi.
- On a desktop with `DISPLAY`/`WAYLAND_DISPLAY` set, Qt uses the desktop instead of eglfs.
  That's handy for UI work, but it is **not** the path the camera uses.
