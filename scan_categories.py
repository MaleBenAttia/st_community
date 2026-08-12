#!/usr/bin/env python3
"""
Scanneur de catégories (Filtré par date) - STMicroelectronics

Ce script interroge l'API inSided pour chaque catégorie et compte UNIQUEMENT 
les articles/questions publiés APRÈS la date spécifiée dans `.env` (RAG_START_DATE).
Il génère un rapport dans `scan_report.txt`.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

load_dotenv(override=True)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
AUTH_URL = os.getenv("AUTH_URL", "https://api2-eu-west-1.insided.com/oauth2/token")
API_BASE_URL = os.getenv("API_BASE_URL", "https://api2-eu-west-1.insided.com/v2")
AUTH_METHOD = os.getenv("AUTH_METHOD", "basic").lower()
OAUTH_SCOPE = os.getenv("OAUTH_SCOPE", "read")

# Date limite
RAG_START_DATE_STR = os.getenv("RAG_START_DATE", "2026-03-15T00:00:00Z")
try:
    RAG_START_DATE = datetime.fromisoformat(RAG_START_DATE_STR.replace("Z", "+00:00"))
except ValueError:
    RAG_START_DATE = datetime(2026, 3, 15, tzinfo=timezone.utc)

KB_CATEGORIES = [60, 61, 62, 63, 64, 65, 66, 68]
FORUM_CATEGORIES = [25, 26, 28, 29, 30, 31, 32, 33, 34, 35, 36, 39, 46, 48, 49, 
                    50, 51, 52, 53, 54, 57, 118, 120, 121, 133, 134, 138, 142, 151]

PAGE_SIZE = 100
MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 2
REQUEST_DELAY_SECONDS = 0.3

# --------------------------------------------------------------------------
# Authentification et API
# --------------------------------------------------------------------------

def get_access_token() -> str:
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("ERREUR : CLIENT_ID ou CLIENT_SECRET manquants dans le .env.")

    cache_file = Path(__file__).parent / ".token_cache.json"
    
    import json
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                cache = json.load(f)
            last_login = cache.get("last_login", 0)
            token = cache.get("access_token", "")
            if token and (time.time() - last_login) < 3500:
                print("[AUTH] Utilisation du token en cache (valide).")
                return token
        except Exception:
            pass

    data = {"grant_type": "client_credentials", "scope": OAUTH_SCOPE}
    auth = (CLIENT_ID, CLIENT_SECRET) if AUTH_METHOD == "basic" else None
    if AUTH_METHOD == "body":
        data["client_id"] = CLIENT_ID
        data["client_secret"] = CLIENT_SECRET

    resp = requests.post(AUTH_URL, data=data, auth=auth, timeout=30)
    if resp.status_code != 200:
        sys.exit(f"ERREUR AUTH ({resp.status_code}) : {resp.text}")

    token = resp.json().get("access_token")
    try:
        with open(cache_file, "w") as f:
            json.dump({"access_token": token, "last_login": time.time()}, f)
    except Exception:
        pass

    return token

def is_recent_enough(published_at_raw: str) -> bool:
    if not published_at_raw:
        return False
    try:
        pub_date = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
        return pub_date >= RAG_START_DATE
    except ValueError:
        return False

def count_recent_items(category_id: int, token: str) -> dict:
    """Parcourt les pages et compte uniquement les items post-RAG_START_DATE."""
    url = f"{API_BASE_URL}/topics"
    headers = {"Authorization": f"Bearer {token}"}
    
    count_recent = 0
    cat_name = f"Category {category_id}"
    page = 1
    
    while True:
        params = {"categoryId": category_id, "pageSize": PAGE_SIZE, "page": page}
        
        # Gestion des retries
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                success = True
                break
            if resp.status_code in [429, 500, 502, 503, 504]:
                wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                time.sleep(wait)
                continue
            resp.raise_for_status()

        if not success:
            return {"id": category_id, "name": cat_name, "count": "Erreur"}

        data = resp.json()
        results = data.get("result", [])
        
        if not results:
            break # Plus aucun résultat
            
        if page == 1 and len(results) > 0:
            cat_name = results[0].get("categoryName", cat_name)
            
        stop_pagination = False
        
        for item in results:
            if is_recent_enough(item.get("publishedAt")):
                count_recent += 1
            else:
                # L'API inSided retourne généralement les topics du plus récent au plus ancien.
                # Si on tombe sur un topic trop vieux, on peut (en théorie) arrêter.
                # Mais par sécurité on vérifie au moins la page entière.
                pass
                
        # Pour être sûr de ne rien rater si jamais l'ordre n'est pas strict, 
        # on continue si la page contient au moins 1 élément récent.
        # Sinon, cela veut dire que toute la page est trop vieille (ou vide) -> on s'arrête
        has_recent_in_page = any(is_recent_enough(i.get("publishedAt")) for i in results)
        
        if not has_recent_in_page:
            break
            
        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    return {"id": category_id, "name": cat_name, "count": count_recent}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

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
        line = f"  - ID {cat_id:3d} | Items récents : {count:4} | Nom : {info['name']}"
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
        line = f"  - ID {cat_id:3d} | Items récents : {count:4} | Nom : {info['name']}"
        print(line)
        report_lines.append(line)
        time.sleep(REQUEST_DELAY_SECONDS)
        
    report_lines.append(f"> TOTAL ITEMS RÉCENTS DANS KNOWLEDGE BASE : {total_kb}\n")

    # SAUVEGARDE DANS logs/
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    report_path = logs_dir / f"scan_report_{time.strftime('%Y%m%d_%H%M%S')}.txt"
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

def main():
    run_scan()

if __name__ == "__main__":
    main()
