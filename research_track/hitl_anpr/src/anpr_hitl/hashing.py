"""Perceptual hashes (dHash, pHash), content hashes, and fast near-duplicate search."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:
    from scipy.fft import dctn
except ImportError:
    dctn = None


def _gray(img) -> Image.Image:
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img[..., ::-1] if img.ndim == 3 else img)  # OpenCV arrays are BGR
    return img.convert("L")


def dhash(img) -> int:
    """64-bit difference hash: horizontal gradient signs of a 9x8 grayscale thumbnail."""
    px = np.asarray(_gray(img).resize((9, 8), Image.Resampling.BICUBIC), dtype=np.int16)
    bits = (px[:, :-1] < px[:, 1:]).flatten()
    return int(sum(1 << i for i, bit in enumerate(bits) if bit))


def phash(img) -> int:
    """64-bit perceptual hash: low-frequency 8x8 DCT block of a 32x32 thumbnail against its median."""
    px = np.asarray(_gray(img).resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
    low = dctn(px, norm="ortho")[:8, :8].flatten()
    bits = low > np.median(low[1:])  # the DC term would dominate the median
    return int(sum(1 << i for i, bit in enumerate(bits) if bit))


def image_dhash(path: Path) -> int | None:
    """dHash of an image file as it is displayed (EXIF orientation applied); None if unreadable."""
    try:
        with Image.open(path) as img:
            return dhash(ImageOps.exif_transpose(img))
    except Exception:  # noqa: BLE001 - an unreadable file simply has no hash
        return None


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _popcount(x: np.ndarray) -> np.ndarray:
    m1, m2, m4 = np.uint64(0x5555555555555555), np.uint64(0x3333333333333333), np.uint64(0x0F0F0F0F0F0F0F0F)
    x = x - ((x >> np.uint64(1)) & m1)
    x = (x & m2) + ((x >> np.uint64(2)) & m2)
    return ((((x + (x >> np.uint64(4))) & m4) * np.uint64(0x0101010101010101)) >> np.uint64(56)).astype(np.int64)


def near_duplicate_pairs(a: list[int], b: list[int] | None = None, max_bits: int = 6) -> list[tuple[int, int, int]]:
    """(i, j, distance) for hashes within max_bits. With one list, pairs i < j inside it; with two, a[i] vs b[j]."""
    left = np.asarray(a, dtype=np.uint64)
    same = b is None
    right = left if same else np.asarray(b, dtype=np.uint64)
    pairs = []
    for i in range(len(left)):
        start = i + 1 if same else 0
        if start >= len(right):
            continue
        dist = _popcount(np.bitwise_xor(right[start:], left[i]))
        for j in np.nonzero(dist <= max_bits)[0]:
            pairs.append((i, start + int(j), int(dist[j])))
    return pairs


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()
