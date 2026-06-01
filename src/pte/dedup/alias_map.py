# Canonical alias dictionary. Keys are lowercase aliases; values are canonical names.
ACTOR_ALIASES: dict[str, str] = {
    "cozy bear": "APT29",
    "midnight blizzard": "APT29",
    "apt 29": "APT29",
    "apt29": "APT29",
    "lazarus": "Lazarus Group",
    "hidden cobra": "Lazarus Group",
}

MALWARE_ALIASES: dict[str, str] = {
    "cobalt-strike": "Cobalt Strike",
    "cobeacon": "Cobalt Strike",
    "win.cobalt_strike": "Cobalt Strike",
    "beacon": "Cobalt Strike",
}

def resolve_actor_alias(name: str) -> str:
    return ACTOR_ALIASES.get(name.lower().strip(), name)

def resolve_malware_alias(name: str) -> str:
    return MALWARE_ALIASES.get(name.lower().strip(), name)
