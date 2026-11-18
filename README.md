# ream_vision

ROS 2 package for measuring bead width from the camera. `bead_width` measures the bead just below the nozzle and shows the result on screen, with the scale taken from the ruler in view. `roi_tuner` picks the region of interest with sliders, and `roi_grabber` writes the live camera frame to a file the tuner reads.

Build from the repo root (this folder is the workspace; the package is in `src/ream_vision`):

```
colcon build --packages-select ream_vision --symlink-install
source install/setup.bash
```

Run the measurement with the camera already running:

```
ros2 launch ream_vision ream_vision_launch.py camera:=false
```

Drop `camera:=false` to also start the Chameleon camera from that launch.
