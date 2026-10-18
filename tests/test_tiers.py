"""Every collected test sits in exactly one tier, so a new file can never land unmarked or in two.

tests/conftest.py gives each test its tier from its path (tests/README.md has the three). This
checks whatever the current run collected: the default run (unit and integration) and `-m ""`,
which collects the e2e tour too.
"""

import pytest

TIERS = frozenset({"unit", "integration", "e2e"})


def test_every_collected_test_has_exactly_one_tier(request: pytest.FixtureRequest) -> None:
    items = request.session.items
    assert request.node in items
    wrong = {
        item.nodeid: sorted(tiers)
        for item in items
        if len(tiers := {m.name for m in item.iter_markers()} & TIERS) != 1
    }
    assert not wrong, f"each test needs exactly one of {sorted(TIERS)}: {wrong}"
