"""Target registry with auto-discovery and explicit error reporting."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

from appspec.generation.contracts import BaseTarget

if TYPE_CHECKING:
    from appspec.models import AppSpec

logger = logging.getLogger("appspec.generation")


class TargetRegistry:
    """Discover and manage code generation targets."""

    def __init__(self) -> None:
        self._targets: dict[str, BaseTarget] = {}

    def register(self, target: BaseTarget) -> None:
        if target.name in self._targets:
            logger.warning(
                "Target '%s' overridden by %s",
                target.name, type(target).__qualname__,
            )
        self._targets[target.name] = target

    def get(self, name: str) -> BaseTarget:
        if name not in self._targets:
            raise KeyError(f"Unknown target '{name}'. Available: {self.list_targets()}")
        return self._targets[name]

    def list_targets(self) -> list[str]:
        return sorted(self._targets.keys())

    def auto_discover(self) -> None:
        """Find targets in the ``appspec.generation.targets`` package."""
        targets_pkg = importlib.import_module("appspec.generation.targets")
        pkg_path = Path(targets_pkg.__file__).parent

        for info in pkgutil.iter_modules([str(pkg_path)]):
            if not info.ispkg:
                continue
            module_path = f"appspec.generation.targets.{info.name}.target"
            try:
                mod = importlib.import_module(module_path)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseTarget)
                        and attr is not BaseTarget
                        and attr.name
                    ):
                        self.register(attr())
            except ImportError as exc:
                logger.warning("Failed to import target %s: %s", module_path, exc)
            except AttributeError as exc:
                logger.warning("Target module %s has no valid target class: %s", module_path, exc)

        self._discover_entry_points()

    def _discover_entry_points(self) -> None:
        """Load targets registered via ``[project.entry-points."appspec.targets"]``."""
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="appspec.targets")
            for ep in eps:
                try:
                    target_cls = ep.load()
                    if isinstance(target_cls, type) and issubclass(target_cls, BaseTarget):
                        self.register(target_cls())
                except Exception as exc:
                    logger.warning("Failed to load entry-point target %s: %s", ep.name, exc)
        except Exception as exc:
            logger.debug("Entry-point discovery unavailable: %s", exc)


_registry: TargetRegistry | None = None


def get_registry() -> TargetRegistry:
    """Return the global target registry (auto-discovers on first call)."""
    global _registry
    if _registry is None:
        _registry = TargetRegistry()
        _registry.auto_discover()
    return _registry


def generate(spec: "AppSpec", target_name: str) -> dict[str, str]:
    """Generate code for the given spec using the named target."""
    registry = get_registry()
    target = registry.get(target_name)
    if not target.supports(spec):
        raise ValueError(
            f"Target '{target_name}' does not support this spec "
            f"(engine={spec.database.engine.value})"
        )
    return target.render(spec)
