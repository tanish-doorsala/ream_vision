# ream-vision

Tools for measuring the bead width from the camera. `ream_vision_bead_width.py` measures the bead just below the nozzle and shows the result on screen, with the scale taken from the ruler in view. `ream_vision_roi_tuner.py` picks the region of interest with sliders, and `ream_vision_roi_grabber.py` writes the live camera frame to a file the tuner can read.

Run the measurement with the camera already running:

```
ros2 launch vision_processor bead_width_launch.py camera:=false
```

The launch file currently installed in the `vision_processor` package is `bead_width_launch.py`, so use that name until the package is updated to match `ream_vision_launch.py`.
