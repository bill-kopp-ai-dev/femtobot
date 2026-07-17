"""Regression test: each bug from longlogs.txt has a line-anchor in the fixture.

Added as part of the ``longlogs.txt`` remediation plan (PR 0.2).
If any of the ten bugs stops being reproducible (because the underlying
behaviour was fixed) the test must be updated alongside the fix — never
silently.

The test is intentionally pure: it does not import femtobot runtime
modules, so it runs even on a half-installed checkout and never blocks
the user from landing a fix.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "longlogs_sample.txt"
EXPECTED = FIXTURES / "longlogs_expected_bugs.json"


def _load_sample() -> list[str]:
    assert SAMPLE.exists(), f"fixture missing: {SAMPLE}"
    return SAMPLE.read_text(encoding="utf-8").splitlines()


def _load_expected() -> dict:
    assert EXPECTED.exists(), f"fixture missing: {EXPECTED}"
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


def test_fixture_present() -> None:
    lines = _load_sample()
    # First line must be the bug-coverage header added in PR 0.2.
    assert lines, "fixture is empty"
    assert "Fixture de regressão" in lines[0], (
        "fixture header drifted; please update tests/fixtures/longlogs_sample.txt"
    )


def test_each_bug_has_anchor() -> None:
    """Every documented bug has at least one anchor line present in the sample.

    Latent bugs (B7, B9) are tracked in the JSON with an empty
    ``must_contain_any`` list — those are not surfaced in the captured
    log because they only fire under specific SDK / startup paths. The
    test still ensures their entries exist and are non-empty in
    description / anchor_lines.
    """
    lines = _load_sample()
    expected = _load_expected()
    joined = "\n".join(lines)
    missing: list[str] = []
    for bug_id, spec in expected.items():
        markers = spec.get("must_contain_any", [])
        if not markers:
            # Latent bug — must still have description + anchor_lines slot.
            assert spec.get("description"), f"{bug_id}: missing description"
            assert isinstance(spec.get("anchor_lines"), list), (
                f"{bug_id}: anchor_lines must be a list"
            )
            continue
        for marker in markers:
            if marker in joined:
                break
        else:
            missing.append(bug_id)
    assert not missing, (
        "fixture no longer reproduces these bugs: "
        f"{missing}. Either the underlying issue is fixed (update the fixture "
        "and the expected JSON together) or the marker drifted."
    )


def test_ten_bugs_documented() -> None:
    """Sanity: the fixture must document exactly the ten B1..B10 bugs."""
    expected = _load_expected()
    assert set(expected.keys()) == {f"B{i}" for i in range(1, 11)}, (
        "longlogs_expected_bugs.json must cover B1..B10 inclusive"
    )
