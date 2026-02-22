"""Application settings and collection profile presets for R0MM."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Dict

DEFAULT_SETTINGS_PATH = os.path.expanduser("~/.rommanager/settings.json")

PROFILE_PRESETS: Dict[str, Dict[str, Any]] = {
    "historical_preservation": {
        "strategy": "museum",
        "region_priority": ["Japan", "USA", "Europe", "World", "Unknown"],
        "allow_tags": ["Rev", "Proto", "Beta"],
        "exclude_tags": ["Hack"],
        "naming_template": "{game} ({region})",
        "keep_name_tags": False,
    },
    "mister_playset": {
        "strategy": "system+1g1r",
        "region_priority": ["USA", "Europe", "Japan", "World", "Unknown"],
        "allow_tags": ["Rev"],
        "exclude_tags": ["Proto", "Beta", "Hack"],
        "naming_template": "{game}",
        "keep_name_tags": False,
    },
    "retroarch_frontend": {
        "strategy": "alphabetical",
        "region_priority": ["USA", "World", "Europe", "Japan", "Unknown"],
        "allow_tags": ["Rev"],
        "exclude_tags": ["Proto", "Beta", "Hack"],
        "naming_template": "{game} ({region})",
        "keep_name_tags": False,
    },
    "full_set_no_hacks": {
        "strategy": "system",
        "region_priority": ["USA", "Europe", "Japan", "World", "Unknown"],
        "allow_tags": ["Rev", "Alt"],
        "exclude_tags": ["Hack"],
        "naming_template": "{name}",
        "keep_name_tags": True,
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "active_profile": "retroarch_frontend",
    "language": "en",
    "theme": "dark",
    "accessibility": {
        "font_scale": 1.0,
        "high_contrast": False,
        "dense_tables": False,
        "reduced_motion": False,
    },
    "collection_profiles": deepcopy(PROFILE_PRESETS),
    "region_policy": {
        "global_priority": ["USA", "World", "Europe", "Japan", "Brazil", "Korea", "Unknown"],
        "per_system": {},
        "allow_tags": ["Rev", "Alt"],
        "exclude_tags": ["Hack"],
    },
    "naming": {
        "template": "{name}",
        "keep_tags": True,
    },
    "metadata": {
        "enabled": False,
        "db_path": "",
    },
    "audit": {
        "enabled": True,
        "level": "normal",
        "path": os.path.expanduser("~/.rommanager/logs/audit.log"),
    },
    "health": {
        "enabled": True,
        "warn_on_duplicates": True,
        "warn_on_unknown_ext": True,
    },
    "museum_mode": {
        "enabled": False,
        "taxonomy": "generation",
    },
}


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in (updates or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def load_settings(path: str = DEFAULT_SETTINGS_PATH) -> Dict[str, Any]:
    if not os.path.exists(path):
        return deepcopy(DEFAULT_SETTINGS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _deep_merge(DEFAULT_SETTINGS, data)
    except Exception:
        return deepcopy(DEFAULT_SETTINGS)


def save_settings(settings: Dict[str, Any], path: str = DEFAULT_SETTINGS_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_effective_profile(settings: Dict[str, Any], profile_name: str | None = None) -> Dict[str, Any]:
    profiles = settings.get("collection_profiles", {})
    name = profile_name or settings.get("active_profile")
    profile = profiles.get(name, {})
    return _deep_merge(PROFILE_PRESETS.get("retroarch_frontend", {}), profile)


def apply_runtime_settings(settings: Dict[str, Any], profile_name: str | None = None) -> Dict[str, Any]:
    """Apply settings to runtime subsystems (organizer/matcher policies)."""
    from .organizer import configure_selection_policy, configure_naming, configure_audit
    from . import i18n as _i18n

    profile = get_effective_profile(settings, profile_name)
    lang = settings.get("language", "en")
    setter = getattr(_i18n, "set_language", None)
    if callable(setter):
        setter(lang)
    configure_selection_policy({
        "global_priority": profile.get("region_priority") or settings.get("region_policy", {}).get("global_priority", []),
        "per_system": settings.get("region_policy", {}).get("per_system", {}),
        "allow_tags": profile.get("allow_tags", []),
        "exclude_tags": profile.get("exclude_tags", []),
    })
    configure_naming(
        profile.get("naming_template", settings.get("naming", {}).get("template", "{name}")),
        profile.get("keep_name_tags", settings.get("naming", {}).get("keep_tags", True)),
    )
    configure_audit(settings.get("audit", {}).get("path"), settings.get("audit", {}).get("enabled", True))
    return profile


def set_persisted_language(language: str, path: str = DEFAULT_SETTINGS_PATH) -> Dict[str, Any]:
    """Persist language choice and apply runtime settings immediately."""
    settings = load_settings(path)
    settings["language"] = language
    save_settings(settings, path)
    apply_runtime_settings(settings)
    return settings
