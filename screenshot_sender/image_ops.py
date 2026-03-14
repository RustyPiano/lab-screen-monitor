from typing import Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


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
