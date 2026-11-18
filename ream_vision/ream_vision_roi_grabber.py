#!/usr/bin/env python3
"""
Writes the latest camera frame to a file so ream_vision_roi_tuner.py can show it live on the host.

Runs INSIDE the ream2_c container (it has rclpy and cv2). The container's ream2_ws
folder is bind-mounted from the host, so the file appears on the host at:
    /home/tanish/robotic_ream2_docker/ream2_ws/.roi/live.png

Start it (from the host):
    docker cp docker/ream_vision_roi_grabber.py ream2_c:/root/ream_vision_roi_grabber.py
    docker exec -d ream2_c bash -c 'source /opt/ros/humble/setup.bash && python3 /root/ream_vision_roi_grabber.py'

Stop it:
    docker exec ream2_c pkill -f ream_vision_roi_grabber.py
"""

import os
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

TOPIC = os.environ.get("ROI_TOPIC", "/flir_camera/image_raw")
OUT = os.environ.get("ROI_OUT", "/root/ream2_ws/.roi/live.png")
MIN_PERIOD = float(os.environ.get("ROI_PERIOD", "0.2"))  # seconds between writes (~5 fps)


def to_bgr(msg):
    """Convert a sensor_msgs/Image to a BGR numpy array (cv_bridge is not installed here)."""
    h, w = msg.height, msg.width
    buf = np.frombuffer(bytes(msg.data), dtype=np.uint8).reshape(h, msg.step)
    if msg.encoding == "mono8":
        return cv2.cvtColor(buf[:, :w], cv2.COLOR_GRAY2BGR)
    if msg.encoding in ("rgb8", "bgr8"):
        img = buf[:, : w * 3].reshape(h, w, 3)
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if msg.encoding == "rgb8" else img.copy()
    raise ValueError(f"unsupported image encoding: {msg.encoding}")


class Grabber(Node):
    def __init__(self):
        super().__init__("roi_grabber")
        self.last_write = 0.0
        self.written = 0
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        self.create_subscription(Image, TOPIC, self.on_image, qos_profile_sensor_data)
        self.get_logger().info(f"reading {TOPIC} -> {OUT}")

    def on_image(self, msg):
        now = time.time()
        if now - self.last_write < MIN_PERIOD:
            return
        self.last_write = now
        try:
            bgr = to_bgr(msg)
        except ValueError as exc:
            self.get_logger().error(str(exc))
            return
        tmp = OUT + ".tmp.png"  # write then rename so the tuner never reads a half-written file
        cv2.imwrite(tmp, bgr, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        os.replace(tmp, OUT)
        self.written += 1
        if self.written % 100 == 1:
            self.get_logger().info(f"wrote {self.written} frames")


def main():
    rclpy.init()
    node = Grabber()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
