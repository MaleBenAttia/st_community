#!/usr/bin/env python3
"""
Construit / met a jour author_roles.json (reference statique des roles d'auteurs).

Etapes :
  1. Agrège les auteurs + roles depuis test/output/forums/*.json (puis output/forums/*.json).
     Pour un auteur 'mixte' (role vide par endroits), on prend le premier role non vide trouve.
     Aucun role n'est invente depuis les profils : vide = vide reel.
  2. MERGE intelligent : ne JAMAIS écraser un role non vide deja present dans author_roles.json
     (modifications manuelles conservees).
  3. Les auteurs restes a "" sont listes a la fin du fichier (cle "_roles_non_resolus")
     pour modification manuelle, et affiches dans un message d'erreur.
  4. Ecriture UTF-8 (noms accentues / caracteres speciaux).
"""

import json
from collections import defaultdict

from config import BASE_DIR, OUTPUT_FORUMS_DIR

ROLES_FILE = BASE_DIR / "author_roles.json"

# Dossier source : output/forums (pipeline complete)
SOURCES = [OUTPUT_FORUMS_DIR]


def aggregate_roles() -> dict:
    """Agrège {auteur: {roles...}} depuis les JSONs sources (récursif, par catégorie)."""
    roles = defaultdict(set)
    for src in SOURCES:
        if not src.exists():
            continue
        for f in src.rglob("*.json"):
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for r in j.get("scraped_replies") or []:
                name = (r.get("author") or "").strip()
                role = (r.get("role") or "").strip()
                if name:
                    roles[name].add(role)
    out = {}
    for name, role_set in roles.items():
        non_empty = [r for r in role_set if r]
        out[name] = non_empty[0] if non_empty else ""
    return out


def main() -> None:
    aggregated = aggregate_roles()

    existing = {}
    if ROLES_FILE.exists():
        try:
            existing = json.loads(ROLES_FILE.read_text(encoding="utf-8"))
        except Exception:
            print(f"[WARN] {ROLES_FILE.name} illisible, il sera recree.")

    merged = dict(existing)
    merged.pop("_roles_non_resolus", None)  # recalculée en fin de fichier
    unresolved_new = []

    for name, role in aggregated.items():
        if name in merged:
            continue  # cle deja presente (role ou "") -> on preserve l'etat manuel
        if role:
            merged[name] = role
        else:
            merged[name] = ""
            unresolved_new.append(name)

    merged = dict(sorted(merged.items(), key=lambda kv: kv[0].lower()))
    # Auteurs restes a "" (manuels ou nouveaux) -> liste en fin de fichier
    unresolved = sorted(k for k, v in merged.items() if not v)
    merged["_roles_non_resolus"] = unresolved

    ROLES_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    resolved = sum(1 for k, v in merged.items() if k != "_roles_non_resolus" and v)
    print(f"[OK] {ROLES_FILE} : {len(merged) - 1} auteurs (resolus: {resolved}, vide: {len(unresolved)})")
    if unresolved:
        print(
            "[MSG ERREUR] Auteurs sans role (a completer manuellement dans "
            f"{ROLES_FILE.name}) : {sorted(unresolved)}"
        )


if __name__ == "__main__":
    main()