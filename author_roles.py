#!/usr/bin/env python3
"""
Reference statique des roles d'auteurs (author_roles.json).

Fonctions partagees par run_test_200.py et main.py :
  - load_roles_map()     : charge author_roles.json (source de verite, modifiable a la main).
  - fill_missing_roles() : remplit le role vide d'une reponse via la reference statique.
  - unresolved_authors() : auteurs dont le role reste vide (pour le message d'erreur).
"""

import json
from pathlib import Path

ROLES_FILE = Path(__file__).parent / "author_roles.json"

_cache = None


def load_roles_map() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(ROLES_FILE.read_text(encoding="utf-8")) if ROLES_FILE.exists() else {}
        except Exception:
            _cache = {}
    return _cache


def fill_missing_roles(replies: list) -> None:
    """Complete role='' de chaque reponse via author_roles.json (repli statique)."""
    roles = load_roles_map()
    for r in replies:
        if not (r.get("role") or "").strip():
            r["role"] = roles.get((r.get("author") or "").strip(), "")


def unresolved_authors(replies: list) -> set:
    """Auteurs dont le role reste vide apres le repli statique."""
    return {
        (r.get("author") or "").strip()
        for r in replies
        if not (r.get("role") or "").strip()
    }