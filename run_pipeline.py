#!/usr/bin/env python3
"""
Orchestrate le pipeline complet en 3 étapes séquentielles :

  ÉTAPE 1 — Scan  (scan_categories.py)
      Interroge l'API pour chaque catégorie et compte les items publiés
      après RAG_START_DATE. Retourne la liste des catégories actives
      (count > 0) pour éviter de paginer des catégories vides à l'étape 2.

  ÉTAPE 2 — Extraction  (main.py)
      Appelle l'API pour chaque catégorie ACTIVE uniquement (optimisation
      issue du scan). Paginationne avec arrêt anticipé dès qu'une page
      ne contient plus d'items dans la période voulue. Scrape les réponses
      HTML de chaque topic en parallèle (ThreadPoolExecutor × 10).
      Écrit 1 fichier JSON par item dans output/.

  ÉTAPE 3 — Préparation RAG  (prepare_rag.py)
      Lit output/, applique les filtres (best_answer, date), convertit
      HTML → Markdown, et écrit les fichiers RAG-ready dans rag-ready/.
      Calcule l'ensemble des KPIs (Forums et KB séparés).

  SORTIE
      Un fichier logs/pipeline_stats_YYYYMMDD_HHmmss.json contenant tous
      les KPIs agregés des 3 étapes (scan, extraction, préparation RAG)
      avec stats Forums et Knowledge Base strictement séparées.

Usage :
    python run_pipeline.py
"""

import os
import json
from pathlib import Path
from datetime import datetime

# Modules du pipeline
from scan_categories import run_scan
from main import run_extract
from prepare_rag import run_prepare

BASE_DIR = Path(__file__).parent
LOGS_DIR = BASE_DIR / "logs"

# Nombre total de catégories couvertes (référence fixe pour les stats step_1)
_TOTAL_FORUM_CATS = 29
_TOTAL_KB_CATS    = 8


def main():
    print("==================================================")
    print("   DÉMARRAGE DU PIPELINE COMPLET STMicroelectronics")
    print("==================================================\n")
    
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    start_time_dt = datetime.now()
    
    print("--- ÉTAPE 1 : SCAN DES CATÉGORIES ---")
    try:
        scan_stats = run_scan()
        # Récupérer les IDs de catégories ayant des items récents
        # → utilisés pour cibler uniquement les catégories non vides à l'étape 2
        active_forum_ids = scan_stats.get("active_forum_ids")
        active_kb_ids    = scan_stats.get("active_kb_ids")
    except Exception as e:
        print(f"Erreur lors du scan: {e}")
        scan_stats = {"error": str(e)}
        active_forum_ids = None  # fallback: run_extract utilisera la liste complète
        active_kb_ids    = None
        
    print("\n--- ÉTAPE 2 : EXTRACTION ---")
    try:
        extract_stats = run_extract(
            active_forum_ids=active_forum_ids,
            active_kb_ids=active_kb_ids,
        )
    except Exception as e:
        print(f"Erreur lors de l'extraction: {e}")
        extract_stats = {"error": str(e)}
        
    print("\n--- ÉTAPE 3 : PRÉPARATION RAG ---")
    try:
        prepare_stats = run_prepare()
    except Exception as e:
        print(f"Erreur lors de la préparation RAG: {e}")
        prepare_stats = {"error": str(e)}
        
    end_time_dt = datetime.now()
    duration = (end_time_dt - start_time_dt).total_seconds()

    rag_start_date = os.getenv("RAG_START_DATE", "")

    # Extraire les stats Forums / KB depuis le rapport de l'étape 3
    # pour les placer à la RACINE du JSON (sections séparées, facile à lire)
    f_stats = prepare_stats.get("forums_stats", {}) if isinstance(prepare_stats, dict) else {}
    k_stats = prepare_stats.get("kb_stats",     {}) if isinstance(prepare_stats, dict) else {}

    # Création du grand rapport final (Statistiques et KPIs globaux)
    final_report = {
        "pipeline_run_info": {
            "start_time":            start_time_dt.isoformat(),
            "end_time":              end_time_dt.isoformat(),
            "total_duration_seconds": round(duration, 2),
            "rag_start_date":        rag_start_date,
        },

        # ── Étape 1 : Scan ──────────────────────────────────────────
        # active_*_ids = catégories avec au moins 1 item récent (détectées par le scan)
        # categories_empty = catégories sautées à l'étape 2 (0 items récents)
        "step_1_scan": {
            "categories_scanned_forums": _TOTAL_FORUM_CATS,
            "categories_active_forums":  len(scan_stats.get("active_forum_ids", [])) if isinstance(scan_stats, dict) else 0,
            "categories_empty_forums":   _TOTAL_FORUM_CATS - len(scan_stats.get("active_forum_ids", [])) if isinstance(scan_stats, dict) else 0,
            "categories_scanned_kb":     _TOTAL_KB_CATS,
            "categories_active_kb":      len(scan_stats.get("active_kb_ids", [])) if isinstance(scan_stats, dict) else 0,
            "categories_empty_kb":       _TOTAL_KB_CATS - len(scan_stats.get("active_kb_ids", [])) if isinstance(scan_stats, dict) else 0,
            "total_recent_items_forums": scan_stats.get("total_forums", 0) if isinstance(scan_stats, dict) else 0,
            "total_recent_items_kb":     scan_stats.get("total_kb", 0)    if isinstance(scan_stats, dict) else 0,
            "active_forum_ids":          scan_stats.get("active_forum_ids", []) if isinstance(scan_stats, dict) else [],
            "active_kb_ids":             scan_stats.get("active_kb_ids",   []) if isinstance(scan_stats, dict) else [],
        },

        # ── Étape 2 : Extraction ───────────────────────────────────
        # Nombre d'items extraits par type + pages visitées + durée
        "step_2_extract": {
            **({k: v for k, v in extract_stats.items()} if isinstance(extract_stats, dict) else {"error": str(extract_stats)}),
        },

        # ── Étape 3 : RAG — Forums (KPIs séparés) ────────────────────────────
        "step_3_forums_stats": f_stats,

        # ── Étape 3 : RAG — Knowledge Base (KPIs séparés) ────────────────────
        "step_3_kb_stats": k_stats,

        # ── Résumé global ─────────────────────────────────────────────────────
        "step_3_summary": prepare_stats.get("summary_totals", {}) if isinstance(prepare_stats, dict) else {},

        # ── Détails URLs acceptées / rejetées ─────────────────────────────────
        "step_3_details": prepare_stats.get("details", {}) if isinstance(prepare_stats, dict) else {},
    }

    # Sauvegarde des statistiques globales
    run_name = f"pipeline_stats_{start_time_dt.strftime('%Y%m%d_%H%M%S')}.json"
    report_path = LOGS_DIR / run_name

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=4)
        
    # Copie pour le dashboard
    dashboard_stats = BASE_DIR / "Dashboard" / "latest_stats.json"
    dashboard_stats.parent.mkdir(parents=True, exist_ok=True)
    with open(dashboard_stats, "w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=4)

    print("\n==================================================")
    print("   PIPELINE TERMINÉ AVEC SUCCÈS")
    print(f"   Durée totale : {duration:.1f} secondes")
    print(f"   KPIs sauvegardés dans : {report_path}")
    print(f"   Dashboard mis à jour : {dashboard_stats}")
    print("==================================================\n")


if __name__ == "__main__":
    main()
