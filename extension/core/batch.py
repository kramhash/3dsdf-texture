"""Bake several objects step by step: the modal operator's and the CLI's driver.

`advance()` runs steps until a time budget is spent, so a modal timer can keep
the UI responsive; `cancel()` stops between steps. A failing object is reported
and skipped. Files for an object are written only once its bake completes.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .bake import BakeSettings, Steps
from .export import ExportSettings
from .pipeline import ObjectReport, bake_object_steps, plan_outputs

# report(level, message), level being "INFO", "WARNING" or "ERROR" like bpy reports.
Report = Callable[[str, str], None]


class BatchBake:
    def __init__(
        self,
        objects: Sequence,
        get_depsgraph: Callable[[], object],
        bake_settings: BakeSettings,
        export_settings: ExportSettings,
        out_dir: Path,
        report: Report,
    ) -> None:
        """Raises NameCollisionError before anything is baked."""
        self.objects = list(objects)
        # Names are read up front so reports still work if an object is deleted mid-bake.
        self.names = [o.name for o in self.objects]
        self.stems = plan_outputs(self.names)
        self.get_depsgraph = get_depsgraph
        self.bake_settings = bake_settings
        self.export_settings = export_settings
        self.out_dir = out_dir
        self.report = report

        self.index = 0
        self.fraction = 0.0
        self.steps: Steps[ObjectReport] | None = None
        self.baked: list[ObjectReport] = []
        self.failed: list[str] = []
        self.cancelled = False

    @property
    def done(self) -> bool:
        return self.cancelled or self.index >= len(self.objects)

    @property
    def current_name(self) -> str:
        return self.names[self.index] if self.index < len(self.names) else ""

    @property
    def progress(self) -> float:
        """Finished objects plus the current one's fraction, in object units."""
        return self.index + self.fraction

    def advance(self, budget: float = 0.05) -> bool:
        """Run steps for about `budget` seconds (at least one step); return done."""
        deadline = time.perf_counter() + budget
        while not self.done:
            self._step()
            if time.perf_counter() >= deadline:
                break
        return self.done

    def cancel(self) -> None:
        if self.steps is not None:
            self.steps.close()
            self.steps = None
        self.cancelled = True

    def summary(self) -> tuple[str, str]:
        total = len(self.objects)
        baked = len(self.baked)
        if self.cancelled:
            return "WARNING", f"Cancelled: {baked}/{total} baked"
        if self.failed:
            return "ERROR", f"{baked}/{total} baked, {len(self.failed)} failed ({', '.join(self.failed)})"
        return "INFO", f"{baked}/{total} baked to {self.out_dir}"

    def _step(self) -> None:
        name = self.names[self.index]
        try:
            if self.steps is None:
                self.steps = bake_object_steps(
                    self.objects[self.index],
                    self.get_depsgraph(),
                    self.bake_settings,
                    self.export_settings,
                    self.out_dir,
                    file_stem=self.stems[name],
                    on_fallback=lambda reason: self.report(
                        "WARNING", f"{name}: GPU failed ({reason}); baking on the CPU instead"
                    ),
                )
            self.fraction = next(self.steps)
        except StopIteration as stop:
            self._finish_object(stop.value)
        except Exception as e:
            message = str(e)
            self.report("ERROR", message if message.startswith(f"{name}:") else f"{name}: {message}")
            self.failed.append(name)
            self._next()

    def _finish_object(self, result: ObjectReport) -> None:
        for warning in result.warnings:
            self.report("WARNING", warning)
        dims = "x".join(map(str, result.result.grid.dims))
        files = ", ".join(p.name for p in result.files)
        self.report("INFO", f"{result.name}: {dims} {result.result.backend} -> {files}")
        self.baked.append(result)
        self._next()

    def _next(self) -> None:
        self.steps = None
        self.fraction = 0.0
        self.index += 1
