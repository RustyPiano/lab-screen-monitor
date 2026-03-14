from pathlib import Path
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import mss
except ImportError:
    mss = None

from .common import require_dependency
from .config import CONFIG_OVERRIDE_PATH, save_config_overrides, validate_roi
from .image_ops import annotate_frame, crop_frame


class ScreenCapturer:
    def __init__(self, roi: Optional[Tuple[int, int, int, int]] = None):
        require_dependency("mss", mss)
        self.roi = roi
        self.sct = mss.mss()

    def __enter__(self) -> "ScreenCapturer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def capture(self) -> np.ndarray:
        require_dependency("cv2", cv2)
        if self.roi is None:
            monitor = self.sct.monitors[1]
            shot = self.sct.grab(monitor)
        else:
            left, top, width, height = self.roi
            shot = self.sct.grab({
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            })

        img = np.array(shot)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def close(self) -> None:
        self.sct.close()

    @staticmethod
    def save(frame: np.ndarray, save_path: str) -> None:
        require_dependency("cv2", cv2)
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(save_path, frame)
        if not ok:
            raise RuntimeError(f"保存图片失败: {save_path}")


def select_roi_from_frame(
    frame: np.ndarray,
    window_name: str,
    instructions: list[str],
) -> Tuple[int, int, int, int]:
    require_dependency("cv2", cv2)

    annotated = annotate_frame(frame, instructions)
    roi = cv2.selectROI(window_name, annotated, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_name)
    roi_tuple = tuple(int(value) for value in roi)
    validate_roi(roi_tuple, window_name)
    return roi_tuple


def run_roi_selector(cfg: dict, config_path: Path = CONFIG_OVERRIDE_PATH) -> None:
    require_dependency("cv2", cv2)
    require_dependency("mss", mss)

    validate_roi(cfg.get("ROI"), "ROI")
    with ScreenCapturer(cfg["ROI"]) as capturer:
        frame = capturer.capture()

    camera_roi = select_roi_from_frame(
        frame,
        "Select Camera ROI",
        [
            "step 1/2: select CAMERA_ROI",
            "drag to select camera window",
            "press Enter/Space to confirm, c to cancel",
        ],
    )
    camera_frame = crop_frame(frame, camera_roi, "CAMERA_ROI")
    spot_roi = select_roi_from_frame(
        camera_frame,
        "Select Spot ROI",
        [
            "step 2/2: select SPOT_SEARCH_ROI",
            "drag a small box around the laser spot",
            "press Enter/Space to confirm, c to cancel",
        ],
    )

    save_config_overrides(
        {
            "CAMERA_ROI": camera_roi,
            "SPOT_SEARCH_ROI": spot_roi,
        },
        config_path=config_path,
    )

    print(f"已保存 ROI 到 {config_path}")
    print(f"CAMERA_ROI = {camera_roi}")
    print(f"SPOT_SEARCH_ROI = {spot_roi}")
