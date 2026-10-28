"""Bake a triangle array into a signed distance field on a fitted grid.

Baking runs as a generator that yields progress in 0..1 and returns the
result, so the UI can advance it from a modal timer and cancel between steps;
`bake()` drives it to the end for the CLI and tests.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Literal, TypeVar

import numpy as np

from . import cpu_backend, gpu_backend
from .grid import Grid, fit_grid

# Above this the GPU brute force gets slow; callers warn and suggest Decimate.
TRIANGLE_WARN_LIMIT = 50_000

Backend = Literal["AUTO", "GPU", "CPU"]
T = TypeVar("T")
Steps = Generator[float, None, T]


@dataclass(frozen=True)
class BakeSettings:
    resolution: int = 128
    padding: int = 4
    backend: Backend = "AUTO"


@dataclass(frozen=True)
class BakeResult:
    grid: Grid
    distance: np.ndarray  # float32, shape grid.shape, negative inside
    backend: Literal["GPU", "CPU"]
    triangle_count: int
    fallback_reason: str | None = None  # AUTO only: why the GPU was not used


def bake_steps(
    tris: np.ndarray, settings: BakeSettings, on_fallback: Callable[[str], None] | None = None
) -> Steps[BakeResult]:
    """on_fallback is called with the GPU error as soon as AUTO switches to the CPU."""
    if len(tris) == 0:
        raise ValueError("mesh has no faces")

    points = tris.reshape(-1, 3)
    grid = fit_grid(points.min(axis=0), points.max(axis=0), settings.resolution, settings.padding)

    reason = None
    if settings.backend in ("AUTO", "GPU"):
        try:
            distance = yield from gpu_backend.compute_steps(tris, grid)
            return BakeResult(grid, distance, "GPU", len(tris))
        except Exception as e:
            if settings.backend == "GPU":
                raise
            traceback.print_exc()
            reason = f"{type(e).__name__}: {e}"
            if on_fallback:
                on_fallback(reason)

    distance = yield from cpu_backend.compute_steps(tris, grid)
    return BakeResult(grid, distance, "CPU", len(tris), reason)


def run(steps: Steps[T], progress: Callable[[float], None] | None = None) -> T:
    """Drive a step generator to the end and return its result."""
    while True:
        try:
            fraction = next(steps)
        except StopIteration as stop:
            return stop.value
        if progress:
            progress(fraction)


def bake(tris: np.ndarray, settings: BakeSettings, progress: Callable[[float], None] | None = None) -> BakeResult:
    return run(bake_steps(tris, settings), progress)
