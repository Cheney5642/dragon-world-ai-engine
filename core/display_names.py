"""Chinese player-facing names with stable internal entity identifiers."""

from __future__ import annotations

from typing import Any


LOCATION_NAMES: dict[str, str] = {
    "skeld_village": "斯凯尔德",
    "stormcliff": "风暴崖",
    "old_ruins": "古老遗迹",
    "whispering_woods": "低语森林",
}

LOCATION_LEGACY_NAMES: dict[str, str] = {
    "skeld_village": "Skeld",
    "stormcliff": "Stormcliff",
    "old_ruins": "Old Ruins",
    "whispering_woods": "Whispering Woods",
}

NPC_NAMES: dict[str, str] = {
    "npc_astrid": "阿斯特丽德",
    "npc_bjorn": "比约恩",
    "npc_haldor": "哈尔多",
}

NPC_LEGACY_NAMES: dict[str, str] = {
    "npc_astrid": "Astrid",
    "npc_bjorn": "Bjorn",
    "npc_haldor": "Haldor",
}

DRAGON_NAME_COPY: dict[str, str] = {
    "kael": "凯尔",
    "voryn": "沃林",
    "mossveil": "苔雾",
}

_LEGACY_DISPLAY_COPY: tuple[tuple[str, str], ...] = (
    ("Whispering Woods", "低语森林"),
    ("Old Ruins", "古老遗迹"),
    ("Stormcliff", "风暴崖"),
    ("Skeld", "斯凯尔德"),
    ("Astrid", "阿斯特丽德"),
    ("Bjorn", "比约恩"),
    ("Haldor", "哈尔多"),
    ("Voryn", "沃林"),
    ("Kael", "凯尔"),
    ("Mossveil", "苔雾"),
)


def display_location_name(location_id: Any, stored_name: Any = None) -> str:
    if isinstance(location_id, str) and location_id in LOCATION_NAMES:
        return LOCATION_NAMES[location_id]
    if isinstance(stored_name, str) and stored_name.strip():
        return stored_name.strip()
    return str(location_id or "未知地点")


def display_npc_name(npc_id: Any, stored_name: Any = None) -> str:
    if isinstance(npc_id, str) and npc_id in NPC_NAMES:
        return NPC_NAMES[npc_id]
    if isinstance(stored_name, str) and stored_name.strip():
        return stored_name.strip()
    return str(npc_id or "未知人物")


def display_dragon_name(dragon_id: Any, stored_name: Any = None) -> str:
    if isinstance(stored_name, str) and stored_name.strip():
        value = stored_name.strip()
        return DRAGON_NAME_COPY.get(value.casefold(), value)
    return str(dragon_id or "未命名之龙")


def location_aliases(location_id: Any, stored_name: Any = None) -> set[str]:
    aliases = {str(location_id or ""), str(stored_name or "")}
    if isinstance(location_id, str):
        aliases.add(LOCATION_NAMES.get(location_id, ""))
        aliases.add(LOCATION_LEGACY_NAMES.get(location_id, ""))
    return {alias for alias in aliases if alias}


def npc_aliases(npc_id: Any, stored_name: Any = None) -> set[str]:
    aliases = {str(npc_id or ""), str(stored_name or "")}
    if isinstance(npc_id, str):
        aliases.add(NPC_NAMES.get(npc_id, ""))
        aliases.add(NPC_LEGACY_NAMES.get(npc_id, ""))
    return {alias for alias in aliases if alias}


def dragon_aliases(dragon_id: Any, stored_name: Any = None) -> set[str]:
    aliases = {str(dragon_id or ""), str(stored_name or "")}
    if isinstance(stored_name, str):
        aliases.add(DRAGON_NAME_COPY.get(stored_name.strip().casefold(), ""))
    return {alias for alias in aliases if alias}


def localize_known_names(text: str) -> str:
    """Translate only authored/known legacy proper names in presentation text."""

    result = text
    for legacy_name, chinese_name in _LEGACY_DISPLAY_COPY:
        result = result.replace(legacy_name, chinese_name)
    return result
