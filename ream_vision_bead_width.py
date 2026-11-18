#!/usr/bin/env python3
"""
Bead width from the ROI saved by docker/ream_vision_roi_tuner.py.

The bead is warm yellow/cream (OpenCV hue about 16), the fabric behind it is
blue (hue about 106), so HSV hue separates them well. The width is the median
horizontal run of bead pixels per row, measured only in a band just below the
nozzle (the top of the ROI), converted to mm with pixels_per_mm.

The scale comes from the ruler's tick marks inside the ROI when a ruler is
visible (tenth-inch ticks, 2.54 mm each). If no ruler is in view, the last
ruler reading is kept, or the pixels_per_mm parameter if none yet.

Run it with the camera:
    ros2 launch vision_processor ream_vision_launch.py

Offline (no ROS needed), on a saved image:
    python3 ream_vision_bead_width.py --image frame.png --roi 746 176 621 520
"""

import argparse
import sys

import cv2
import numpy as np

# OpenCV HSV ranges: hue 0-179, saturation 0-255, value 0-255
BEAD_HUE_MAX = 35
BEAD_SAT_MIN = 50
# The ruler's beige metal face has saturation about 145, the bead about 70-100,
# so a ceiling keeps the metal out of the bead mask.
BEAD_SAT_MAX = 125
BEAD_VAL_MIN = 120
MIN_BEAD_AREA_PX = 500  # connected blobs smaller than this are noise, not bead

# Metal face of the ruler / caliper (used to find the tick band)
FACE_SAT_MIN = 100
FACE_VAL_MIN = 150

# Ruler: tenth-inch ticks, 2.54 mm apart, pitch about 70-130 px in this view
RULER_MM_PER_TICK = 2.54
RULER_PITCH_PX = (70, 130)

# Measure only this band of ROI rows, starting just below the nozzle
NOZZLE_SKIP_ROWS = 25
NOZZLE_BAND_ROWS = 175

# Fallback scale (ruler reading from 2026-11-17, 98.7 px per tenth inch)
DEFAULT_PX_PER_MM = 38.9

# Saved ROI from docker/ream_vision_roi_tuner.py (x, y, width, height)
DEFAULT_ROI = [746, 176, 621, 520]


def bead_mask(bgr):
    """Binary mask (255 = bead) for a BGR image."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    mask = ((h <= BEAD_HUE_MAX) & (s >= BEAD_SAT_MIN) & (s <= BEAD_SAT_MAX)
            & (v >= BEAD_VAL_MIN)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return mask


def measure(bgr, pixels_per_mm):
    """
    Measure the bead in a BGR ROI image, in the band below the nozzle.

    Returns a dict with width_px (median), width_mm, p10_px, p90_px, rows,
    mask, row_spans (ROI coordinates) and band (first and last+1 ROI row),
    or None if no bead is found in the band.
    """
    mask = bead_mask(bgr)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= MIN_BEAD_AREA_PX
    bead = keep[labels]

    band_lo = NOZZLE_SKIP_ROWS
    band_hi = min(bgr.shape[0], NOZZLE_SKIP_ROWS + NOZZLE_BAND_ROWS)

    # The bead is a narrow band. Rows whose span covers most of the ROI are the
    # ruler or other non-bead colour, so skip them.
    max_span = 0.5 * bgr.shape[1]
    spans = []
    widths = []
    for y in range(band_lo, band_hi):
        xs = np.flatnonzero(bead[y])
        if xs.size:
            left, right = int(xs[0]), int(xs[-1])
            if right - left + 1 > max_span:
                continue
            spans.append((y, left, right))
            widths.append(right - left + 1)
    if not widths:
        return None
    widths = np.asarray(widths, dtype=float)

    median_px = float(np.median(widths))
    return {
        "width_px": median_px,
        "width_mm": median_px / pixels_per_mm,
        "p10_px": float(np.percentile(widths, 10)),
        "p90_px": float(np.percentile(widths, 90)),
        "rows": int(widths.size),
        "mask": mask,
        "row_spans": spans,
        "band": (band_lo, band_hi),
    }


def crop(img, roi):
    x, y, w, h = roi
    return img[y:y + h, x:x + w]


def calibrate_from_ticks(bgr, mm_per_tick, pitch_lo, pitch_hi):
    """
    px per mm from tick marks on a metal scale (ruler or caliper) inside this ROI.

    Finds the metal face, reads the tick band just under its top edge, takes the
    median spacing between neighbouring ticks in the given pitch range, and
    divides by mm_per_tick. Returns None when no scale is visible.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    face = ((h <= BEAD_HUE_MAX) & (s >= FACE_SAT_MIN) & (v >= FACE_VAL_MIN)).astype(np.uint8) * 255
    face = cv2.morphologyEx(face, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(face)
    if n <= 1:
        return None
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    px, py, pw, ph = stats[biggest, :4]
    if pw < 100 or ph < 40:
        return None

    # Tick band: just under the face's top edge, where the ticks start
    band_top = py + 15
    band_bot = min(py + 25, bgr.shape[0])
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    band = gray[band_top:band_bot, px:px + pw].astype(float).mean(axis=0)
    dark = np.flatnonzero(band < np.percentile(band, 15))
    if dark.size == 0:
        return None
    groups = [[dark[0]]]
    for x in dark[1:]:
        if x - groups[-1][-1] <= 3:
            groups[-1].append(x)
        else:
            groups.append([x])
    ticks = np.array([np.mean(g) for g in groups]) + px
    if ticks.size < 3:
        return None
    gaps = np.diff(ticks)
    gaps = gaps[(gaps > pitch_lo) & (gaps < pitch_hi)]
    if gaps.size < 2:
        return None
    return float(np.median(gaps)) / mm_per_tick


def calibrate_from_ruler(bgr):
    """px per mm from the ruler inside this ROI, or None if no ruler is visible."""
    return calibrate_from_ticks(bgr, RULER_MM_PER_TICK, *RULER_PITCH_PX)


def draw_overlay(frame, roi, res, px_per_mm, scale_source=""):
    """Draw the ROI, the nozzle band, the measured spans and the readout on a copy of the frame."""
    out = frame.copy()
    x, y, w, h = roi
    cv2.rectangle(out, (x, y), (x + w - 1, y + h - 1), (0, 255, 0), 2)
    band_lo = y + NOZZLE_SKIP_ROWS
    band_hi = min(y + h, y + NOZZLE_SKIP_ROWS + NOZZLE_BAND_ROWS)
    cv2.line(out, (x, band_lo), (x + w - 1, band_lo), (255, 255, 0), 2)
    cv2.line(out, (x, band_hi), (x + w - 1, band_hi), (255, 255, 0), 2)
    if res is not None:
        # yellow line across the bead at each sampled row
        for row_y, left, right in res["row_spans"][::5]:
            cv2.line(out, (x + left, y + row_y), (x + right, y + row_y), (0, 255, 255), 2)
        text = (f"width {res['width_mm']:.2f} mm  ({res['width_px']:.0f} px, "
                f"{px_per_mm:.2f} px/mm, {scale_source})")
    else:
        text = "no bead found in nozzle band"
    cv2.rectangle(out, (0, 0), (out.shape[1], 46), (0, 0, 0), -1)
    cv2.putText(out, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2, cv2.LINE_AA)
    return out


def main_offline(argv=None):
    p = argparse.ArgumentParser(description="Measure bead width in a saved image.")
    p.add_argument("--image", required=True)
    p.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"), default=DEFAULT_ROI)
    p.add_argument("--px-per-mm", type=float, default=None,
                   help="scale; default is the ruler in the ROI, else the fallback")
    p.add_argument("--save-mask", default=None, help="optional path to write the bead mask")
    args = p.parse_args(argv)

    img = cv2.imread(args.image)
    if img is None:
        sys.exit(f"error: could not read {args.image}")
    roi_img = crop(img, args.roi)
    ppm = args.px_per_mm
    source = "given"
    if ppm is None:
        ppm = calibrate_from_ruler(roi_img)
        source = "ruler in ROI"
        if ppm is None:
            ppm = DEFAULT_PX_PER_MM
            source = "fallback"
    res = measure(roi_img, ppm)
    if res is None:
        sys.exit("no bead found in the nozzle band")
    print(f"scale     {ppm:.2f} px/mm ({source})")
    print(f"band      rows {res['band'][0]}-{res['band'][1]} of the ROI")
    print(f"width_px  median={res['width_px']:.1f}  p10={res['p10_px']:.0f}  p90={res['p90_px']:.0f}  rows={res['rows']}")
    print(f"width_mm  {res['width_mm']:.3f}")
    if args.save_mask:
        cv2.imwrite(args.save_mask, res["mask"])


# ---------------------------------------------------------------- ROS node
def ros_main():
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image
    from std_msgs.msg import Float32

    def image_to_bgr(msg):
        h, w = msg.height, msg.width
        buf = np.frombuffer(bytes(msg.data), dtype=np.uint8).reshape(h, msg.step)
        if msg.encoding == "rgb8":
            return cv2.cvtColor(buf[:, : w * 3].reshape(h, w, 3), cv2.COLOR_RGB2BGR)
        if msg.encoding == "bgr8":
            return buf[:, : w * 3].reshape(h, w, 3).copy()
        if msg.encoding == "mono8":
            return cv2.cvtColor(buf[:, :w], cv2.COLOR_GRAY2BGR)
        raise ValueError(f"unsupported encoding {msg.encoding}")

    class BeadWidthNode(Node):
        def __init__(self):
            super().__init__("bead_width")
            self.declare_parameter("image_topic", "/flir_camera/image_raw")
            # "x,y,w,h" string (launch passes a string); the default is the saved roi.yaml box
            self.declare_parameter("roi", ",".join(str(v) for v in DEFAULT_ROI))
            self.declare_parameter("pixels_per_mm", DEFAULT_PX_PER_MM)
            self.declare_parameter("show_ui", True)
            roi_value = self.get_parameter("roi").value
            parts = str(roi_value).strip("[] ").replace(" ", "").split(",")
            self.roi = [int(v) for v in parts]
            if len(self.roi) != 4:
                raise ValueError(f"roi must be x,y,w,h but got '{roi_value}'")
            self.px_per_mm = float(self.get_parameter("pixels_per_mm").value)
            self.show_ui = bool(self.get_parameter("show_ui").value)
            self.pub = self.create_publisher(Float32, "bead_width_mm", 10)
            self.count = 0
            self.scale_source = "parameter"

            if self.show_ui:
                cv2.namedWindow("Bead View", cv2.WINDOW_NORMAL)
                cv2.namedWindow("Bead Mask", cv2.WINDOW_NORMAL)
                cv2.resizeWindow("Bead View", 900, 680)
                cv2.resizeWindow("Bead Mask", 450, 340)

            self.create_subscription(
                Image, self.get_parameter("image_topic").value, self.on_image, qos_profile_sensor_data
            )
            self.get_logger().info(
                f"roi={self.roi} band=rows {NOZZLE_SKIP_ROWS}-{NOZZLE_SKIP_ROWS + NOZZLE_BAND_ROWS} "
                f"fallback={self.px_per_mm} px/mm"
            )

        def on_image(self, msg):
            try:
                bgr = image_to_bgr(msg)
            except ValueError as exc:
                self.get_logger().error(str(exc))
                return
            roi_img = crop(bgr, self.roi)
            self.count += 1

            # Scale from the ruler inside the ROI when visible; otherwise keep the last one
            ruler = calibrate_from_ruler(roi_img)
            if ruler is not None:
                self.px_per_mm = ruler
                self.scale_source = "ruler in ROI"
            else:
                self.scale_source = "last/parameter"

            res = measure(roi_img, self.px_per_mm)

            if res is not None:
                out = Float32()
                out.data = float(res["width_mm"])
                self.pub.publish(out)
                if self.count % 10 == 0:
                    self.get_logger().info(
                        f"width {res['width_mm']:.3f} mm ({res['width_px']:.1f} px at "
                        f"{self.px_per_mm:.2f} px/mm, {self.scale_source}; "
                        f"p10 {res['p10_px']:.0f} / p90 {res['p90_px']:.0f} px)"
                    )
            elif self.count % 20 == 0:
                self.get_logger().warn("no bead found in nozzle band")

            if self.show_ui:
                view = draw_overlay(bgr, self.roi, res, self.px_per_mm, self.scale_source)
                scale = min(1.0, 900 / view.shape[1])
                if scale < 1.0:
                    view = cv2.resize(view, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                cv2.imshow("Bead View", view)
                if res is not None:
                    cv2.imshow("Bead Mask", res["mask"])
                cv2.waitKey(1)

    rclpy.init()
    node = BeadWidthNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        cv2.destroyAllWindows()


def main():
    ros_main()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--image":
        main_offline(sys.argv[1:])
    else:
        main()
