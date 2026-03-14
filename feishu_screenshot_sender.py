import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
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

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
    )
except ImportError:
    lark = None
    CreateImageRequest = None
    CreateImageRequestBody = None
    CreateMessageRequest = None
    CreateMessageRequestBody = None


# =========================================================
# 配置区：你只需要改这里
# =========================================================
CONFIG = {
    # 飞书应用信息
    "APP_ID": "",
    "APP_SECRET": "",

    # 接收对象
    # 发给个人：open_id
    # 发给群：chat_id
    "RECEIVE_ID_TYPE": "chat_id",   # "open_id" 或 "chat_id"
    "RECEIVE_ID": "",

    # 定时发送整屏截图的间隔（秒）
    "INTERVAL_SECONDS": 1800,

    # 截图区域
    # None 表示全屏
    # (left, top, width, height) 表示指定区域
    # 注意：CAMERA_ROI 是相对于这里截下来的图像坐标
    "ROI": None,
    # 例子：
    # "ROI": (200, 120, 800, 600),

    # 相机窗口区域（相对于 ROI 截图后的图像坐标）
    # 例如：(1280, 0, 1280, 1600)
    "CAMERA_ROI": None,

    # 激光亮点搜索区域（相对于 CAMERA_ROI 的图像坐标）
    # 例如：(420, 430, 180, 180)
    "SPOT_SEARCH_ROI": None,

    # 激光点检测间隔（秒）
    "DETECT_INTERVAL_SECONDS": 5,

    # 建立正常基线时采样的帧数，建议 10-20
    "BASELINE_INIT_FRAMES": 15,

    # 亮度或面积比基线降低多少算异常
    # 例如 0.10 表示当前值低于基线 90% 时算异常
    "INTENSITY_DROP_RATIO_THRESHOLD": 0.05,
    "AREA_DROP_RATIO_THRESHOLD": 0.05,

    # 连续多少帧异常才报警
    "ALERT_CONSECUTIVE_FRAMES": 3,

    # 报警冷却时间，防止刷屏（秒）
    "ALERT_COOLDOWN_SECONDS": 300,

    # 是否先发文本再发图片
    "SEND_TEXT_BEFORE_IMAGE": True,

    # 文本内容前缀
    "TEXT_PREFIX": "实验截图",

    # 本地保存目录
    "SAVE_DIR": "feishu_screenshots",

    # 日志级别
    "LOG_LEVEL": "INFO",
}

CONFIG_OVERRIDE_PATH = Path(__file__).with_name("config.local.json")
ROI_CONFIG_KEYS = ("ROI", "CAMERA_ROI", "SPOT_SEARCH_ROI")


def normalize_config_overrides(overrides: dict) -> dict:
    normalized = dict(overrides)
    for key in ROI_CONFIG_KEYS:
        value = normalized.get(key)
        if value is None:
            continue
        normalized[key] = tuple(int(part) for part in value)
    return normalized


def build_runtime_config(base_config: dict, overrides: Optional[dict] = None) -> dict:
    merged = dict(base_config)
    if overrides:
        merged.update(normalize_config_overrides(overrides))
    return merged


def load_runtime_config(config_path: Path = CONFIG_OVERRIDE_PATH) -> dict:
    if not config_path.exists():
        return dict(CONFIG)

    with open(config_path, "r", encoding="utf-8") as f:
        overrides = json.load(f)
    return build_runtime_config(CONFIG, overrides)


def save_config_overrides(overrides: dict, config_path: Path = CONFIG_OVERRIDE_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    current_overrides = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            current_overrides = json.load(f)

    current_overrides.update(overrides)
    serializable = {}
    for key, value in current_overrides.items():
        if key in ROI_CONFIG_KEYS and value is not None:
            serializable[key] = list(value)
        else:
            serializable[key] = value

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
        f.write("\n")


def require_dependency(module_name: str, module_obj) -> None:
    if module_obj is None:
        raise RuntimeError(f"缺少依赖模块: {module_name}")


def validate_roi(roi: Optional[Tuple[int, int, int, int]], name: str) -> None:
    if roi is None:
        return

    if len(roi) != 4:
        raise ValueError(f"{name} 必须是 (left, top, width, height)")

    left, top, width, height = roi
    if min(left, top, width, height) < 0:
        raise ValueError(f"{name} 不能包含负数")
    if width <= 0 or height <= 0:
        raise ValueError(f"{name} 的 width 和 height 必须大于 0")


def crop_frame(frame: np.ndarray, roi: Optional[Tuple[int, int, int, int]], name: str) -> np.ndarray:
    if roi is None:
        return frame.copy()

    left, top, width, height = roi
    frame_height, frame_width = frame.shape[:2]
    right = left + width
    bottom = top + height
    if right > frame_width or bottom > frame_height:
        raise ValueError(
            f"{name} 超出图像范围: roi={roi}, frame_size=({frame_width}, {frame_height})"
        )
    return frame[top:bottom, left:right].copy()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def make_output_path(save_dir: str, prefix: str = "screenshot") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    Path(save_dir).mkdir(parents=True, exist_ok=True)
    return str(Path(save_dir) / f"{prefix}_{ts}.png")


def append_log(save_dir: str, text: str) -> None:
    log_path = Path(save_dir) / "sender.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{now_str()}] {text}\n")


def annotate_frame(frame: np.ndarray, text_lines: list[str]) -> np.ndarray:
    if cv2 is None:
        return frame.copy()

    vis = frame.copy()
    y = 30
    for line in text_lines:
        cv2.putText(
            vis,
            line,
            (10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )
        y += 30
    return vis


def to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame.astype(np.float32)
    if frame.ndim != 3 or frame.shape[2] < 3:
        raise ValueError("输入图像必须是灰度图或 3 通道图")

    bgr = frame[..., :3].astype(np.float32)
    weights = np.array([0.114, 0.587, 0.299], dtype=np.float32)
    return np.tensordot(bgr, weights, axes=([-1], [0]))


def mean_blur_3x3(gray: np.ndarray) -> np.ndarray:
    padded = np.pad(gray, ((1, 1), (1, 1)), mode="edge")
    return (
        padded[:-2, :-2]
        + padded[:-2, 1:-1]
        + padded[:-2, 2:]
        + padded[1:-1, :-2]
        + padded[1:-1, 1:-1]
        + padded[1:-1, 2:]
        + padded[2:, :-2]
        + padded[2:, 1:-1]
        + padded[2:, 2:]
    ) / 9.0


def percentile_normalize(gray: np.ndarray) -> np.ndarray:
    low = float(np.percentile(gray, 5.0))
    high = float(np.percentile(gray, 99.5))
    if high - low < 1.0:
        return np.clip(gray, 0, 255).astype(np.uint8)

    normalized = (gray - low) * 255.0 / (high - low)
    return np.clip(normalized, 0, 255).astype(np.uint8)


def largest_connected_component(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    best_coords: list[Tuple[int, int]] = []
    neighbors = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    )

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue

            stack = [(y, x)]
            visited[y, x] = True
            coords: list[Tuple[int, int]] = []

            while stack:
                cy, cx = stack.pop()
                coords.append((cy, cx))
                for dy, dx in neighbors:
                    ny = cy + dy
                    nx = cx + dx
                    if (
                        0 <= ny < height
                        and 0 <= nx < width
                        and mask[ny, nx]
                        and not visited[ny, nx]
                    ):
                        visited[ny, nx] = True
                        stack.append((ny, nx))

            if len(coords) > len(best_coords):
                best_coords = coords

    if not best_coords:
        return np.empty((0, 2), dtype=np.int32)
    return np.array(best_coords, dtype=np.int32)


def draw_rectangle(
    frame: np.ndarray,
    roi: Tuple[int, int, int, int],
    color: Tuple[int, int, int],
    thickness: int = 2,
) -> np.ndarray:
    vis = frame.copy()
    left, top, width, height = roi
    right = left + width
    bottom = top + height

    vis[top:top + thickness, left:right] = color
    vis[max(top, bottom - thickness):bottom, left:right] = color
    vis[top:bottom, left:left + thickness] = color
    vis[top:bottom, max(left, right - thickness):right] = color
    return vis


def draw_cross(
    frame: np.ndarray,
    center: Tuple[float, float],
    color: Tuple[int, int, int],
    size: int = 6,
    thickness: int = 1,
) -> np.ndarray:
    vis = frame.copy()
    cx = int(round(center[0]))
    cy = int(round(center[1]))
    height, width = vis.shape[:2]

    left = max(0, cx - size)
    right = min(width, cx + size + 1)
    top = max(0, cy - size)
    bottom = min(height, cy + size + 1)

    vis[max(0, cy - thickness):min(height, cy + thickness + 1), left:right] = color
    vis[top:bottom, max(0, cx - thickness):min(width, cx + thickness + 1)] = color
    return vis


def resize_nearest(frame: np.ndarray, new_height: int, new_width: int) -> np.ndarray:
    src_height, src_width = frame.shape[:2]
    y_idx = np.clip(
        (np.arange(new_height) * src_height / new_height).astype(np.int32),
        0,
        src_height - 1,
    )
    x_idx = np.clip(
        (np.arange(new_width) * src_width / new_width).astype(np.int32),
        0,
        src_width - 1,
    )
    if frame.ndim == 2:
        return frame[y_idx[:, None], x_idx[None, :]]
    return frame[y_idx[:, None], x_idx[None, :], :]


def safe_ratio(current: float, baseline: Optional[float]) -> float:
    if baseline is None or baseline <= 0:
        return 0.0
    return current / baseline


def detection_enabled(cfg: dict) -> bool:
    return cfg.get("CAMERA_ROI") is not None and cfg.get("SPOT_SEARCH_ROI") is not None


@dataclass
class LaserSpotMeasurement:
    is_detected: bool
    spot_area: float
    spot_sum_intensity: float
    spot_centroid: Optional[Tuple[float, float]]
    peak_intensity: float
    threshold_value: float
    mask: np.ndarray = field(repr=False)
    debug_frame: np.ndarray = field(repr=False)


@dataclass
class SpotMonitorEvent:
    status: str
    reason: str
    measurement: LaserSpotMeasurement
    baseline_area: Optional[float] = None
    baseline_intensity: Optional[float] = None
    area_ratio: Optional[float] = None
    intensity_ratio: Optional[float] = None
    consecutive_anomalies: int = 0
    baseline_progress: int = 0
    baseline_target: int = 0
    should_alert: bool = False


class LaserSpotDetector:
    def __init__(
        self,
        relative_threshold_factor: float = 0.72,
        min_peak_intensity: float = 100.0,
        min_component_area: int = 12,
    ):
        self.relative_threshold_factor = relative_threshold_factor
        self.min_peak_intensity = min_peak_intensity
        self.min_component_area = min_component_area

    def analyze(self, frame: np.ndarray) -> LaserSpotMeasurement:
        gray = to_gray(frame)
        blurred = mean_blur_3x3(gray)
        normalized = percentile_normalize(blurred)
        peak_intensity = float(blurred.max()) if blurred.size else 0.0
        threshold_value = float(max(normalized.max() * self.relative_threshold_factor, 180.0))
        mask = normalized >= threshold_value
        coords = largest_connected_component(mask)

        debug_frame = self._build_debug_frame(gray, mask, coords)

        if peak_intensity < self.min_peak_intensity or len(coords) < self.min_component_area:
            return LaserSpotMeasurement(
                is_detected=False,
                spot_area=0.0,
                spot_sum_intensity=0.0,
                spot_centroid=None,
                peak_intensity=peak_intensity,
                threshold_value=threshold_value,
                mask=mask,
                debug_frame=debug_frame,
            )

        ys = coords[:, 0]
        xs = coords[:, 1]
        spot_sum_intensity = float(blurred[ys, xs].sum())
        centroid = (float(xs.mean()), float(ys.mean()))
        debug_frame = draw_cross(debug_frame, centroid, color=(0, 255, 0))

        return LaserSpotMeasurement(
            is_detected=True,
            spot_area=float(len(coords)),
            spot_sum_intensity=spot_sum_intensity,
            spot_centroid=centroid,
            peak_intensity=peak_intensity,
            threshold_value=threshold_value,
            mask=mask,
            debug_frame=debug_frame,
        )

    @staticmethod
    def _build_debug_frame(gray: np.ndarray, mask: np.ndarray, coords: np.ndarray) -> np.ndarray:
        gray_uint8 = np.clip(gray, 0, 255).astype(np.uint8)
        debug = np.stack([gray_uint8, gray_uint8, gray_uint8], axis=-1)
        if mask.any():
            debug[mask] = (0, 140, 255)
        if len(coords):
            debug[coords[:, 0], coords[:, 1]] = (0, 0, 255)
        return debug


class LaserSpotMonitor:
    def __init__(
        self,
        detector: LaserSpotDetector,
        search_roi: Tuple[int, int, int, int],
        baseline_init_frames: int,
        intensity_drop_ratio_threshold: float,
        area_drop_ratio_threshold: float,
        alert_consecutive_frames: int,
        alert_cooldown_seconds: int,
    ):
        self.detector = detector
        self.search_roi = search_roi
        self.baseline_init_frames = baseline_init_frames
        self.minimum_intensity_ratio = 1.0 - intensity_drop_ratio_threshold
        self.minimum_area_ratio = 1.0 - area_drop_ratio_threshold
        self.alert_consecutive_frames = alert_consecutive_frames
        self.alert_cooldown_seconds = alert_cooldown_seconds

        self._baseline_area_samples: list[float] = []
        self._baseline_intensity_samples: list[float] = []
        self.baseline_area: Optional[float] = None
        self.baseline_intensity: Optional[float] = None
        self.consecutive_anomalies = 0
        self.last_alert_timestamp: Optional[float] = None

    @property
    def baseline_ready(self) -> bool:
        return self.baseline_area is not None and self.baseline_intensity is not None

    def process_camera_frame(
        self,
        camera_frame: np.ndarray,
        now_timestamp: Optional[float] = None,
    ) -> Tuple[SpotMonitorEvent, np.ndarray]:
        current_ts = time.time() if now_timestamp is None else now_timestamp
        search_frame = crop_frame(camera_frame, self.search_roi, "SPOT_SEARCH_ROI")
        measurement = self.detector.analyze(search_frame)

        if not self.baseline_ready:
            if measurement.is_detected:
                self._baseline_area_samples.append(measurement.spot_area)
                self._baseline_intensity_samples.append(measurement.spot_sum_intensity)

                if len(self._baseline_area_samples) >= self.baseline_init_frames:
                    self.baseline_area = float(np.median(self._baseline_area_samples))
                    self.baseline_intensity = float(np.median(self._baseline_intensity_samples))
                    status = "baseline_ready"
                    reason = (
                        f"激光点基线建立完成: intensity={self.baseline_intensity:.1f}, "
                        f"area={self.baseline_area:.1f}"
                    )
                else:
                    status = "warming_up"
                    reason = (
                        f"正在建立激光点基线 "
                        f"({len(self._baseline_area_samples)}/{self.baseline_init_frames})"
                    )
            else:
                status = "warming_up"
                reason = (
                    "正在建立激光点基线，但当前帧未检测到亮点 "
                    f"({len(self._baseline_area_samples)}/{self.baseline_init_frames})"
                )

            return SpotMonitorEvent(
                status=status,
                reason=reason,
                measurement=measurement,
                baseline_progress=len(self._baseline_area_samples),
                baseline_target=self.baseline_init_frames,
            ), search_frame

        intensity_ratio = safe_ratio(measurement.spot_sum_intensity, self.baseline_intensity)
        area_ratio = safe_ratio(measurement.spot_area, self.baseline_area)

        abnormal_reasons: list[str] = []
        if not measurement.is_detected:
            abnormal_reasons.append("未检测到激光亮点")
        else:
            if intensity_ratio < self.minimum_intensity_ratio:
                abnormal_reasons.append(f"亮度降至基线 {intensity_ratio:.1%}")
            if area_ratio < self.minimum_area_ratio:
                abnormal_reasons.append(f"面积降至基线 {area_ratio:.1%}")

        if abnormal_reasons:
            self.consecutive_anomalies += 1
            status = "anomaly_pending"
            should_alert = False
            if (
                self.consecutive_anomalies >= self.alert_consecutive_frames
                and self._cooldown_elapsed(current_ts)
            ):
                self.last_alert_timestamp = current_ts
                status = "alert"
                should_alert = True

            event = SpotMonitorEvent(
                status=status,
                reason="; ".join(abnormal_reasons),
                measurement=measurement,
                baseline_area=self.baseline_area,
                baseline_intensity=self.baseline_intensity,
                area_ratio=area_ratio,
                intensity_ratio=intensity_ratio,
                consecutive_anomalies=self.consecutive_anomalies,
                should_alert=should_alert,
            )
            return event, search_frame

        self.consecutive_anomalies = 0
        return SpotMonitorEvent(
            status="normal",
            reason="激光亮点正常",
            measurement=measurement,
            baseline_area=self.baseline_area,
            baseline_intensity=self.baseline_intensity,
            area_ratio=area_ratio,
            intensity_ratio=intensity_ratio,
        ), search_frame

    def _cooldown_elapsed(self, current_ts: float) -> bool:
        if self.last_alert_timestamp is None:
            return True
        return (current_ts - self.last_alert_timestamp) >= self.alert_cooldown_seconds


# =========================================================
# 飞书消息发送
# =========================================================
class FeishuMessenger:
    def __init__(self, app_id: str, app_secret: str, log_level: str = "INFO"):
        require_dependency("lark_oapi", lark)

        level_map = {
            "DEBUG": lark.LogLevel.DEBUG,
            "INFO": lark.LogLevel.INFO,
            "WARNING": lark.LogLevel.WARNING,
            "ERROR": lark.LogLevel.ERROR,
        }

        self.client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(level_map.get(log_level.upper(), lark.LogLevel.INFO))
            .build()
        )

    def upload_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            request = (
                CreateImageRequest.builder()
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(f)
                    .build()
                )
                .build()
            )

            response = self.client.im.v1.image.create(request)

        if not response.success():
            raise RuntimeError(
                f"上传图片失败: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )

        return response.data.image_key

    def send_text(self, receive_id_type: str, receive_id: str, text: str) -> None:
        content = json.dumps({"text": text}, ensure_ascii=False)

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("text")
                .content(content)
                .build()
            )
            .build()
        )

        response = self.client.im.v1.message.create(request)

        if not response.success():
            raise RuntimeError(
                f"发送文本失败: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )

    def send_image(self, receive_id_type: str, receive_id: str, image_path: str) -> None:
        image_key = self.upload_image(image_path)
        content = json.dumps({"image_key": image_key}, ensure_ascii=False)

        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("image")
                .content(content)
                .build()
            )
            .build()
        )

        response = self.client.im.v1.message.create(request)

        if not response.success():
            raise RuntimeError(
                f"发送图片失败: code={response.code}, msg={response.msg}, log_id={response.get_log_id()}"
            )


# =========================================================
# 截图
# =========================================================
class ScreenCapturer:
    def __init__(self, roi: Optional[Tuple[int, int, int, int]] = None):
        require_dependency("mss", mss)
        self.roi = roi
        self.sct = mss.mss()

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
    capturer = ScreenCapturer(cfg["ROI"])
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


def validate_config(cfg: dict) -> None:
    required = ["APP_ID", "APP_SECRET", "RECEIVE_ID_TYPE", "RECEIVE_ID"]
    for key in required:
        if not cfg.get(key):
            raise ValueError(f"缺少配置项: {key}")

    if cfg["RECEIVE_ID_TYPE"] not in {"open_id", "chat_id"}:
        raise ValueError("RECEIVE_ID_TYPE 只能是 open_id 或 chat_id")

    positive_int_keys = [
        "INTERVAL_SECONDS",
        "DETECT_INTERVAL_SECONDS",
        "BASELINE_INIT_FRAMES",
        "ALERT_CONSECUTIVE_FRAMES",
        "ALERT_COOLDOWN_SECONDS",
    ]
    for key in positive_int_keys:
        if cfg[key] <= 0:
            raise ValueError(f"{key} 必须大于 0")

    ratio_keys = [
        "INTENSITY_DROP_RATIO_THRESHOLD",
        "AREA_DROP_RATIO_THRESHOLD",
    ]
    for key in ratio_keys:
        if not 0 < cfg[key] < 1:
            raise ValueError(f"{key} 必须在 0 和 1 之间")

    validate_roi(cfg.get("ROI"), "ROI")
    validate_roi(cfg.get("CAMERA_ROI"), "CAMERA_ROI")
    validate_roi(cfg.get("SPOT_SEARCH_ROI"), "SPOT_SEARCH_ROI")

    camera_roi = cfg.get("CAMERA_ROI")
    search_roi = cfg.get("SPOT_SEARCH_ROI")
    if (camera_roi is None) != (search_roi is None):
        raise ValueError("CAMERA_ROI 和 SPOT_SEARCH_ROI 必须同时配置，或同时留空")


def build_alert_visual(
    camera_frame: np.ndarray,
    search_roi: Tuple[int, int, int, int],
    event: SpotMonitorEvent,
) -> np.ndarray:
    camera_vis = draw_rectangle(camera_frame, search_roi, color=(0, 255, 255), thickness=2)
    debug_frame = event.measurement.debug_frame
    target_height = camera_vis.shape[0]
    target_width = max(1, int(debug_frame.shape[1] * target_height / max(1, debug_frame.shape[0])))
    debug_vis = resize_nearest(debug_frame, target_height, target_width)

    gap = 20
    canvas = np.zeros(
        (target_height, camera_vis.shape[1] + gap + debug_vis.shape[1], 3),
        dtype=np.uint8,
    )
    canvas[:, :camera_vis.shape[1]] = camera_vis
    canvas[:, camera_vis.shape[1] + gap:] = debug_vis

    lines = [
        f"time: {now_str()}",
        "mode: laser spot alert",
        event.reason,
    ]
    if event.intensity_ratio is not None:
        lines.append(f"intensity_ratio: {event.intensity_ratio:.1%}")
    if event.area_ratio is not None:
        lines.append(f"area_ratio: {event.area_ratio:.1%}")

    return annotate_frame(canvas, lines)


def build_alert_text(event: SpotMonitorEvent) -> str:
    lines = [
        "激光亮点异常报警",
        f"时间: {now_str()}",
        f"原因: {event.reason}",
    ]
    if event.intensity_ratio is not None:
        lines.append(f"亮度比例: {event.intensity_ratio:.1%}")
    if event.area_ratio is not None:
        lines.append(f"面积比例: {event.area_ratio:.1%}")
    lines.append(f"连续异常帧: {event.consecutive_anomalies}")
    return "\n".join(lines)


def send_scheduled_screenshot(
    messenger: FeishuMessenger,
    frame: np.ndarray,
    cfg: dict,
    latest_detection_note: str,
) -> None:
    image_path = make_output_path(cfg["SAVE_DIR"], prefix="screenshot")
    note_lines = [
        f"time: {now_str()}",
        "mode: scheduled screenshot",
    ]
    if latest_detection_note:
        note_lines.append(latest_detection_note)

    vis = annotate_frame(frame, note_lines)
    ScreenCapturer.save(vis, image_path)

    if cfg["SEND_TEXT_BEFORE_IMAGE"]:
        messenger.send_text(
            cfg["RECEIVE_ID_TYPE"],
            cfg["RECEIVE_ID"],
            f"{cfg['TEXT_PREFIX']}\n时间: {now_str()}",
        )

    messenger.send_image(
        cfg["RECEIVE_ID_TYPE"],
        cfg["RECEIVE_ID"],
        image_path,
    )

    print(f"[{now_str()}] 已发送截图: {image_path}")
    append_log(cfg["SAVE_DIR"], f"已发送截图: {image_path}")


def send_alert(
    messenger: FeishuMessenger,
    cfg: dict,
    camera_frame: np.ndarray,
    event: SpotMonitorEvent,
) -> None:
    alert_path = make_output_path(cfg["SAVE_DIR"], prefix="laser_alert")
    alert_visual = build_alert_visual(camera_frame, cfg["SPOT_SEARCH_ROI"], event)
    ScreenCapturer.save(alert_visual, alert_path)

    messenger.send_text(
        cfg["RECEIVE_ID_TYPE"],
        cfg["RECEIVE_ID"],
        build_alert_text(event),
    )
    messenger.send_image(
        cfg["RECEIVE_ID_TYPE"],
        cfg["RECEIVE_ID"],
        alert_path,
    )

    append_log(
        cfg["SAVE_DIR"],
        (
            "激光点异常报警: "
            f"{event.reason}, intensity_ratio={event.intensity_ratio}, area_ratio={event.area_ratio}, "
            f"image={alert_path}"
        ),
    )


# =========================================================
# 主程序
# =========================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="定时截屏并监控激光亮点异常")
    parser.add_argument(
        "--select-roi",
        action="store_true",
        help="交互式框选 CAMERA_ROI 和 SPOT_SEARCH_ROI，并保存到 config.local.json",
    )
    return parser.parse_args()


def run_sender(cfg: dict) -> None:
    validate_config(cfg)

    messenger = FeishuMessenger(
        app_id=cfg["APP_ID"],
        app_secret=cfg["APP_SECRET"],
        log_level=cfg["LOG_LEVEL"],
    )
    capturer = ScreenCapturer(cfg["ROI"])

    monitor = None
    latest_detection_note = "laser: detection disabled"
    last_detection_status = None
    if detection_enabled(cfg):
        monitor = LaserSpotMonitor(
            detector=LaserSpotDetector(),
            search_roi=cfg["SPOT_SEARCH_ROI"],
            baseline_init_frames=cfg["BASELINE_INIT_FRAMES"],
            intensity_drop_ratio_threshold=cfg["INTENSITY_DROP_RATIO_THRESHOLD"],
            area_drop_ratio_threshold=cfg["AREA_DROP_RATIO_THRESHOLD"],
            alert_consecutive_frames=cfg["ALERT_CONSECUTIVE_FRAMES"],
            alert_cooldown_seconds=cfg["ALERT_COOLDOWN_SECONDS"],
        )
        latest_detection_note = "laser: warming up"

    append_log(cfg["SAVE_DIR"], "程序启动")
    append_log(
        cfg["SAVE_DIR"],
        "激光点检测状态: 已启用" if monitor is not None else "激光点检测状态: 未启用",
    )

    next_screenshot_at = time.monotonic()
    next_detect_at = time.monotonic() if monitor is not None else float("inf")

    while True:
        now_monotonic = time.monotonic()
        due_screenshot = now_monotonic >= next_screenshot_at
        due_detect = monitor is not None and now_monotonic >= next_detect_at

        if not due_screenshot and not due_detect:
            sleep_for = min(next_screenshot_at, next_detect_at) - now_monotonic
            time.sleep(max(0.2, min(1.0, sleep_for)))
            continue

        try:
            frame = capturer.capture()
        except Exception as e:
            err = f"截图失败: {repr(e)}"
            print(f"[{now_str()}] {err}")
            append_log(cfg["SAVE_DIR"], err)
            time.sleep(1)
            continue

        if due_detect and monitor is not None:
            try:
                camera_frame = crop_frame(frame, cfg["CAMERA_ROI"], "CAMERA_ROI")
                event, _ = monitor.process_camera_frame(camera_frame)
                latest_detection_note = f"laser: {event.status}"

                if event.status != last_detection_status:
                    append_log(cfg["SAVE_DIR"], f"激光点状态变更: {event.status} - {event.reason}")
                    last_detection_status = event.status

                if event.should_alert:
                    send_alert(messenger, cfg, camera_frame, event)
            except Exception as e:
                err = f"激光点检测失败: {repr(e)}"
                print(f"[{now_str()}] {err}")
                append_log(cfg["SAVE_DIR"], err)
                latest_detection_note = "laser: error"
            finally:
                next_detect_at = time.monotonic() + cfg["DETECT_INTERVAL_SECONDS"]

        if due_screenshot:
            try:
                send_scheduled_screenshot(messenger, frame, cfg, latest_detection_note)
            except Exception as e:
                err = f"发送失败: {repr(e)}"
                print(f"[{now_str()}] {err}")
                append_log(cfg["SAVE_DIR"], err)
            finally:
                next_screenshot_at = time.monotonic() + cfg["INTERVAL_SECONDS"]


def main() -> None:
    args = parse_args()
    cfg = load_runtime_config()

    if args.select_roi:
        run_roi_selector(cfg)
        return

    run_sender(cfg)


if __name__ == "__main__":
    main()
