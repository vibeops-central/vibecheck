"""Vibecheck — evaluate a codebase against its AGENTS.md policy."""

__version__ = "0.1.0"

from .scorer import evaluate  # noqa: E402

__all__ = ["evaluate", "__version__"]
