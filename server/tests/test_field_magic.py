"""Field (overworld) spell casting."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.data_loader import field_spells_at, get_spell
from game.formulas import apply_heal, heal_amount
from game.rng import Rng
from game.world_manager import zone_at


def test_field_spells_by_level():
    assert "heal" in field_spells_at(3)
    assert "hurt" not in field_spells_at(20)  # battle-only
    assert "return" in field_spells_at(13)
    assert "repel" in field_spells_at(15)
    assert get_spell("heal").get("field") is True
    assert get_spell("hurt").get("field") is False


def test_heal_formula_field_band():
    for seed in range(10):
        a = heal_amount(Rng(seed))
        assert 10 <= a <= 17
        hp, actual = apply_heal(5, 40, a)
        assert hp == min(40, 5 + a)
        assert actual == hp - 5


def test_outside_requires_dungeon_zone():
    assert zone_at(2, 2) == "town"
    assert zone_at(17, 1) == "dungeon"
