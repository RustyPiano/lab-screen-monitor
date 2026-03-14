import json
import logging
from pathlib import Path
from typing import Optional, Tuple

from .common import DEFAULT_SCREENSHOT_DIR, PROJECT_ROOT

CONFIG = {
    # 推送渠道: "feishu" 或 "wecom"
    "PUSH_PROVIDER": "feishu",

    # 飞书应用信息
    "APP_ID": "",
    "APP_SECRET": "",

    # 接收对象
    # 发给个人：open_id
    # 发给群：chat_id
    "RECEIVE_ID_TYPE": "chat_id",
    "RECEIVE_ID": "",

    # 企业微信机器人 webhook
    "WECOM_WEBHOOK_URL": "",

    # 定时发送整屏截图的间隔（秒）
    "INTERVAL_SECONDS": 1800,

    # 截图区域
    # None 表示全屏
    # (left, top, width, height) 表示指定区域
    # 注意：CAMERA_ROI 是相对于这里截下来的图像坐标
    "ROI": None,

    # 相机窗口区域（相对于 ROI 截图后的图像坐标）
    "CAMERA_ROI": None,

    # 激光亮点搜索区域（相对于 CAMERA_ROI 的图像坐标）
    "SPOT_SEARCH_ROI": None,

    # 激光点检测间隔（秒）
    "DETECT_INTERVAL_SECONDS": 5,

    # 建立正常基线时采样的帧数，建议 10-20
    "BASELINE_INIT_FRAMES": 15,

    # 亮度或面积比基线降低多少算异常
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
    "SAVE_DIR": str(DEFAULT_SCREENSHOT_DIR),

    # 日志级别
    "LOG_LEVEL": "INFO",
}

CONFIG_OVERRIDE_PATH = PROJECT_ROOT / "config.local.json"
CONFIG_TEMPLATE_PATH = PROJECT_ROOT / "config.example.json"
ROI_CONFIG_KEYS = ("ROI", "CAMERA_ROI", "SPOT_SEARCH_ROI")


def normalize_config_overrides(overrides: dict) -> dict:
    normalized = dict(overrides)
    for key in ROI_CONFIG_KEYS:
        value = normalized.get(key)
        if value is None:
            continue
        if not isinstance(value, (list, tuple)):
            raise ValueError(
                f"{key} 必须是 [left, top, width, height] 数组，当前值: {value!r}"
            )
        normalized[key] = tuple(int(part) for part in value)
    return normalized


def build_runtime_config(base_config: dict, overrides: Optional[dict] = None) -> dict:
    merged = dict(base_config)
    if overrides:
        merged.update(normalize_config_overrides(overrides))
    return merged


def resolve_config_path(config_path: Optional[Path | str] = None) -> Optional[Path]:
    if config_path is not None:
        return Path(config_path).expanduser().resolve()
    if CONFIG_OVERRIDE_PATH.exists():
        return CONFIG_OVERRIDE_PATH
    return None


def load_runtime_config(config_path: Optional[Path | str] = None) -> dict:
    resolved_path = resolve_config_path(config_path)
    if resolved_path is None or not resolved_path.exists():
        return dict(CONFIG)

    with open(resolved_path, "r", encoding="utf-8") as f:
        overrides = json.load(f)
    return build_runtime_config(CONFIG, overrides)


def get_config_write_path(config_path: Optional[Path | str] = None) -> Path:
    if config_path is None:
        return CONFIG_OVERRIDE_PATH
    return Path(config_path).expanduser().resolve()


def save_config_overrides(overrides: dict, config_path: Optional[Path | str] = None) -> None:
    resolved_path = get_config_write_path(config_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    current_overrides = {}
    if resolved_path.exists():
        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                current_overrides = json.load(f)
        except json.JSONDecodeError:
            backup = resolved_path.with_suffix(".json.bak")
            resolved_path.rename(backup)
            logging.getLogger("screenshot_sender").warning(
                f"配置文件损坏，已备份到 {backup}，将从空配置开始"
            )

    current_overrides.update(overrides)
    serializable = {}
    for key, value in current_overrides.items():
        if key in ROI_CONFIG_KEYS and value is not None:
            serializable[key] = list(value)
        else:
            serializable[key] = value

    with open(resolved_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
        f.write("\n")


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


def detection_enabled(cfg: dict) -> bool:
    return cfg.get("CAMERA_ROI") is not None and cfg.get("SPOT_SEARCH_ROI") is not None


def validate_config(cfg: dict) -> None:
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR"}
    log_level = str(cfg.get("LOG_LEVEL", "INFO")).upper()
    if log_level not in valid_levels:
        raise ValueError(f"LOG_LEVEL 必须是 {valid_levels} 之一")

    provider = cfg.get("PUSH_PROVIDER")
    if provider not in {"feishu", "wecom"}:
        raise ValueError("PUSH_PROVIDER 只能是 feishu 或 wecom")

    if provider == "feishu":
        required = ["APP_ID", "APP_SECRET", "RECEIVE_ID_TYPE", "RECEIVE_ID"]
        for key in required:
            if not cfg.get(key):
                raise ValueError(f"缺少配置项: {key}")

        if cfg["RECEIVE_ID_TYPE"] not in {"open_id", "chat_id"}:
            raise ValueError("RECEIVE_ID_TYPE 只能是 open_id 或 chat_id")
    elif not cfg.get("WECOM_WEBHOOK_URL"):
        raise ValueError("缺少配置项: WECOM_WEBHOOK_URL")

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

    save_dir = Path(cfg.get("SAVE_DIR", DEFAULT_SCREENSHOT_DIR))
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"SAVE_DIR 路径无效或不可写: {save_dir}: {e}") from e

    camera_roi = cfg.get("CAMERA_ROI")
    search_roi = cfg.get("SPOT_SEARCH_ROI")
    if (camera_roi is None) != (search_roi is None):
        raise ValueError("CAMERA_ROI 和 SPOT_SEARCH_ROI 必须同时配置，或同时留空")
