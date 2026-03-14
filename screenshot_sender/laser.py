import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from .common import now_str
from .image_ops import (
    crop_frame,
    draw_cross,
    draw_rectangle,
    largest_connected_component,
    mean_blur_3x3,
    percentile_normalize,
    resize_nearest,
    safe_ratio,
    to_gray,
)


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
        if cv2 is not None:
            threshold_value, mask_u8 = cv2.threshold(
                normalized,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU,
            )
            threshold_value = float(threshold_value)
            kernel = np.ones((3, 3), dtype=np.uint8)
            mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel)
            mask = mask_u8 > 0
        else:
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
        self.baseline_ema_alpha = 0.01

        self._baseline_area_samples: list[float] = []
        self._baseline_intensity_samples: list[float] = []
        self.baseline_area: Optional[float] = None
        self.baseline_intensity: Optional[float] = None
        self.consecutive_anomalies = 0
        self.last_alert_timestamp: Optional[float] = None

    @property
    def baseline_ready(self) -> bool:
        return (
            self.baseline_area is not None
            and self.baseline_area > 0
            and self.baseline_intensity is not None
            and self.baseline_intensity > 0
        )

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
                self.consecutive_anomalies = 0
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

        was_anomaly = self.consecutive_anomalies > 0
        self.consecutive_anomalies = 0
        if self.last_alert_timestamp is not None:
            self.last_alert_timestamp = None
        if measurement.is_detected:
            self.baseline_area = (
                self.baseline_ema_alpha * measurement.spot_area
                + (1.0 - self.baseline_ema_alpha) * self.baseline_area
            )
            self.baseline_intensity = (
                self.baseline_ema_alpha * measurement.spot_sum_intensity
                + (1.0 - self.baseline_ema_alpha) * self.baseline_intensity
            )
        return SpotMonitorEvent(
            status="recovered" if was_anomaly else "normal",
            reason="激光亮点已恢复正常" if was_anomaly else "激光亮点正常",
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
    return canvas


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
