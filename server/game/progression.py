"""XP / level-up using dq1 level table."""

from __future__ import annotations

from game.data_loader import battle_spells_at, get_level_row


def level_for_xp(xp: int) -> int:
    level = 1
    for lv in range(1, 31):
        row = get_level_row(lv)
        if not row:
            break
        if xp >= int(row["total_xp"]):
            level = lv
        else:
            break
    return level


def xp_to_next_level(xp: int, level: int | None = None) -> dict:
    """XP progress toward the next level (for HUD / status sheet)."""
    xp = max(0, int(xp or 0))
    lv = int(level) if level is not None else level_for_xp(xp)
    lv = max(1, min(30, lv))
    cur_row = get_level_row(lv) or {}
    next_row = get_level_row(lv + 1) if lv < 30 else None
    cur_total = int(cur_row.get("total_xp") or 0)
    if not next_row:
        return {
            "level": lv,
            "xp": xp,
            "xp_into_level": max(0, xp - cur_total),
            "xp_for_level": 0,
            "xp_to_next": 0,
            "max_level": True,
        }
    next_total = int(next_row.get("total_xp") or cur_total)
    span = max(1, next_total - cur_total)
    into = max(0, min(span, xp - cur_total))
    return {
        "level": lv,
        "xp": xp,
        "xp_into_level": into,
        "xp_for_level": span,
        "xp_to_next": max(0, next_total - xp),
        "max_level": False,
    }


def apply_xp(hero: dict, xp_gain: int) -> dict:
    """Mutate hero with XP; return report with level_ups list."""
    old_level = int(hero.get("level", 1))
    hero["experience"] = int(hero.get("experience", 0)) + int(xp_gain)
    new_level = level_for_xp(hero["experience"])
    report = {
        "xp_gained": int(xp_gain),
        "xp_total": hero["experience"],
        "level_ups": [],
        "new_spells": [],
    }
    if new_level > old_level:
        for lv in range(old_level + 1, new_level + 1):
            row = get_level_row(lv)
            if not row:
                continue
            up = {
                "level": lv,
                "strength": row["strength"],
                "agility": row["agility"],
                "max_hp": row["max_hp"],
                "max_mp": row["max_mp"],
                "spell": row.get("spell"),
            }
            hero["level"] = lv
            hero["strength"] = row["strength"]
            hero["agility"] = row["agility"]
            # Full heal on level up (DQ1 style-ish).
            # Battle engine uses hp/mp; persistence uses current_hp/current_mp — keep both in sync.
            hero["max_hp"] = row["max_hp"]
            hero["max_mp"] = row["max_mp"]
            hero["current_hp"] = row["max_hp"]
            hero["current_mp"] = row["max_mp"]
            hero["hp"] = row["max_hp"]
            hero["mp"] = row["max_mp"]
            if row.get("spell"):
                report["new_spells"].append(row["spell"])
            report["level_ups"].append(up)
    hero["known_spells"] = battle_spells_at(int(hero["level"]))
    return report


def gold_add(hero: dict, amount: int) -> int:
    """Add gold to hero. Clamps at 0; tolerates corrupt gold strings."""
    try:
        cur = int(str(hero.get("gold", "0") or "0"))
    except (TypeError, ValueError):
        cur = 0
    cur = max(0, cur + int(amount))
    hero["gold"] = str(cur)
    return int(amount)
