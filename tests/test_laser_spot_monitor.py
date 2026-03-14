import json
import unittest
from hashlib import md5
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import numpy as np

import screenshot_sender as sender
import screenshot_sender.app as sender_app
import screenshot_sender.common as sender_common
import screenshot_sender.config as sender_config


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


def make_base_config() -> dict:
    return sender.build_runtime_config(sender.CONFIG)


def write_config(path: Path, overrides: dict) -> None:
    config = make_base_config()
    config.update(overrides)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


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

    def test_save_config_overrides_backs_up_invalid_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.local.json"
            config_path.write_text("{broken", encoding="utf-8")

            sender.save_config_overrides({"CAMERA_ROI": (1, 2, 3, 4)}, config_path=config_path)

            backup_path = config_path.with_suffix(".json.bak")
            self.assertTrue(backup_path.exists())
            runtime = sender.load_runtime_config(config_path)
            self.assertEqual(runtime["CAMERA_ROI"], (1, 2, 3, 4))


class ConfigLoadingTests(unittest.TestCase):
    def test_explicit_config_path_has_priority_over_default_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            default_path = temp_root / "config.local.json"
            explicit_path = temp_root / "custom.json"

            write_config(default_path, {"PUSH_PROVIDER": "wecom", "WECOM_WEBHOOK_URL": "default"})
            write_config(explicit_path, {"PUSH_PROVIDER": "wecom", "WECOM_WEBHOOK_URL": "explicit"})

            with patch.object(sender_config, "CONFIG_OVERRIDE_PATH", default_path):
                runtime = sender.load_runtime_config(explicit_path)

        self.assertEqual(runtime["WECOM_WEBHOOK_URL"], "explicit")

    def test_load_runtime_config_falls_back_to_defaults_when_default_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            missing_default_path = Path(temp_dir) / "missing.json"
            with patch.object(sender_config, "CONFIG_OVERRIDE_PATH", missing_default_path):
                runtime = sender.load_runtime_config()

        self.assertEqual(runtime["PUSH_PROVIDER"], sender.CONFIG["PUSH_PROVIDER"])
        self.assertEqual(runtime["SAVE_DIR"], sender.CONFIG["SAVE_DIR"])

    def test_load_runtime_config_accepts_utf8_bom(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.local.json"
            payload = json.dumps(
                {
                    "PUSH_PROVIDER": "wecom",
                    "WECOM_WEBHOOK_URL": "https://example.invalid/wecom-webhook",
                },
                ensure_ascii=False,
                indent=2,
            )
            config_path.write_text(payload, encoding="utf-8-sig")

            runtime = sender.load_runtime_config(config_path)

        self.assertEqual(runtime["PUSH_PROVIDER"], "wecom")
        self.assertEqual(runtime["WECOM_WEBHOOK_URL"], "https://example.invalid/wecom-webhook")


class MessengerConfigTests(unittest.TestCase):
    def test_validate_config_accepts_feishu_runtime_config(self) -> None:
        cfg = make_base_config()
        cfg["APP_ID"] = "cli_test"
        cfg["APP_SECRET"] = "secret"
        cfg["RECEIVE_ID"] = "oc_test"
        sender.validate_config(cfg)

    def test_validate_config_requires_wecom_webhook(self) -> None:
        cfg = make_base_config()
        cfg["PUSH_PROVIDER"] = "wecom"
        cfg["WECOM_WEBHOOK_URL"] = ""

        with self.assertRaisesRegex(ValueError, "WECOM_WEBHOOK_URL"):
            sender.validate_config(cfg)

    def test_validate_config_accepts_wecom_webhook(self) -> None:
        cfg = make_base_config()
        cfg["PUSH_PROVIDER"] = "wecom"
        cfg["WECOM_WEBHOOK_URL"] = "https://example.invalid/wecom-webhook"
        sender.validate_config(cfg)

    def test_build_messenger_returns_wecom_instance(self) -> None:
        cfg = make_base_config()
        cfg["PUSH_PROVIDER"] = "wecom"
        cfg["WECOM_WEBHOOK_URL"] = "https://example.invalid/wecom-webhook"

        messenger = sender.build_messenger(cfg)

        self.assertIsInstance(messenger, sender.WecomMessenger)

    def test_validate_config_rejects_invalid_log_level(self) -> None:
        cfg = make_base_config()
        cfg["LOG_LEVEL"] = "TRACE"

        with self.assertRaisesRegex(ValueError, "LOG_LEVEL"):
            sender.validate_config(cfg)


class WecomMessengerTests(unittest.TestCase):
    def test_build_image_payload_contains_base64_and_md5(self) -> None:
        image_bytes = b"fake-image-bytes"
        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "image.png"
            image_path.write_bytes(image_bytes)

            payload = sender.WecomMessenger.build_image_payload(str(image_path))

        self.assertEqual(payload["msgtype"], "image")
        self.assertEqual(payload["image"]["md5"], md5(image_bytes).hexdigest())
        self.assertEqual(payload["image"]["base64"], "ZmFrZS1pbWFnZS1ieXRlcw==")


class CliTests(unittest.TestCase):
    def test_main_check_returns_zero_when_runtime_check_succeeds(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            config_path = temp_root / "config.local.json"
            write_config(
                config_path,
                {
                    "PUSH_PROVIDER": "wecom",
                    "WECOM_WEBHOOK_URL": "https://example.invalid/wecom-webhook",
                    "SAVE_DIR": str(temp_root / "screenshots"),
                },
            )

            with patch.object(sender_app, "setup_logging", return_value=temp_root / "sender.log"):
                with patch.object(sender_app, "check_runtime") as mock_check:
                    exit_code = sender.main(["--check", "--config", str(config_path)])

        self.assertEqual(exit_code, 0)
        mock_check.assert_called_once()

    def test_main_once_sends_single_screenshot_when_detection_disabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            config_path = temp_root / "config.local.json"
            write_config(
                config_path,
                {
                    "PUSH_PROVIDER": "wecom",
                    "WECOM_WEBHOOK_URL": "https://example.invalid/wecom-webhook",
                    "SAVE_DIR": str(temp_root / "screenshots"),
                },
            )

            messenger = MagicMock()
            frame = np.zeros((10, 10, 3), dtype=np.uint8)
            capturer = MagicMock()
            capturer.__enter__.return_value = capturer
            capturer.__exit__.return_value = None
            capturer.capture.return_value = frame

            with patch.object(sender_app, "setup_logging", return_value=temp_root / "sender.log"):
                with patch.object(sender_app, "build_messenger", return_value=messenger):
                    with patch.object(sender_app, "ScreenCapturer", return_value=capturer):
                        with patch.object(sender_app.ScreenCapturer, "save", return_value=None):
                            exit_code = sender.main(["--once", "--config", str(config_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(messenger.send_image.call_count, 1)
        self.assertEqual(messenger.send_text.call_count, 1)

    def test_build_detection_note_skips_detection_in_single_shot_mode(self) -> None:
        cfg = make_base_config()
        cfg["CAMERA_ROI"] = (0, 0, 10, 10)
        cfg["SPOT_SEARCH_ROI"] = (0, 0, 5, 5)

        note = sender_app.build_detection_note(cfg, np.zeros((10, 10, 3), dtype=np.uint8))

        self.assertEqual(note, "laser: single-shot mode (no baseline)")

    def test_main_check_returns_one_for_invalid_detection_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            config_path = temp_root / "config.local.json"
            write_config(
                config_path,
                {
                    "PUSH_PROVIDER": "wecom",
                    "WECOM_WEBHOOK_URL": "https://example.invalid/wecom-webhook",
                    "CAMERA_ROI": [0, 0, 10, 10],
                },
            )

            with patch.object(sender_app, "setup_logging", return_value=temp_root / "sender.log"):
                with self.assertLogs(sender_common.LOGGER_NAME, level="ERROR") as logs:
                    exit_code = sender.main(["--check", "--config", str(config_path)])

        self.assertEqual(exit_code, 1)
        self.assertTrue(
            any("CAMERA_ROI 和 SPOT_SEARCH_ROI 必须同时配置" in message for message in logs.output)
        )


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
        self.assertEqual(event.status, "recovered")
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

    def test_alert_resets_consecutive_counter(self) -> None:
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
        self.assertEqual(final_event.consecutive_anomalies, 0)
        self.assertEqual(monitor.consecutive_anomalies, 0)

    def test_recovery_clears_cooldown_for_next_alert_cycle(self) -> None:
        monitor = build_monitor()
        prime_baseline(monitor)

        for ts in range(5, 8):
            event, _ = monitor.process_camera_frame(
                make_spot_frame(radius=0, peak=20),
                now_timestamp=float(ts),
            )
        self.assertTrue(event.should_alert)
        self.assertIsNotNone(monitor.last_alert_timestamp)

        event, _ = monitor.process_camera_frame(make_spot_frame(), now_timestamp=8.0)
        self.assertEqual(event.status, "normal")
        self.assertIsNone(monitor.last_alert_timestamp)

        for ts in (9.0, 10.0, 11.0):
            event, _ = monitor.process_camera_frame(
                make_spot_frame(radius=0, peak=20),
                now_timestamp=ts,
            )

        self.assertEqual(event.status, "alert")
        self.assertTrue(event.should_alert)


class CommonAndImageOpsTests(unittest.TestCase):
    def test_make_output_path_includes_microseconds(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = sender.make_output_path(temp_dir, prefix="shot")

        self.assertRegex(Path(output_path).name, r"^shot_\d{8}_\d{6}_\d{6}\.png$")

    def test_safe_ratio_treats_invalid_baseline_as_neutral(self) -> None:
        self.assertEqual(sender.safe_ratio(10.0, None), 1.0)
        self.assertEqual(sender.safe_ratio(10.0, 0.0), 1.0)

    def test_draw_rectangle_clips_out_of_bounds_roi(self) -> None:
        frame = np.zeros((6, 6, 3), dtype=np.uint8)

        result = sender.draw_rectangle(frame, (-2, -2, 5, 5), color=(255, 0, 0), thickness=1)

        self.assertEqual(int(result[0, 0, 0]), 255)
        self.assertEqual(result.shape, frame.shape)


if __name__ == "__main__":
    unittest.main()
