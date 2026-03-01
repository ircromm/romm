"""DAT catalog and downloader sources."""

from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
import webbrowser
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import unquote, urlsplit
import urllib.request

_USER_AGENT = "R0MM/2 DATDownloader (+local desktop app)"
_GITHUB_API_BASE = "https://api.github.com/repos/libretro/libretro-database/contents"

# Libretro mirrors for curated DAT families.
# These endpoints provide direct, scriptable listing + download URLs.
KNOWN_SOURCES = [
    {
        "id": "nointro",
        "family_name": "No-Intro",
        "name": "Libretro DAT Mirror (No-Intro)",
        "url": "https://github.com/libretro/libretro-database/tree/master/metadat/no-intro",
        "api_url": f"{_GITHUB_API_BASE}/metadat/no-intro",
        "description": "No-Intro DATs mirrored from libretro-database.",
    },
    {
        "id": "redump",
        "family_name": "Redump",
        "name": "Libretro DAT Mirror (Redump)",
        "url": "https://github.com/libretro/libretro-database/tree/master/metadat/redump",
        "api_url": f"{_GITHUB_API_BASE}/metadat/redump",
        "description": "Redump DATs mirrored from libretro-database.",
    },
    {
        "id": "tosec",
        "family_name": "TOSEC",
        "name": "Libretro DAT Mirror (TOSEC)",
        "url": "https://github.com/libretro/libretro-database/tree/master/metadat/tosec",
        "api_url": f"{_GITHUB_API_BASE}/metadat/tosec",
        "description": "TOSEC DATs mirrored from libretro-database.",
    },
]

_FAMILY_MAP = {row["id"]: row for row in KNOWN_SOURCES}
_SUPPORTED_EXTS = {".dat", ".xml", ".zip", ".gz", ".7z"}


class DATSourceManager:
    """Discovers downloadable DAT files and classifies DAT families."""

    def __init__(self) -> None:
        self.sources = {row["id"]: row for row in KNOWN_SOURCES}
        self._cache_lock = threading.Lock()
        self._catalog_cache: Dict[str, Dict] = {}
        self._cache_ttl_s = 600.0

    @staticmethod
    def _request_json(url: str, timeout_s: float = 4.0):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/vnd.github+json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=max(2.0, float(timeout_s))) as resp:
            raw = resp.read()
        text = raw.decode("utf-8", errors="ignore")
        return json.loads(text or "[]")

    @staticmethod
    def suggest_filename(url: str, fallback: str = "download.dat") -> str:
        raw = unquote(Path(urlsplit(str(url or "")).path).name)
        safe = (raw or "").strip().replace("\\", "_").replace("/", "_")
        if not safe:
            safe = fallback
        return safe

    @staticmethod
    def _system_from_name(name: str) -> str:
        base = Path(str(name or "")).stem
        return (base or str(name or "")).strip()

    @staticmethod
    def _is_dat_like(name: str) -> bool:
        suffix = Path(str(name or "")).suffix.lower()
        return suffix in _SUPPORTED_EXTS

    @staticmethod
    def _clone_items(items: List[Dict]) -> List[Dict]:
        return [dict(row) for row in (items or []) if isinstance(row, dict)]

    def _cache_get(self, family_id: str) -> Dict:
        key = str(family_id or "").strip().lower()
        if not key:
            return {}
        now = time.monotonic()
        with self._cache_lock:
            row = self._catalog_cache.get(key)
            if not isinstance(row, dict):
                return {}
            ts = float(row.get("ts", 0.0) or 0.0)
            if (now - ts) > self._cache_ttl_s:
                self._catalog_cache.pop(key, None)
                return {}
            return {
                "items": self._clone_items(list(row.get("items", []) or [])),
                "family": key,
                "source": str(row.get("source", "") or ""),
                "cached": True,
                "error": str(row.get("error", "") or ""),
            }

    def _cache_set(self, family_id: str, payload: Dict) -> None:
        key = str(family_id or "").strip().lower()
        if not key:
            return
        row = {
            "ts": time.monotonic(),
            "items": self._clone_items(list(payload.get("items", []) or [])),
            "source": str(payload.get("source", "") or ""),
            "error": str(payload.get("error", "") or ""),
        }
        with self._cache_lock:
            self._catalog_cache[key] = row

    def get_sources(self) -> List[Dict]:
        """List known DAT downloader families."""
        return [dict(row) for row in KNOWN_SOURCES]

    def open_source_page(self, source_id: str) -> bool:
        source = self.sources.get((source_id or "").strip().lower())
        if not source:
            return False
        webbrowser.open(source["url"])
        return True

    def list_family_dats(self, family_id: str, *, limit: int = 5000, force_refresh: bool = False) -> Dict:
        family_key = (family_id or "").strip().lower()
        meta = _FAMILY_MAP.get(family_key)
        if not meta:
            return {"items": [], "error": f"unknown family: {family_id}", "family": family_key}

        if not force_refresh:
            cached = self._cache_get(family_key)
            if cached:
                items = list(cached.get("items", []) or [])
                if limit > 0:
                    items = items[: int(limit)]
                return {**cached, "items": items}

        api_url = str(meta.get("api_url", "") or "").strip()
        if not api_url:
            return {"items": [], "error": f"missing api url for family: {family_key}", "family": family_key}

        try:
            payload = self._request_json(api_url)
        except Exception as exc:
            return {"items": [], "error": str(exc), "family": family_key, "source": api_url}

        items: List[Dict] = []
        if isinstance(payload, list):
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("type", "")).lower() != "file":
                    continue
                name = str(entry.get("name", "") or "").strip()
                if not name or not self._is_dat_like(name):
                    continue
                download_url = str(entry.get("download_url", "") or "").strip()
                html_url = str(entry.get("html_url", "") or "").strip()
                url = download_url or html_url
                if not url:
                    continue
                size_raw = entry.get("size", 0)
                try:
                    size_val = int(size_raw or 0)
                except Exception:
                    size_val = 0
                items.append(
                    {
                        "id": f"{family_key}:{name}",
                        "family_id": family_key,
                        "family_name": str(meta.get("family_name", "") or "").strip(),
                        "source_name": str(meta.get("name", "") or "").strip(),
                        "name": name,
                        "system": self._system_from_name(name),
                        "url": url,
                        "size": size_val,
                        "recognized_family": str(meta.get("family_name", "") or "").strip(),
                        "source_url": str(meta.get("url", "") or "").strip(),
                    }
                )

        items.sort(key=lambda row: (str(row.get("system", "")).lower(), str(row.get("name", "")).lower()))
        payload = {"items": items, "family": family_key, "source": api_url}
        self._cache_set(family_key, payload)
        if limit > 0:
            items = items[: int(limit)]
        return {**payload, "items": items}

    def list_download_catalog(
        self,
        *,
        family: str = "",
        limit_per_family: int = 5000,
        force_refresh: bool = False,
    ) -> Dict:
        family_key = (family or "").strip().lower()
        if family_key and family_key not in _FAMILY_MAP:
            return {"items": [], "error": f"unsupported family: {family}", "families": self.get_sources()}

        all_items: List[Dict] = []
        errors: List[str] = []
        family_ids = [family_key] if family_key else [row["id"] for row in KNOWN_SOURCES]

        def _fetch_one(fid: str) -> Tuple[str, Dict]:
            res = self.list_family_dats(
                fid,
                limit=limit_per_family,
                force_refresh=force_refresh,
            )
            return fid, res

        if len(family_ids) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(family_ids))) as executor:
                futures = [executor.submit(_fetch_one, fid) for fid in family_ids]
                for future in concurrent.futures.as_completed(futures):
                    fid, res = future.result()
                    all_items.extend(list(res.get("items", []) or []))
                    err = str(res.get("error", "") or "").strip()
                    if err:
                        errors.append(f"{fid}: {err}")
        else:
            for fid in family_ids:
                _fid, res = _fetch_one(fid)
                all_items.extend(list(res.get("items", []) or []))
                err = str(res.get("error", "") or "").strip()
                if err:
                    errors.append(f"{fid}: {err}")

        all_items.sort(
            key=lambda row: (
                str(row.get("family_name", "")).lower(),
                str(row.get("system", "")).lower(),
                str(row.get("name", "")).lower(),
            )
        )
        return {
            "items": all_items,
            "families": self.get_sources(),
            "error": " | ".join(errors) if errors else "",
            "family_filter": family_key,
        }

    @staticmethod
    def _normalize_query_text(value: str) -> str:
        raw = str(value or "").strip().lower()
        raw = raw.replace("_", " ").replace("-", " ")
        raw = re.sub(r"\s+", " ", raw)
        raw = re.sub(r"[^a-z0-9 ]+", "", raw)
        return raw.strip()

    @classmethod
    def _score_item(cls, query: str, item: Dict) -> Tuple[int, int]:
        name = str(item.get("name", "") or "")
        system = str(item.get("system", "") or "")
        hay_raw = f"{name} {system}".strip().lower()
        hay = cls._normalize_query_text(hay_raw)
        q = cls._normalize_query_text(query)
        if not q or not hay:
            return (0, 0)

        score = 0
        if hay == q:
            score += 120
        if hay.startswith(q):
            score += 90
        if q in hay:
            score += 70

        name_norm = cls._normalize_query_text(name)
        system_norm = cls._normalize_query_text(system)
        if name_norm == q:
            score += 110
        if system_norm == q:
            score += 105
        if name_norm.startswith(q):
            score += 75
        if system_norm.startswith(q):
            score += 70
        if q in name_norm:
            score += 55
        if q in system_norm:
            score += 50

        # Prefer smaller edit distance by token overlap proxy.
        q_tokens = [tok for tok in q.split(" ") if tok]
        if q_tokens:
            overlap = sum(1 for tok in q_tokens if tok in hay)
            score += min(40, overlap * 12)
        return (score, len(name))

    def find_best_match(self, query: str, *, family: str = "", limit_per_family: int = 5000) -> Dict:
        safe_query = str(query or "").strip()
        if not safe_query:
            return {"error": "query required", "match": None, "alternatives": []}

        catalog = self.list_download_catalog(
            family=str(family or "").strip().lower(),
            limit_per_family=max(100, int(limit_per_family or 5000)),
        )
        items = [row for row in list(catalog.get("items", []) or []) if isinstance(row, dict)]
        if not items:
            return {
                "error": str(catalog.get("error", "") or "catalog is empty"),
                "match": None,
                "alternatives": [],
            }

        scored: List[Tuple[int, int, Dict]] = []
        for row in items:
            score, name_len = self._score_item(safe_query, row)
            if score <= 0:
                continue
            scored.append((score, -name_len, row))
        scored.sort(key=lambda it: (it[0], it[1]), reverse=True)

        if not scored:
            return {"error": "no match found", "match": None, "alternatives": []}

        best = scored[0][2]
        alternatives = [it[2] for it in scored[:10]]
        return {
            "match": best,
            "alternatives": alternatives,
            "total_candidates": len(scored),
            "catalog_error": str(catalog.get("error", "") or ""),
        }

    @staticmethod
    def recognize_family(
        name: str = "",
        *,
        url: str = "",
        header_name: str = "",
        header_description: str = "",
        family_hint: str = "",
    ) -> str:
        hint = (family_hint or "").strip().lower()
        if hint in {"nointro", "no-intro"}:
            return "No-Intro"
        if hint == "redump":
            return "Redump"
        if hint == "tosec":
            return "TOSEC"

        text = " ".join(
            [
                str(name or ""),
                str(url or ""),
                str(header_name or ""),
                str(header_description or ""),
            ]
        ).lower()

        checks: List[Tuple[str, str]] = [
            ("no-intro", "No-Intro"),
            ("dat-o-matic", "No-Intro"),
            ("/no-intro/", "No-Intro"),
            ("redump", "Redump"),
            ("/redump/", "Redump"),
            ("tosec", "TOSEC"),
            ("/tosec/", "TOSEC"),
        ]
        for token, family_name in checks:
            if token in text:
                return family_name
        return "Unknown"

    def list_libretro_dats(self) -> List[Dict]:
        """
        Backward-compatible list endpoint (No-Intro family only).
        """
        res = self.list_family_dats("nointro", limit=400)
        return list(res.get("items", []) or [])
