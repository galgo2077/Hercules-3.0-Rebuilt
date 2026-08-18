"""GPU-accelerated batch computations — cupy when available, numpy fallback."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import numpy.typing as npt

_GPU = False
try:
    import cupy as cp  # type: ignore[import]
    cp.cuda.Device(0).use()
    _GPU = True
except Exception:
    cp = None  # type: ignore[assignment]

_xp = cp if _GPU else np


def backend() -> str:
    return "cuda" if _GPU else "cpu"


def to_device(arr: "npt.ArrayLike") -> "npt.NDArray":
    """Move array to active compute device (GPU or CPU)."""
    a = np.asarray(arr, dtype=np.float64)
    return _xp.asarray(a) if _GPU else a


def to_numpy(arr: "npt.NDArray") -> "npt.NDArray":
    return cp.asnumpy(arr) if _GPU else np.asarray(arr)


def rolling_mean(values: "npt.ArrayLike", window: int) -> "npt.NDArray":
    a = to_device(values)
    out = _xp.full_like(a, _xp.nan)
    kernel = _xp.ones(window) / window
    conv = _xp.convolve(a, kernel, mode="full")[: len(a)]
    out[window - 1 :] = conv[window - 1 :]
    return to_numpy(out)


def rolling_std(values: "npt.ArrayLike", window: int) -> "npt.NDArray":
    a = to_device(values)
    n = len(a)
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        sl = a[i - window + 1 : i + 1]
        out[i] = float(_xp.std(sl))
    return out


def rolling_slope(values: "npt.ArrayLike", window: int) -> "npt.NDArray":
    """Linear regression slope over rolling window — used for slope gate."""
    a = to_device(values)
    n = len(a)
    out = np.full(n, np.nan)
    x = _xp.arange(window, dtype=_xp.float64)
    xm = x - x.mean()
    denom = float((_xp.dot(xm, xm)))
    for i in range(window - 1, n):
        y = a[i - window + 1 : i + 1]
        ym = y - _xp.mean(y)
        out[i] = float(_xp.dot(xm, ym)) / denom
    return out
