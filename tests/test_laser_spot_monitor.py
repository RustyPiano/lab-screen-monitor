import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

import feishu_screenshot_sender as sender


def make_spot_frame(
    size: int = 64,
    center: tuple[int, int] = (32, 32),
    radius: int = 6,
    peak: int = 230,
    background: int = 20,
    noise: float = 0.0,
) -> np.ndarray:
    yy, xx = np.ogrid[:size, :size]
    cx, cy = center
    dist_sq = (xx - cx) ** 2 + (yy - cy) ** 2

    frame = np.full((size, size), background, dtype=np.float32)
    if radius > 0 and peak > background:
        core_mask = dist_sq <= radius ** 2
        halo_mask = (dist_sq <= (radius + 2) ** 2) & ~core_mask
        frame[core_mask] = peak
        frame[halo_mask] = max(background, peak * 0.45)

    if noise > 0:
        rng = np.random.default_rng(20260314)
        frame += rng.normal(0.0, noise, size=frame.shape)

    frame = np.clip(frame, 0, 255).astype(np.uint8)
    return np.repeat(frame[..., None], 3, axis=2)


def build_monitor() -> sender.LaserSpotMonitor:
    detector = sender.LaserSpotDetector(
        relative_threshold_factor=0.72,
        min_peak_intensity=60.0,
        min_component_area=8,
    )
    return sender.LaserSpotMonitor(
        detector=detector,
        search_roi=(0, 0, 64, 64),
        baseline_init_frames=5,
        intensity_drop_ratio_threshold=0.40,
        area_drop_ratio_threshold=0.40,
        alert_consecutive_frames=3,
        alert_cooldown_seconds=30,
    )


def prime_baseline(monitor: sender.LaserSpotMonitor) -> None:
    for ts in range(5):
        event, _ = monitor.process_camera_frame(make_spot_frame(), now_timestamp=float(ts))
    assert monitor.baseline_ready
    assert event.status == "baseline_ready"


class LaserSpotDetectorTests(unittest.TestCase):
    def test_detector_finds_bright_spot(self) -> None:
        detector = sender.LaserSpotDetector(
            relative_threshold_factor=0.72,
            min_peak_intensity=60.0,
            min_component_area=8,
        )
        measurement = detector.analyze(make_spot_frame())

        self.assertTrue(measurement.is_detected)
        self.assertGreater(measurement.spot_area, 50)
        self.assertGreater(measurement.spot_sum_intensity, 1000)
        self.assertIsNotNone(measurement.spot_centroid)
        self.assertAlmostEqual(measurement.spot_centroid[0], 32.0, delta=1.5)
        self.assertAlmostEqual(measurement.spot_centroid[1], 32.0, delta=1.5)


class ConfigOverrideTests(unittest.TestCase):
    def test_build_runtime_config_converts_roi_lists_to_tuples(self) -> None:
        runtime = sender.build_runtime_config(
            {"ROI": None, "CAMERA_ROI": None, "SPOT_SEARCH_ROI": None},
            {
                "CAMERA_ROI": [10, 20, 30, 40],
                "SPOT_SEARCH_ROI": [1, 2, 3, 4],
            },
        )

        self.assertEqual(runtime["CAMERA_ROI"], (10, 20, 30, 40))
        self.assertEqual(runtime["SPOT_SEARCH_ROI"], (1, 2, 3, 4))

    def test_save_config_overrides_serializes_tuples_as_lists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.local.json"
            sender.save_config_overrides(
                {
                    "CAMERA_ROI": (11, 22, 33, 44),
                    "SPOT_SEARCH_ROI": (5, 6, 7, 8),
                },
                config_path=config_path,
            )

            runtime = sender.load_runtime_config(config_path)

        self.assertEqual(runtime["CAMERA_ROI"], (11, 22, 33, 44))
        self.assertEqual(runtime["SPOT_SEARCH_ROI"], (5, 6, 7, 8))


class LaserSpotMonitorTests(unittest.TestCase):
    def test_normal_variation_does_not_alert(self) -> None:
        monitor = build_monitor()
        prime_baseline(monitor)

        last_event = None
        for ts in range(5, 8):
            frame = make_spot_frame(center=(33, 32), peak=220, noise=2.0)
            last_event, _ = monitor.process_camera_frame(frame, now_timestamp=float(ts))
            self.assertFalse(last_event.should_alert)

        self.assertIsNotNone(last_event)
        self.assertEqual(last_event.status, "normal")
        self.assertEqual(monitor.consecutive_anomalies, 0)

    def test_dim_spot_triggers_alert_after_three_frames(self) -> None:
        monitor = build_monitor()
        prime_baseline(monitor)

        events = []
        for ts in range(5, 8):
            event, _ = monitor.process_camera_frame(
                make_spot_frame(peak=95),
                now_timestamp=float(ts),
            )
            events.append(event)

        self.assertEqual(events[0].status, "anomaly_pending")
        self.assertEqual(events[1].status, "anomaly_pending")
        self.assertEqual(events[2].status, "alert")
        self.assertTrue(events[2].should_alert)
        self.assertIn("亮度", events[2].reason)

    def test_smaller_spot_triggers_area_alert(self) -> None:
        monitor = build_monitor()
        prime_baseline(monitor)

        final_event = None
        for ts in range(5, 8):
            final_event, _ = monitor.process_camera_frame(
                make_spot_frame(radius=3),
                now_timestamp=float(ts),
            )

        self.assertIsNotNone(final_event)
        self.assertEqual(final_event.status, "alert")
        self.assertTrue(final_event.should_alert)
        self.assertIn("面积", final_event.reason)

    def test_missing_spot_triggers_alert(self) -> None:
        monitor = build_monitor()
        prime_baseline(monitor)

        final_event = None
        for ts in range(5, 8):
            final_event, _ = monitor.process_camera_frame(
                make_spot_frame(radius=0, peak=20),
                now_timestamp=float(ts),
            )

        self.assertIsNotNone(final_event)
        self.assertEqual(final_event.status, "alert")
        self.assertTrue(final_event.should_alert)
        self.assertIn("未检测到激光亮点", final_event.reason)

    def test_single_abnormal_frame_resets_after_recovery(self) -> None:
        monitor = build_monitor()
        prime_baseline(monitor)

        event, _ = monitor.process_camera_frame(make_spot_frame(peak=95), now_timestamp=5.0)
        self.assertEqual(event.status, "anomaly_pending")
        self.assertFalse(event.should_alert)
        self.assertEqual(monitor.consecutive_anomalies, 1)

        event, _ = monitor.process_camera_frame(make_spot_frame(), now_timestamp=6.0)
        self.assertEqual(event.status, "normal")
        self.assertEqual(monitor.consecutive_anomalies, 0)

        for ts in (7.0, 8.0):
            event, _ = monitor.process_camera_frame(make_spot_frame(peak=95), now_timestamp=ts)
        self.assertEqual(event.status, "anomaly_pending")
        self.assertFalse(event.should_alert)

    def test_cooldown_suppresses_repeat_alerts(self) -> None:
        monitor = build_monitor()
        prime_baseline(monitor)

        first_alert = None
        for ts in range(5, 8):
            first_alert, _ = monitor.process_camera_frame(
                make_spot_frame(radius=0, peak=20),
                now_timestamp=float(ts),
            )
        self.assertTrue(first_alert.should_alert)

        suppressed = []
        for ts in range(8, 11):
            event, _ = monitor.process_camera_frame(
                make_spot_frame(radius=0, peak=20),
                now_timestamp=float(ts),
            )
            suppressed.append(event)

        self.assertTrue(all(not event.should_alert for event in suppressed))


if __name__ == "__main__":
    unittest.main()
