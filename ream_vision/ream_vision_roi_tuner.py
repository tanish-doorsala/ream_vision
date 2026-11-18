#!/usr/bin/env python3
"""
ROI (region of interest) tuner.

Drag the x / y / width / height sliders until the green box covers the
"window" you care about. The live crop, pixel values and fractional values
update as you go. Press "Save" (or Enter) to write a YAML file, and the same
values are printed to the terminal.

Examples:
    python3 ream_vision_roi_tuner.py --source 0                  # first webcam
    python3 ream_vision_roi_tuner.py --source /dev/video2        # specific V4L2 device
    python3 ream_vision_roi_tuner.py --source snapshot.png       # still image (good for testing)
    python3 ream_vision_roi_tuner.py --source clip.mp4           # video file (loops last frame at EOF)
    python3 ream_vision_roi_tuner.py --source 0 --out cell_roi.yaml

Keys:  Enter / s = save    r = reset to centre    q / Esc = quit

Requirements (host side): python3 with opencv (cv2), numpy and Tk
(Debian/Ubuntu: sudo apt install python3-opencv python3-tk python3-numpy).

Note: docker/ is not mounted into the ream2 container (only ream2_ws is), so
run this script on the host. The camera devices are reachable from the host.
"""

import argparse
import base64
import os
import sys
import time
import tkinter as tk

import cv2
import numpy as np

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


class FrameSource:
    """Wraps a webcam index, device path, video file, still image or a live image file.

    live=True: an image file that another process keeps overwriting (ream_vision_roi_grabber.py).
    The file is reloaded whenever its modification time changes.
    """

    def __init__(self, source, live=False):
        self.static = None
        self.cap = None
        self.last = None
        self.path = None
        self.mtime = None
        self.live = False
        self.interval_ms = 33  # how often the tuner polls for a new frame

        if isinstance(source, str) and source.lower().endswith(IMAGE_EXTENSIONS):
            self.path = source
            if live:
                self.live = True
                self.interval_ms = 200
                self.static = self._load_live()  # may be None until the grabber writes
                return
            self.static = cv2.imread(source)
            if self.static is None:
                sys.exit(f"error: could not read image '{source}'")
            return

        if isinstance(source, str) and source.isdigit():
            source = int(source)

        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            sys.exit(f"error: could not open video source '{source}'")

    @property
    def is_static(self):
        """True when nothing will change, so the tuner does not need to keep polling."""
        return self.path is not None and not self.live

    def _load_live(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return None
        if mtime == self.mtime:
            return self.static
        img = cv2.imread(self.path)
        if img is not None:
            self.mtime = mtime
            return img
        return self.static

    def read(self):
        """Return the newest BGR frame, or the last good frame if none is available."""
        if self.live:
            self.static = self._load_live()
            return self.static
        if self.static is not None:
            return self.static
        ok, frame = self.cap.read()
        if ok and frame is not None:
            self.last = frame
        return self.last

    def close(self):
        if self.cap is not None:
            self.cap.release()


class ROITuner:
    MAX_DISPLAY_W = 900  # width of the preview panel in pixels
    MAX_CROP_W = 320     # width of the crop preview in pixels

    def __init__(self, root, source, out_path):
        self.root = root
        self.source = source
        self.out_path = out_path
        self.syncing = False

        self.frame = None
        self.frame_h = 0
        self.frame_w = 0

        # Wait for the first frame so we know the image size (up to ~10 s).
        for _ in range(100):
            self.frame = self.source.read()
            if self.frame is not None:
                break
            time.sleep(0.1)
        if self.frame is None:
            sys.exit("error: no frames received from the source")
        self.frame_h, self.frame_w = self.frame.shape[:2]

        self._build_ui()
        self._set_initial_values()
        self._on_slider()

        self.root.bind("<Return>", lambda _e: self.save())
        self.root.bind("<s>", lambda _e: self.save())
        self.root.bind("<r>", lambda _e: self.reset())
        self.root.bind("<q>", lambda _e: self.quit())
        self.root.bind("<Escape>", lambda _e: self.quit())
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self._tick()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.root.title("ROI tuner")
        self.root.configure(bg="#1e1e1e")

        main = tk.Frame(self.root, bg="#1e1e1e")
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Left: full frame with the ROI highlighted.
        self.preview_label = tk.Label(main, bg="#1e1e1e")
        self.preview_label.grid(row=0, column=0, rowspan=2, sticky="nw")

        # Right: sliders, readout, crop preview, buttons.
        side = tk.Frame(main, bg="#1e1e1e")
        side.grid(row=0, column=1, sticky="nw", padx=(16, 0))

        fg = "#e6e6e6"
        self.sliders = {}
        for name in ("x", "y", "width", "height"):
            tk.Label(side, text=name, fg=fg, bg="#1e1e1e",
                     font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
            s = tk.Scale(side, from_=0, to=100, orient=tk.HORIZONTAL, length=320,
                         resolution=1, showvalue=True, command=self._on_slider,
                         bg="#1e1e1e", fg=fg, troughcolor="#3a3a3a",
                         highlightthickness=0, activebackground="#4caf50")
            s.pack(anchor="w", pady=(0, 6))
            self.sliders[name] = s

        self.sx = self.sliders["x"]
        self.sy = self.sliders["y"]
        self.sw = self.sliders["width"]
        self.sh = self.sliders["height"]

        self.readout = tk.Label(side, text="", fg="#7CFC00", bg="#1e1e1e",
                                justify=tk.LEFT, font=("Courier", 11))
        self.readout.pack(anchor="w", pady=(8, 8))

        tk.Label(side, text="crop preview", fg=fg, bg="#1e1e1e").pack(anchor="w")
        self.crop_label = tk.Label(side, bg="#1e1e1e")
        self.crop_label.pack(anchor="w", pady=(2, 10))

        buttons = tk.Frame(side, bg="#1e1e1e")
        buttons.pack(anchor="w")
        tk.Button(buttons, text="Save (Enter)", command=self.save).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(buttons, text="Print", command=self.print_values).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(buttons, text="Reset (r)", command=self.reset).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(buttons, text="Quit (q)", command=self.quit).pack(side=tk.LEFT)

        self.status = tk.Label(side, text="", fg="#aaaaaa", bg="#1e1e1e", justify=tk.LEFT,
                               wraplength=320)
        self.status.pack(anchor="w", pady=(8, 0))

    def _set_initial_values(self):
        self.syncing = True
        try:
            self._apply_bounds()
            self.sx.set(self.frame_w // 4)
            self.sy.set(self.frame_h // 4)
            self.sw.set(self.frame_w // 2)
            self.sh.set(self.frame_h // 2)
        finally:
            self.syncing = False

    def _apply_bounds(self):
        """Set slider ranges to match the current frame size."""
        self.sx.config(to=max(0, self.frame_w - 1))
        self.sy.config(to=max(0, self.frame_h - 1))
        self.sw.config(to=max(1, self.frame_w))
        self.sh.config(to=max(1, self.frame_h))

    # --------------------------------------------------------------- logic
    def _clamp(self):
        """Keep the ROI inside the frame and keep the sliders' ranges in sync."""
        W, H = self.frame_w, self.frame_h
        x = min(max(0, self.sx.get()), W - 1)
        y = min(max(0, self.sy.get()), H - 1)
        w = min(max(1, self.sw.get()), W - x)
        h = min(max(1, self.sh.get()), H - y)

        # A slider's maximum depends on the others, so the ranges shrink as
        # the ROI is moved toward a corner.
        self.sw.config(to=max(1, W - x))
        self.sh.config(to=max(1, H - y))

        self.sx.set(x)
        self.sy.set(y)
        self.sw.set(w)
        self.sh.set(h)
        return x, y, w, h

    def _on_slider(self, _value=None):
        if self.syncing:
            return
        self.syncing = True
        try:
            self.vals = self._clamp()
        finally:
            self.syncing = False
        self._refresh_readout()
        self.render()

    def _refresh_readout(self):
        x, y, w, h = self.vals
        W, H = self.frame_w, self.frame_h
        text = (
            f"x = {x:<5d}  y = {y:<5d}\n"
            f"w = {w:<5d}  h = {h:<5d}\n"
            f"\n"
            f"frame   {W} x {H}\n"
            f"norm    x0={x / W:.3f} y0={y / H:.3f}\n"
            f"        x1={(x + w) / W:.3f} y1={(y + h) / H:.3f}"
        )
        self.readout.config(text=text)

    def _tick(self):
        """Pull the newest frame from the camera periodically (live view)."""
        frame = self.source.read()
        if frame is not None and frame is not self.frame:
            h, w = frame.shape[:2]
            self.frame = frame
            if (h, w) != (self.frame_h, self.frame_w):
                self.frame_h, self.frame_w = h, w
                self.syncing = True
                try:
                    self._apply_bounds()
                    self.vals = self._clamp()
                finally:
                    self.syncing = False
                self._refresh_readout()
            self.render()
        if not self.source.is_static:
            self.root.after(self.source.interval_ms, self._tick)  # live camera or live file

    def render(self):
        if self.frame is None:
            return
        x, y, w, h = self.vals
        W, H = self.frame_w, self.frame_h

        # Dim everything outside the ROI and outline the ROI in green.
        vis = (self.frame.astype(np.float32) * 0.35).astype(np.uint8)
        vis[y:y + h, x:x + w] = self.frame[y:y + h, x:x + w]
        thickness = max(2, W // 320)
        cv2.rectangle(vis, (x, y), (x + w - 1, y + h - 1), (0, 255, 0), thickness)

        scale = min(1.0, self.MAX_DISPLAY_W / W)
        if scale < 1.0:
            vis = cv2.resize(vis, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        self._set_label(self.preview_label, vis, attr="_preview_img")

        crop = self.frame[y:y + h, x:x + w]
        cscale = min(1.0, self.MAX_CROP_W / max(1, crop.shape[1]))
        if cscale < 1.0:
            crop = cv2.resize(crop, None, fx=cscale, fy=cscale, interpolation=cv2.INTER_AREA)
        self._set_label(self.crop_label, crop, attr="_crop_img")

    def _set_label(self, label, bgr, attr):
        ok, buf = cv2.imencode(".png", bgr)
        if not ok:
            return
        photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))
        label.config(image=photo)
        setattr(self, attr, photo)  # keep a reference so Tk doesn't drop the image

    # ------------------------------------------------------------- outputs
    def values_dict(self):
        x, y, w, h = self.vals
        W, H = self.frame_w, self.frame_h
        return {
            "roi": {"x": x, "y": y, "width": w, "height": h},
            "frame_size": {"width": W, "height": H},
            "normalized": {
                "x": round(x / W, 4),
                "y": round(y / H, 4),
                "width": round(w / W, 4),
                "height": round(h / H, 4),
            },
        }

    def yaml_text(self):
        d = self.values_dict()
        r, f, n = d["roi"], d["frame_size"], d["normalized"]
        return (
            "roi:\n"
            f"  x: {r['x']}\n"
            f"  y: {r['y']}\n"
            f"  width: {r['width']}\n"
            f"  height: {r['height']}\n"
            "frame_size:\n"
            f"  width: {f['width']}\n"
            f"  height: {f['height']}\n"
            "normalized:\n"
            f"  x: {n['x']}\n"
            f"  y: {n['y']}\n"
            f"  width: {n['width']}\n"
            f"  height: {n['height']}\n"
        )

    def snippet_text(self):
        x, y, w, h = self.vals
        return (
            f"# OpenCV crop\n"
            f"roi = frame[{y}:{y + h}, {x}:{x + w}]\n"
            f"# (x, y, w, h) tuple\n"
            f"ROI = ({x}, {y}, {w}, {h})"
        )

    def print_values(self):
        print(self.yaml_text(), end="")
        print(self.snippet_text())
        self.status.config(text="printed to terminal")

    def save(self):
        out = os.path.abspath(self.out_path)
        try:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(self.yaml_text())
        except OSError as exc:
            self.status.config(text=f"save failed: {exc}")
            return
        self.print_values()
        self.status.config(text=f"saved to {out}")

    def reset(self):
        self.syncing = True
        try:
            self._apply_bounds()
            self.sx.set(self.frame_w // 4)
            self.sy.set(self.frame_h // 4)
            self.sw.set(self.frame_w // 2)
            self.sh.set(self.frame_h // 2)
        finally:
            self.syncing = False
        self._on_slider()

    def quit(self):
        self.source.close()
        self.root.destroy()


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Interactive ROI picker with sliders.")
    p.add_argument("--source", default="0",
                   help="webcam index (0), device path (/dev/video2), image or video file")
    p.add_argument("--out", default="roi.yaml",
                   help="YAML file written by Save (default: roi.yaml in the current directory)")
    p.add_argument("--live", action="store_true",
                   help="--source is an image file that is being overwritten live (ream_vision_roi_grabber.py)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    source = FrameSource(args.source, live=args.live)
    root = tk.Tk()
    ROITuner(root, source, args.out)
    try:
        root.mainloop()
    finally:
        source.close()


if __name__ == "__main__":
    main()
