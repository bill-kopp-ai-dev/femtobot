"""Whimsical loading-state verbs and spinner styles for the CLI.

Used by ``ThinkingSpinner`` (and friends) to add a bit of personality to
the "thinking…" state. All randomness is optional and seedable for tests.

Camada 1 (1.5) do ``FEMTOBOT_CLI_REFACTOR_PLAN.md``.
"""

from __future__ import annotations

import random
from typing import Iterable

# 40+ verbs to match ``agents.cli.whimsy.verbPoolSize`` default.
DEFAULT_VERBS: tuple[str, ...] = (
    "Cogitating", "Percolating", "Ruminating", "Moonwalking", "Shenaniganing",
    "Brewing", "Synthesizing", "Deliberating", "Pondering", "Mulling",
    "Contemplating", "Daydreaming", "Wrangling words", "Reticulating",
    "Stringing syllables", "Crunching concepts", "Painting pixels",
    "Herding hypotheses", "Sharpening scissors", "Polishing prose",
    "Brewing ideas", "Assembling arguments", "Weaving words",
    "Stacking semaphores", "Crunching tokens", "Folding space-time",
    "Tightening bolts", "Sanding syllables", "Arranging atoms",
    "Threading thoughts", "Mashing metaphors", "Massaging metadata",
    "Negotiating nuance", "Brewing bytecode", "Tuning tensors",
    "Sharpening syntax", "Folding flags", "Sweeping stack traces",
    "Tightening tesseracts", "Brewing caffeine", "Steeping semantics",
)

# Spinner styles supported by ``rich.console.status``. We map ``auto`` to
# a random pick at runtime; explicit values are forwarded as-is.
SPINNER_STYLES: tuple[str, ...] = (
    "dots", "dots2", "dots3", "line", "aesthetic", "simpleDots",
)


def pick_verb(seed: int | None = None) -> str:
    """Return a random whimsical verb. Optional ``seed`` for determinism."""
    rng = random.Random(seed) if seed is not None else random
    return rng.choice(DEFAULT_VERBS)


def pick_spinner(seed: int | None = None) -> str:
    """Return a Rich spinner style name."""
    rng = random.Random(seed) if seed is not None else random
    return rng.choice(SPINNER_STYLES)


def resolve_spinner(style: str | None, *, seed: int | None = None) -> str:
    """Resolve a spinner style honoring the 'auto' sentinel.

    ``None`` and ``"auto"`` both return a random pick from
    :data:`SPINNER_STYLES`. Any other value is returned unchanged (the caller
    is responsible for validating it against :data:`SPINNER_STYLES`).
    """
    if not style or style == "auto":
        return pick_spinner(seed)
    return style


def rotate_verb(used: Iterable[str], *, seed: int | None = None) -> str:
    """Return a verb different from any in ``used`` (best-effort)."""
    used_set = set(used)
    choices = [v for v in DEFAULT_VERBS if v not in used_set]
    if not choices:
        return pick_verb(seed)
    rng = random.Random(seed) if seed is not None else random
    return rng.choice(choices)
