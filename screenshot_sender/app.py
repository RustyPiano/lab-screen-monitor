import argparse
import json
import signal
import time
from pathlib import Path
from typing import Optional

import numpy as np

from .capture import ScreenCapturer, run_roi_selector
from .common import (
    DEFAULT_LOG_PATH,
    append_log,
    cleanup_old_files,
    get_logger,
    make_output_path,
    now_str,
    setup_logging,
)
from .config import (
    CONFIG_OVERRIDE_PATH,
    detection_enabled,
    get_config_write_path,
    load_runtime_config,
    resolve_config_path,
    validate_config,
)
from .image_ops import crop_frame
from .laser import (
    LaserSpotDetector,
    LaserSpotMonitor,
    SpotMonitorEvent,
    build_alert_text,
    build_alert_visual,
)
from .messaging import Messenger, build_messenger


def load_config_from_args(config_arg: Optional[str]) -> tuple[dict, Optional[Path]]:
    resolved_path = resolve_config_path(config_arg)
    if config_arg is not None and resolved_path is not None and not resolved_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {resolved_path}")
    return load_runtime_config(config_arg), resolved_path


def check_runtime(cfg: dict) -> None:
    validate_config(cfg)
    build_messenger(cfg)

    with ScreenCapturer(cfg["ROI"]) as capturer:
        frame = capturer.capture()
    if detection_enabled(cfg):
        camera_frame = crop_frame(frame, cfg["CAMERA_ROI"], "CAMERA_ROI")
        crop_frame(camera_frame, cfg["SPOT_SEARCH_ROI"], "SPOT_SEARCH_ROI")

    save_dir = Path(cfg["SAVE_DIR"])
    save_dir.mkdir(parents=True, exist_ok=True)


def build_runtime_summary(
    cfg: dict,
    *,
    mode: str,
    config_path: Optional[Path],
    log_path: Path,
) -> list[str]:
    return [
        f"运行模式: {mode}",
        f"推送渠道: {cfg['PUSH_PROVIDER']}",
        f"整屏截图间隔: {cfg['INTERVAL_SECONDS']} 秒",
        f"激光检测: {'启用' if detection_enabled(cfg) else '禁用'}",
        f"配置文件: {config_path if config_path is not None else '内置默认配置'}",
        f"日志文件: {log_path}",
    ]


def log_runtime_summary(
    cfg: dict,
    *,
    mode: str,
    config_path: Optional[Path],
    log_path: Path,
) -> None:
    logger = get_logger()
    for line in build_runtime_summary(cfg, mode=mode, config_path=config_path, log_path=log_path):
        logger.info(line)


def send_scheduled_screenshot(
    messenger: Messenger,
    frame: np.ndarray,
    cfg: dict,
    latest_detection_note: str,
) -> None:
    del latest_detection_note
    image_path = make_output_path(cfg["SAVE_DIR"], prefix="screenshot")
    ScreenCapturer.save(frame, image_path)

    if cfg["SEND_TEXT_BEFORE_IMAGE"]:
        messenger.send_text(f"{cfg['TEXT_PREFIX']}\n时间: {now_str()}")

    messenger.send_image(image_path)

    append_log(f"已发送截图: {image_path}")


def build_detection_note(cfg: dict, frame: np.ndarray) -> str:
    del frame
    if not detection_enabled(cfg):
        return "laser: detection disabled"
    return "laser: single-shot mode (no baseline)"


def send_alert(
    messenger: Messenger,
    cfg: dict,
    camera_frame: np.ndarray,
    event: SpotMonitorEvent,
) -> None:
    alert_path = make_output_path(cfg["SAVE_DIR"], prefix="laser_alert")
    alert_visual = build_alert_visual(camera_frame, cfg["SPOT_SEARCH_ROI"], event)
    ScreenCapturer.save(alert_visual, alert_path)

    messenger.send_text(build_alert_text(event))
    messenger.send_image(alert_path)

    append_log(
        "激光点异常报警: "
        f"{event.reason}, intensity_ratio={event.intensity_ratio}, area_ratio={event.area_ratio}, "
        f"image={alert_path}"
    )


def send_recovery_notification(messenger: Messenger) -> None:
    messenger.send_text(f"激光亮点已恢复正常\n时间: {now_str()}")


def run_once(cfg: dict) -> None:
    validate_config(cfg)

    messenger = build_messenger(cfg)
    with ScreenCapturer(cfg["ROI"]) as capturer:
        frame = capturer.capture()
    detection_note = build_detection_note(cfg, frame)
    send_scheduled_screenshot(messenger, frame, cfg, detection_note)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="定时截屏并监控激光亮点异常")
    parser.add_argument(
        "--config",
        help="指定配置文件路径，默认读取项目根目录的 config.local.json",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--select-roi",
        action="store_true",
        help="交互式框选 CAMERA_ROI 和 SPOT_SEARCH_ROI，并保存回当前配置文件",
    )
    mode_group.add_argument(
        "--check",
        action="store_true",
        help="检查配置、依赖、截图和 ROI 是否可用，然后退出",
    )
    mode_group.add_argument(
        "--once",
        action="store_true",
        help="发送一次截图用于验收，然后退出",
    )
    return parser.parse_args(argv)


def run_sender(cfg: dict) -> None:
    validate_config(cfg)

    messenger = build_messenger(cfg)
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

    append_log("程序启动")
    append_log("激光点检测状态: 已启用" if monitor is not None else "激光点检测状态: 未启用")
    cleanup_old_files(cfg["SAVE_DIR"])

    next_screenshot_at = time.monotonic()
    next_detect_at = time.monotonic() if monitor is not None else float("inf")
    shutdown = False
    capture_fail_count = 0
    max_capture_backoff = 60

    def handle_signal(signum, frame) -> None:
        del signum, frame
        nonlocal shutdown
        shutdown = True

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except ValueError:
        pass

    with ScreenCapturer(cfg["ROI"]) as capturer:
        while not shutdown:
            now_monotonic = time.monotonic()
            due_screenshot = now_monotonic >= next_screenshot_at
            due_detect = monitor is not None and now_monotonic >= next_detect_at

            if not due_screenshot and not due_detect:
                sleep_for = min(next_screenshot_at, next_detect_at) - now_monotonic
                time.sleep(max(0.2, min(1.0, sleep_for)))
                continue

            logger = get_logger()

            try:
                frame = capturer.capture()
                capture_fail_count = 0
            except Exception as e:
                capture_fail_count += 1
                backoff = min(max_capture_backoff, 2 ** capture_fail_count)
                logger.error(f"截图失败 (第{capture_fail_count}次): {e}, {backoff}秒后重试")
                time.sleep(backoff)
                continue

            if due_detect and monitor is not None:
                try:
                    camera_frame = crop_frame(frame, cfg["CAMERA_ROI"], "CAMERA_ROI")
                    event, _ = monitor.process_camera_frame(camera_frame)
                    latest_detection_note = f"laser: {event.status}"

                    if event.status != last_detection_status:
                        append_log(f"激光点状态变更: {event.status} - {event.reason}")
                        last_detection_status = event.status

                    if event.should_alert:
                        send_alert(messenger, cfg, camera_frame, event)
                    elif event.status == "recovered":
                        send_recovery_notification(messenger)
                except Exception as e:
                    err = f"激光点检测失败: {e}"
                    logger.error(err)
                    latest_detection_note = "laser: error"
                finally:
                    next_detect_at = time.monotonic() + cfg["DETECT_INTERVAL_SECONDS"]

            if due_screenshot:
                try:
                    send_scheduled_screenshot(messenger, frame, cfg, latest_detection_note)
                    cleanup_old_files(cfg["SAVE_DIR"])
                except Exception as e:
                    err = f"发送失败: {e}"
                    logger.error(err)
                finally:
                    next_screenshot_at = time.monotonic() + cfg["INTERVAL_SECONDS"]

    append_log("程序退出")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    try:
        cfg, config_path = load_config_from_args(args.config)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"配置加载失败: {e}")
        return 1

    log_path = setup_logging(DEFAULT_LOG_PATH, cfg.get("LOG_LEVEL", "INFO"))
    logger = get_logger()

    try:
        if args.select_roi:
            log_runtime_summary(cfg, mode="select-roi", config_path=config_path, log_path=log_path)
            run_roi_selector(cfg, config_path=get_config_write_path(args.config))
            return 0

        if args.check:
            log_runtime_summary(cfg, mode="check", config_path=config_path, log_path=log_path)
            check_runtime(cfg)
            logger.info("检查通过")
            return 0

        if args.once:
            log_runtime_summary(cfg, mode="once", config_path=config_path, log_path=log_path)
            run_once(cfg)
            return 0

        log_runtime_summary(cfg, mode="run", config_path=config_path, log_path=log_path)
        run_sender(cfg)
        return 0
    except Exception as e:
        logger.error(f"运行失败: {e}")
        return 1
