#!/usr/bin/env bash
# One-time setup on the Raspberry Pi (Raspberry Pi OS Lite, Bookworm 64-bit).
# Safe to re-run:   bash scripts/setup_pi.sh
#
# Why apt + a venv with --system-site-packages:
#   picamera2 and its libcamera bindings must match the system libcamera,
#   so they come from apt. PyQt is also far easier from apt on ARM (no long
#   source builds). The venv only isolates *our* package and dev tools while
#   still seeing those system packages.
#
# Why --no-install-recommends: on Lite, picamera2's "recommended" packages
# pull in a large chunk of desktop/X11 stuff we don't use.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "This script is meant for the Raspberry Pi (aarch64). Detected $(uname -m)." >&2
  exit 1
fi

echo "== apt packages"
sudo apt update
sudo apt install -y --no-install-recommends \
  git \
  python3-picamera2 \
  python3-pyqt5 python3-pyqt5.qtopengl python3-opengl \
  python3-pyqt6 qt6-qpa-plugins \
  python3-venv python3-pip \
  fonts-dejavu-core \
  rpicam-apps-lite

echo "== user groups (screen, GPU and touchscreen access without sudo)"
missing=()
for g in video render input; do
  id -nG "$USER" | grep -qw "$g" || missing+=("$g")
done
if (( ${#missing[@]} )); then
  sudo usermod -aG "$(IFS=,; echo "${missing[*]}")" "$USER"
  echo "  added $USER to: ${missing[*]}  -> log out and back in (or reboot) before running the app"
else
  echo "  ok (video, render, input)"
fi

echo "== virtualenv (.venv, with system site packages)"
if [[ ! -d .venv ]]; then
  python3 -m venv --system-site-packages .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"

echo
echo "== Quick sanity check"
rpicam-hello --list-cameras || true
echo "  connected screens:"
grep -l '^connected' /sys/class/drm/card*-*/status 2>/dev/null | sed 's|/sys/class/drm/||; s|/status||; s|^|    |' || echo "    none found"
.venv/bin/python -c "from jigglecam.ui import qt_compat; print('  Qt:', qt_compat.summary())"

echo
echo "Done. Next (works straight from SSH, no desktop needed):"
echo "  source .venv/bin/activate"
echo "  python scripts/check_camera.py"
echo "  python scripts/check_touch.py"
echo "  python -m jigglecam"
