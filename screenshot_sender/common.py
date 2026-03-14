import logging
import sys
from datetime import datetime
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

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return log_path


def make_output_path(save_dir: str | Path, prefix: str = "screenshot") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(save_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir / f"{prefix}_{ts}.png")


def append_log(save_dir: str, text: str) -> None:
    del save_dir
    get_logger().info(text)
