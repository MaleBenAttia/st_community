#!/usr/bin/env python3
"""
Scanneur de catégories (Filtré par date) - STMicroelectronics

Interroge l'API inSided pour chaque catégorie et compte UNIQUEMENT
les articles/questions publiés APRÈS la date spécifiée dans `.env` (RAG_START_DATE).
Génère un rapport dans scan_report.txt et retourne les IDs des catégories actives
(avec au moins un item récent) pour cibler l'extraction.

Point d'entrée : run_pipeline.py (scan → extraction → rôles → RAG).
"""

import time
from pathlib import Path
from datetime import datetime

import run_logger

from config import (
    API_BASE_URL,
    FORUM_CATEGORIES,
    KB_CATEGORIES,
    PAGE_SIZE,
    RAG_START_DATE_STR,
    REQUEST_DELAY_SECONDS,
    api_get,
    get_access_token,
    is_recent_enough,
)


def count_recent_items(category_id, token: str) -> dict:
    """Parcourt les pages et compte uniquement les items post-RAG_START_DATE."""
    url = f"{API_BASE_URL}/topics"
    headers = {"Authorization": f"Bearer {token}"}

    count_recent = 0
    cat_name = f"Category {category_id}"
    page = 1

    while True:
        params = {"categoryId": category_id, "pageSize": PAGE_SIZE, "page": page}

        # Gestion des retries via config.api_get (429 / 5xx / 401)
        try:
            data = api_get(url, headers, params)
        except Exception as e:
            run_logger.error(f"[SCAN] Échec API catégorie {category_id} (retries épuisés) : {e}")
            return {"id": category_id, "name": cat_name, "count": "Erreur"}

        results = data.get("result", [])

        if not results:
            break  # Plus aucun résultat

        if page == 1 and len(results) > 0:
            cat_name = results[0].get("categoryName", cat_name)

        for item in results:
            if is_recent_enough(item.get("publishedAt")):
                count_recent += 1

        # L'API inSided retourne les topics du plus récent au plus ancien.
        # Si toute la page est trop vieille (ou vide) -> on s'arrête.
        has_recent_in_page = any(is_recent_enough(i.get("publishedAt")) for i in results)
        if not has_recent_in_page:
            break

        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    return {"id": category_id, "name": cat_name, "count": count_recent}


def run_scan() -> dict:
    print("Authentification en cours (Scan)...")
    token = get_access_token()
    print(f"Token obtenu. Démarrage du scan à partir de la date : {RAG_START_DATE_STR}\n")
    print("Cette opération va paginer l'API (cela peut prendre un petit moment)...\n")

    report_lines = []
    report_lines.append("========================================")
    report_lines.append("RAPPORT DE SCAN DES CATÉGORIES ST")
    report_lines.append(f"Date du scan : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"Filtre date  : > {RAG_START_DATE_STR}")
    report_lines.append("========================================\n")

    # SCAN FORUMS
    report_lines.append("--- PRODUCT FORUMS ---")
    print("Scan des Product Forums...")
    total_forums = 0
    forum_results = []  # collect all results for deriving active IDs
    for cat_id in FORUM_CATEGORIES:
        info = count_recent_items(cat_id, token)
        forum_results.append(info)
        count = info["count"]
        if isinstance(count, int):
            total_forums += count
        line = f"  - ID {cat_id:>3} | Items récents : {count:4} | Nom : {info['name']}"
        print(line)
        report_lines.append(line)
        time.sleep(REQUEST_DELAY_SECONDS)

    report_lines.append(f"> TOTAL ITEMS RÉCENTS DANS FORUMS : {total_forums}\n")

    # SCAN KNOWLEDGE BASE
    report_lines.append("--- KNOWLEDGE BASE ---")
    print("\nScan de la Knowledge Base...")
    total_kb = 0
    kb_results = []  # collect all results for deriving active IDs
    for cat_id in KB_CATEGORIES:
        info = count_recent_items(cat_id, token)
        kb_results.append(info)
        count = info["count"]
        if isinstance(count, int):
            total_kb += count
        line = f"  - ID {cat_id:>3} | Items récents : {count:4} | Nom : {info['name']}"
        print(line)
        report_lines.append(line)
        time.sleep(REQUEST_DELAY_SECONDS)

    report_lines.append(f"> TOTAL ITEMS RÉCENTS DANS KNOWLEDGE BASE : {total_kb}\n")

    # SAUVEGARDE DANS logs/ (dossier du run si actif)
    run_dir = run_logger.current_run_dir()
    logs_dir = Path(run_dir) if run_dir else (Path(__file__).parent / "logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    report_path = logs_dir / "scan_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print(f"\n[OK] Scan terminé ! Le rapport filtré sur {RAG_START_DATE_STR} a été sauvegardé dans : {report_path}")

    # Dériver les IDs actifs (count > 0) pour cibler uniquement les catégories non vides
    active_forum_ids = [str(info["id"]) for info in forum_results if isinstance(info["count"], int) and info["count"] > 0]
    active_kb_ids    = [str(info["id"]) for info in kb_results    if isinstance(info["count"], int) and info["count"] > 0]

    print(f"\n[SCAN] Forums avec items récents ({len(active_forum_ids)}/{len(FORUM_CATEGORIES)}) : {active_forum_ids}")
    print(f"[SCAN] KB avec items récents     ({len(active_kb_ids)}/{len(KB_CATEGORIES)}) : {active_kb_ids}")

    return {
        "total_forums": total_forums,
        "total_kb": total_kb,
        "active_forum_ids": active_forum_ids,
        "active_kb_ids": active_kb_ids,
    }
