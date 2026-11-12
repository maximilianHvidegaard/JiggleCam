"""NetworkedNodesSource: STUB (phase 6). Pi 5 with 2 CSI cameras + Pi Zero nodes.

The hard part is making 4 independent cameras expose at the same instant.
Options, best sync first. **The owner decides this when hardware arrives.**

1. **Hardware trigger (GPIO line to every camera).** One wire pulses all
   sensors' external-trigger input. Sync is microseconds. But it only works
   with sensors that expose a trigger input on Pi (e.g. the IMX296 Global
   Shutter camera, some IMX477 setups). Camera Module 3 (IMX708) does not
   officially support it. Each node still sends its frame over the network
   afterwards.

2. **libcamera's frame-sync between Pis (software).** Recent Raspberry Pi
   libcamera can lock several cameras' frame timing to a "server" over the
   network (rpicam-apps `--sync server/client`). The cameras free-run at
   the same rate with aligned frame starts, and all of them grab the frame
   at an agreed timestamp. Typically well under one frame of error. Needs
   checking on our exact OS version and sensors.

3. **Network timestamps only (PTP/NTP clocks + nearest frame).** Every node
   streams at e.g. 30 fps with clocks synced by PTP. On the shutter, each
   node returns the frame whose SensorTimestamp is closest to the target time.
   Error can be up to half a frame (~16 ms at 30 fps). Fine for still
   subjects, visible on moving ones.

Common to all: the main Pi sends "capture at T" + the ExposureLock to every
node (ZeroMQ was proposed), and each node returns its frame + FrameMeta.
Exposure/WB/focus must be pushed to every node: there is no shared ISP.
The viewfinder is one of the main Pi's local CSI cameras.
"""

from __future__ import annotations

from jigglecam.capture.base import CaptureSource, FrameSet


class NetworkedNodesSource(CaptureSource):
    name = "networked_nodes"

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError("NetworkedNodesSource is planned for phase 6 (hardware not available yet)")

    def open(self) -> None:  # pragma: no cover
        raise NotImplementedError

    @property
    def preview_camera(self):  # pragma: no cover
        raise NotImplementedError

    def start(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def capture(self) -> FrameSet:  # pragma: no cover
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        pass
