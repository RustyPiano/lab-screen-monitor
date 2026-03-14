import logging
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
DEFAULT_LOG_PATH = RUNTIME_DIR / "sender.log"
DEFAULT_SCREENSHOT_DIR = RUNTIME_DIR / "screenshots"
LOGGER_NAME = "screenshot_sender"


def require_dependency(module_name: str, module_obj) -> None:
    if module_obj is None:
        raise RuntimeError(f"缺少依赖模块: {module_name}")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def setup_logging(log_path: Path = DEFAULT_LOG_PATH, log_level: str = "INFO") -> Path:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = get_logger()
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return log_path


def make_output_path(save_dir: str | Path, prefix: str = "screenshot") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir = Path(save_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir / f"{prefix}_{ts}.jpg")


def append_log(text: str) -> None:
    get_logger().info(text)


def cleanup_old_files(save_dir: str | Path, max_age_days: int = 7) -> None:
    save_path = Path(save_dir)
    if not save_path.exists():
        return

    cutoff = time.time() - (max_age_days * 86400)
    for entry in save_path.iterdir():
        if not entry.is_file():
            continue
        if entry.stat().st_mtime < cutoff:
            entry.unlink()
