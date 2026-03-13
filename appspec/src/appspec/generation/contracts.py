"""Target plugin contract — the interface all code generation targets must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from appspec.models import AppSpec


class BaseTarget(ABC):
    """A deterministic code generation target.

    Subclass this and implement ``render()`` and ``supports()`` to create a
    new target.  Place the subclass in ``appspec/generation/targets/<name>/target.py``
    for auto-discovery, or register via the ``appspec.targets`` entry-point group.
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def render(self, spec: "AppSpec") -> dict[str, str]:
        """Produce files from an AppSpec. Returns ``{filepath: content}``.

        **Must be deterministic** — identical spec -> identical output.
        **Must be pure** — do not call other targets; the composer handles composition.
        """
        ...

    @abstractmethod
    def supports(self, spec: "AppSpec") -> bool:
        """Return True if this target can render the given spec."""
        ...
