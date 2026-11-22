"""Image loading, photo-quality checks and geometric clean-up (crop, straighten, enlarge)."""
from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import SETTINGS
from .datatypes import BadImage, Line


def load_image(data: bytes) -> np.ndarray:
    """Decode bytes to a BGR array, applying the phone's EXIF rotation."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            arr = np.asarray(im)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise BadImage("not_an_image", "the file could not be opened as an image") from exc
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def blur_score(img: np.ndarray) -> float:
    """Variance of the Laplacian at a fixed width: high = sharp edges, low = blurry."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    g = cv2.resize(g, (1000, max(1, int(1000 * h / w))), interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def glare_fraction(img: np.ndarray) -> float:
    """Share of the image covered by blown-out white blobs (flash or lamp reflections) on a photo.
    Small specks are ignored, and clean scans (mostly pure white) are not measured at all."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    if np.median(hsv[:, :, 2]) >= 240:
        return 0.0  # a scan or digital copy: the white is the paper, not a reflection
    mask = ((hsv[:, :, 2] >= 252) & (hsv[:, :, 1] <= 20)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    return float(mask.mean())


def check_quality(img: np.ndarray) -> dict:
    """Reject photos that cannot be read; return measurements and warnings for the rest."""
    h, w = img.shape[:2]
    if min(h, w) < SETTINGS.MIN_SIDE_PX:
        raise BadImage("too_small", f"image is {w}x{h}px; at least {SETTINGS.MIN_SIDE_PX}px per side is needed")
    blur = blur_score(img)
    if blur < SETTINGS.BLUR_REJECT:
        raise BadImage("blurry", f"sharpness {blur:.0f} is below {SETTINGS.BLUR_REJECT:.0f}")
    glare = glare_fraction(img)
    if glare > SETTINGS.GLARE_REJECT:
        raise BadImage("glare", f"{glare:.0%} of the photo is washed out by reflections")
    warnings = []
    if blur < SETTINGS.BLUR_WARN:
        warnings.append("slightly_blurry")
    if glare > SETTINGS.GLARE_REJECT / 3:
        warnings.append("some_glare")
    return {"sharpness": round(blur, 1), "glare_fraction": round(glare, 4), "warnings": warnings,
            "input_size": [int(w), int(h)]}


def _order_corners(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def find_document(img: np.ndarray) -> np.ndarray | None:
    """Corners of the paper or card if it stands out clearly from the background, else None.
    Only a convex four-sided outline covering 25-97% of the photo is accepted, so a page that
    fills the frame (already a 'scan') is left as it is."""
    h, w = img.shape[:2]
    scale = 800 / max(h, w)
    small = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_total = small.shape[0] * small.shape[1]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        area = cv2.contourArea(approx)
        if len(approx) == 4 and cv2.isContourConvex(approx) and 0.25 * area_total < area < 0.97 * area_total:
            return _order_corners(approx / scale)
    return None


def warp_document(img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = corners
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(img, m, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def resize_long_side(img: np.ndarray, target: int, max_up: float = 3.0) -> tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    f = min(max_up, target / max(h, w))
    if abs(f - 1) < 0.05:
        return img, 1.0
    interp = cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA
    return cv2.resize(img, (int(w * f), int(h * f)), interpolation=interp), f


def rotate(img: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate counter-clockwise by angle_deg, growing the canvas so nothing is cut off."""
    if angle_deg % 360 == 0:
        return img
    if angle_deg % 90 == 0:
        k = int(angle_deg // 90) % 4
        return np.ascontiguousarray(np.rot90(img, k))
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def text_skew(lines: list[Line]) -> float:
    """Median slope (degrees) of the longer text lines; positive = text rises to the right."""
    angles = []
    for ln in lines:
        p = ln.box
        dx, dy = p[1][0] - p[0][0], p[1][1] - p[0][1]
        if dx > 3 * ln.h and len(ln.text) >= 6:
            angles.append(np.degrees(np.arctan2(-dy, dx)))
    return float(np.median(angles)) if len(angles) >= 3 else 0.0


def crop_box(img: np.ndarray, x0: float, y0: float, x1: float, y1: float, pad_x: float, pad_y: float) -> np.ndarray:
    h, w = img.shape[:2]
    a, b = int(max(0, x0 - pad_x)), int(max(0, y0 - pad_y))
    c, d = int(min(w, x1 + pad_x)), int(min(h, y1 + pad_y))
    return img[b:d, a:c]
