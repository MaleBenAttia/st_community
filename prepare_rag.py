#!/usr/bin/env python3
"""
Préparation RAG - STMicroelectronics

Ce script lit les fichiers JSON bruts générés par main.py dans le dossier `output/`,
applique des filtres, nettoie le contenu HTML (en Markdown), récupère les réponses 
acceptées pour les forums via un appel API supplémentaire, et sauvegarde le résultat 
propre dans `rag-ready/`.
Génère également un rapport d'exécution (JSON).
"""

import os
import re
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import markdownify

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

# Paramètres RAG
RAG_START_DATE_STR = os.getenv("RAG_START_DATE", "2026-03-15T00:00:00Z")
try:
    RAG_START_DATE = datetime.fromisoformat(RAG_START_DATE_STR.replace("Z", "+00:00"))
except ValueError:
    RAG_START_DATE = datetime(2026, 3, 15, tzinfo=timezone.utc)

MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 2
REQUEST_DELAY_SECONDS = 0.3

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
RAG_READY_DIR = BASE_DIR / "rag-ready"

# --------------------------------------------------------------------------
# Authentification et API (repris de main.py)
# --------------------------------------------------------------------------

def get_access_token() -> str:
    """Récupère un access token via OAuth2 Client Credentials (avec cache)."""
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Avertissement: CLIENT_ID ou CLIENT_SECRET manquant pour l'API.")
        print("La récupération des réponses de forums pourrait échouer si l'API exige une auth.")
        return ""

    cache_file = Path(__file__).parent / ".token_cache.json"
    
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
    auth = None

    if AUTH_METHOD == "basic":
        auth = (CLIENT_ID, CLIENT_SECRET)
    elif AUTH_METHOD == "body":
        data["client_id"] = CLIENT_ID
        data["client_secret"] = CLIENT_SECRET
    else:
        sys.exit(f"ERREUR : AUTH_METHOD invalide '{AUTH_METHOD}'.")

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

def api_get(url: str, headers: dict, params: dict = None) -> dict:
    """GET avec retry + backoff exponentiel en cas d'erreur ou de rate limit (429)."""
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        
        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:
            wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                wait = float(retry_after)
            print(f"  [RATE LIMIT] 429 reçu, pause de {wait}s...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"  [ERREUR SERVEUR] {resp.status_code}, pause de {wait}s...")
            time.sleep(wait)
            continue

        resp.raise_for_status()

    raise Exception(f"Échec après {MAX_RETRIES} tentatives sur {url}")

# --------------------------------------------------------------------------
# Fonctions de Traitement HTML
# --------------------------------------------------------------------------

def clean_html_to_markdown(html_content: str) -> str:
    """Convertit du HTML en Markdown propre pour le RAG (un paragraphe par bloc)."""
    if not html_content:
        return ""
    md_text = markdownify.markdownify(html_content, heading_style="ATX")
    # Conserve les paragraphes originaux séparés par des sauts de ligne clairs
    lines = [line.strip() for line in md_text.splitlines() if line.strip()]
    return "\n\n".join(lines)

def extract_images_from_html(html_content: str) -> list:
    """Extrait toutes les URLs d'images d'un contenu HTML."""
    if not html_content:
        return []
    soup = BeautifulSoup(html_content, 'html.parser')
    images = []
    for img in soup.find_all('img'):
        src = img.get('src')
        if src and src.startswith('http'):
            images.append(src)
    return images

def is_recent_enough(published_at_raw: str) -> bool:
    """Vérifie si la date de publication est supérieure au seuil RAG_START_DATE."""
    if not published_at_raw:
        return False
    try:
        pub_date = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
        return pub_date >= RAG_START_DATE
    except ValueError:
        return False

# --------------------------------------------------------------------------
# Traitement par Type
# --------------------------------------------------------------------------

def process_forums(token: str) -> dict:
    input_dir = OUTPUT_DIR / "forums"
    output_dir = RAG_READY_DIR / "forums"
    output_dir.mkdir(parents=True, exist_ok=True)

    ok_urls = []
    filtered_urls = []
    processed_count = 0
    rag_items = []  # liste consolidée pour le fichier unique

    # Stats replies
    total_replies = 0
    reply_counts = []          # liste de (reply_count, title, url)
    total_views = 0
    total_images = 0
    filtered_no_best_answer = 0
    filtered_too_old = 0
    filtered_other = 0

    if not input_dir.exists():
        print("Aucun dossier de forums trouvé.")
        return {"count": 0, "ok_urls": [], "filtered_urls": [], "stats": {}}

    headers = {"Authorization": f"Bearer {token}"} if token else {}

    print("\n--- Traitement des Forums ---")
    for file_path in input_dir.glob("*.json"):
        with open(file_path, "r", encoding="utf-8") as f:
            topic = json.load(f)

        topic_url = topic.get("_seoUrl", file_path.name)

        out_path = output_dir / file_path.name
        # Toujours traiter le fichier pour appliquer les corrections de scraping récents

        # 1. Filtre: bestAnswer doit être true
        if not topic.get("bestAnswer", False):
            filtered_urls.append({"url": topic_url, "reason": "no_best_answer"})
            filtered_no_best_answer += 1
            continue

        # 2. Filtre: Date
        if not is_recent_enough(topic.get("publishedAt")):
            filtered_urls.append({"url": topic_url, "reason": "too_old"})
            filtered_too_old += 1
            continue

        topic_id = topic.get("id")
        if not topic_id:
            filtered_urls.append({"url": topic_url, "reason": "no_id"})
            filtered_other += 1
            continue

        print(f"Traitement du topic forum {topic_id}...")

        # 3. Nettoyage HTML -> Markdown lisible
        question_md = clean_html_to_markdown(topic.get("content", ""))
        question_images = extract_images_from_html(topic.get("content", ""))
        
        all_images = set(question_images)
        if topic.get("featuredImage"):
            all_images.add(topic.get("featuredImage"))

        # Traitement des réponses extraites par main.py
        scraped_replies = topic.get("scraped_replies", [])
        best_answers = []

        if scraped_replies:
            for reply in scraped_replies:
                html_reply = reply.get("html", "")
                is_best = reply.get("is_best", False)
                md_reply = clean_html_to_markdown(html_reply)
                
                if md_reply:
                    if is_best and md_reply not in best_answers:
                        best_answers.append(md_reply)
                    reply_images = extract_images_from_html(html_reply)
                    all_images.update(reply_images)

        r = topic.get("replyCount", 0) or 0
        total_replies += r
        total_views += topic.get("views", 0) or 0
        total_images += len(all_images)
        reply_counts.append((r, topic.get("title", ""), topic_url))

        rag_item = {
            "id": str(topic_id),
            "publicId": str(topic.get("publicId", "")),
            "title": topic.get("title", ""),
            "url": topic_url,
            "category": topic.get("categoryName", ""),
            "tags": topic.get("tags", []),
            "published_at": topic.get("publishedAt", ""),
            "views": topic.get("views", 0),
            "reply_count": r,
            "best_answer": True,
        }

        # S'il y a 1 seule réponse acceptée -> "best_answer_content"
        # S'il y en a plusieurs -> "best_answer_content1", "best_answer_content2", etc.
        if len(best_answers) == 1:
            rag_item["best_answer_content"] = best_answers[0]
        elif len(best_answers) > 1:
            for idx, ans in enumerate(best_answers, start=1):
                rag_item[f"best_answer_content{idx}"] = ans
        else:
            rag_item["best_answer_content"] = ""

        rag_item["content_text"] = question_md
        rag_item["images"] = list(all_images)
        rag_item["author"] = topic.get("author", {}).get("username", "")

        # Silhouette exacte demandée : englobé dans {"forum": [ ... ]}
        wrapped_item = {"forum": [rag_item]}

        out_path = output_dir / file_path.name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(wrapped_item, f, ensure_ascii=False, indent=4)

        processed_count += 1
        ok_urls.append(topic_url)
        rag_items.append(rag_item)

    # ── Calcul des stats finales ─────────────────────────────────────────
    total_input = processed_count + filtered_no_best_answer + filtered_too_old + filtered_other
    avg_replies  = round(total_replies / processed_count, 2) if processed_count > 0 else 0
    avg_views    = round(total_views   / processed_count, 2) if processed_count > 0 else 0
    min_replies  = min(r for r, _, _ in reply_counts) if reply_counts else 0
    max_replies  = max(r for r, _, _ in reply_counts) if reply_counts else 0
    resolution_rate = round(processed_count / total_input * 100, 1) if total_input > 0 else 0
    pct_no_best  = round(filtered_no_best_answer / total_input * 100, 1) if total_input > 0 else 0
    pct_too_old  = round(filtered_too_old        / total_input * 100, 1) if total_input > 0 else 0

    # Distribution des réponses par tranche
    dist = {"0": 0, "1": 0, "2_to_5": 0, "6_plus": 0}
    for r, _, _ in reply_counts:
        if   r == 0: dist["0"]      += 1
        elif r == 1: dist["1"]      += 1
        elif r <= 5: dist["2_to_5"] += 1
        else:        dist["6_plus"] += 1

    # Top 3 posts les plus répondus
    top3_replied = sorted(reply_counts, key=lambda x: x[0], reverse=True)[:3]
    top3_replied_out = [{"title": t, "url": u, "reply_count": r} for r, t, u in top3_replied]

    # Top 3 posts les plus vus (on recollecte depuis rag_items)
    top3_viewed = sorted(rag_items, key=lambda x: x.get("views", 0), reverse=True)[:3]
    top3_viewed_out = [{"title": x["title"], "url": x["url"], "views": x.get("views", 0)} for x in top3_viewed]

    # Breakdown par catégorie
    cat_breakdown: dict = {}
    for item in rag_items:
        cat = item.get("category", "Unknown")
        cat_breakdown.setdefault(cat, {"accepted": 0, "total_replies": 0, "total_views": 0})
        cat_breakdown[cat]["accepted"]      += 1
        cat_breakdown[cat]["total_replies"] += item.get("reply_count", 0)
        cat_breakdown[cat]["total_views"]   += item.get("views", 0)

    stats = {
        # Volume & Filtrage
        "total_input_files":              total_input,
        "accepted":                       processed_count,
        "accepted_pct":                   resolution_rate,
        "rejected_total":                 total_input - processed_count,
        "rejected_no_best_answer":        filtered_no_best_answer,
        "rejected_no_best_answer_pct":    pct_no_best,
        "rejected_too_old":               filtered_too_old,
        "rejected_too_old_pct":           pct_too_old,
        "rejected_other":                 filtered_other,
        # Réponses (replies)
        "total_replies":                  total_replies,
        "avg_replies_per_post":           avg_replies,
        "min_replies":                    min_replies,
        "max_replies":                    max_replies,
        "reply_distribution": {
            "0_replies":    dist["0"],
            "1_reply":      dist["1"],
            "2_to_5_replies": dist["2_to_5"],
            "6_plus_replies": dist["6_plus"],
        },
        "top3_most_replied_posts":        top3_replied_out,
        # Vues
        "total_views":                    total_views,
        "avg_views_per_post":             avg_views,
        "top3_most_viewed_posts":         top3_viewed_out,
        # Images
        "total_images_in_content":        total_images,
        # Par catégorie
        "by_category":                    cat_breakdown,
    }

    print(f"  -> {processed_count} sujets de forum préparés pour le RAG.")
    print(f"     Taux de résolution : {resolution_rate}%")
    print(f"     Réponses totales   : {total_replies} | Moyenne : {avg_replies} | Max : {max_replies}")
    if top3_replied:
        try:
            print(f"     Post le + répondu  : {top3_replied[0][1][:80]}")
        except Exception:
            pass
    return {"count": processed_count, "ok_urls": ok_urls, "filtered_urls": filtered_urls, "stats": stats, "rag_items": rag_items}


def process_knowledge_base() -> dict:
    input_dir = OUTPUT_DIR / "knowledge_base"
    output_dir = RAG_READY_DIR / "knowledge_base"
    output_dir.mkdir(parents=True, exist_ok=True)

    ok_urls = []
    filtered_urls = []
    processed_count = 0
    total_images = 0
    filtered_too_old = 0
    rag_items = []  # liste consolidée pour le fichier unique

    if not input_dir.exists():
        print("Aucun dossier Knowledge Base trouvé.")
        return {"count": 0, "ok_urls": [], "filtered_urls": [], "stats": {}}

    print("\n--- Traitement de la Knowledge Base ---")
    for file_path in input_dir.glob("*.json"):
        with open(file_path, "r", encoding="utf-8") as f:
            article = json.load(f)

        article_url = article.get("_seoUrl", file_path.name)

        out_path = output_dir / file_path.name

        # 1. Filtre: Date
        if not is_recent_enough(article.get("publishedAt")):
            filtered_urls.append({"url": article_url, "reason": "too_old"})
            filtered_too_old += 1
            continue

        # 2. Nettoyage HTML -> Markdown
        html_content = article.get("content", "")
        article_md = clean_html_to_markdown(html_content)

        # 3. Consolidation des images
        all_images = set()
        if article.get("featuredImage"):
            all_images.add(article.get("featuredImage"))
        content_images = extract_images_from_html(html_content)
        all_images.update(content_images)
        total_images += len(all_images)

        # 4. Génération JSON RAG
        rag_item = {
            "id": str(article.get("id", "")),
            "publicId": str(article.get("publicId", "")),
            "type": "knowledge_base",
            "title": article.get("title", ""),
            "url": article_url,
            "category": article.get("categoryName", ""),
            "tags": article.get("tags", []),
            "published_at": article.get("publishedAt", ""),
            "views": article.get("views", 0),
            "content_text": article_md,
            "images": list(all_images),
            "author": article.get("author", {}).get("username", "")
        }

        # Silhouette exacte demandée : englobé dans {"kb": [ ... ]}
        wrapped_item = {"kb": [rag_item]}

        out_path = output_dir / file_path.name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(wrapped_item, f, ensure_ascii=False, indent=4)

        processed_count += 1
        ok_urls.append(article_url)
        rag_items.append(rag_item)

    total_input = processed_count + filtered_too_old
    accepted_pct = round(processed_count / total_input * 100, 1) if total_input > 0 else 0
    too_old_pct  = round(filtered_too_old  / total_input * 100, 1) if total_input > 0 else 0

    # Breakdown par catégorie KB
    cat_breakdown_kb: dict = {}
    for item in rag_items:
        cat = item.get("category", "Unknown")
        cat_breakdown_kb.setdefault(cat, {"accepted": 0, "total_views": 0})
        cat_breakdown_kb[cat]["accepted"]    += 1
        cat_breakdown_kb[cat]["total_views"] += item.get("views", 0)

    stats = {
        "total_input_files":      total_input,
        "accepted":               processed_count,
        "accepted_pct":           accepted_pct,
        "rejected_too_old":       filtered_too_old,
        "rejected_too_old_pct":   too_old_pct,
        "total_images_in_content": total_images,
        "by_category":            cat_breakdown_kb,
    }

    print(f"  -> {processed_count} articles préparés pour le RAG.")
    return {"count": processed_count, "ok_urls": ok_urls, "filtered_urls": filtered_urls, "stats": stats, "rag_items": rag_items}

# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

LOGS_DIR = Path(__file__).parent / "logs"

def run_prepare() -> dict:
    print("Démarrage du pipeline de préparation RAG...")
    start_time_dt = datetime.now()
    start_time_iso = start_time_dt.isoformat()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    token = get_access_token()

    forums_report = process_forums(token)
    kb_report = process_knowledge_base()

    end_time_dt = datetime.now()
    end_time_iso = end_time_dt.isoformat()
    duration = (end_time_dt - start_time_dt).total_seconds()

    f_stats = forums_report.get("stats", {})
    k_stats = kb_report.get("stats", {})

    total_accepted = forums_report["count"] + kb_report["count"]
    total_input    = f_stats.get("total_input_files", 0) + k_stats.get("total_input_files", 0)
    global_rate    = round(total_accepted / total_input * 100, 1) if total_input > 0 else 0

    # Création du rapport complet
    report = {
        "run_info": {
            "start_time": start_time_iso,
            "end_time": end_time_iso,
            "duration_seconds": duration
        },
        "filters_applied": {
            "RAG_START_DATE": RAG_START_DATE_STR,
            "forum_best_answer_required": True
        },
        "summary_totals": {
            "total_input_files": total_input,
            "total_accepted": total_accepted,
            "total_filtered_out": total_input - total_accepted,
            "global_acceptance_rate_pct": global_rate,
            "forums_accepted": forums_report["count"],
            "kb_accepted": kb_report["count"],
        },
        "forums_stats": f_stats,
        "kb_stats": k_stats,
        "details": {
            "forums": {
                "ok_urls": forums_report["ok_urls"],
                "filtered_out_urls": forums_report["filtered_urls"]
            },
            "knowledge_base": {
                "ok_urls": kb_report["ok_urls"],
                "filtered_out_urls": kb_report["filtered_urls"]
            }
        }
    }

    # Affichage résumé console
    print("\n" + "="*55)
    print("  RÉSUMÉ DE LA PRÉPARATION RAG")
    print("="*55)
    print(f"  Durée                  : {duration:.1f} sec")
    print(f"  Fichiers analysés      : {total_input}")
    print(f"  Acceptés (RAG-ready)   : {total_accepted} ({global_rate}%)")
    print(f"  Rejetés                : {total_input - total_accepted}")
    print(f"  --- Forums ---")
    print(f"  Acceptés               : {forums_report['count']} ({f_stats.get('accepted_pct',0)}%)")
    print(f"  Sans best answer       : {f_stats.get('rejected_no_best_answer', 0)} ({f_stats.get('rejected_no_best_answer_pct',0)}%)")
    print(f"  Trop anciens           : {f_stats.get('rejected_too_old', 0)} ({f_stats.get('rejected_too_old_pct',0)}%)")
    print(f"  Total réponses         : {f_stats.get('total_replies', 0)}")
    print(f"  Moy. réponses/post     : {f_stats.get('avg_replies_per_post', 0)}")
    print(f"  Min/Max réponses       : {f_stats.get('min_replies',0)} / {f_stats.get('max_replies', 0)}")
    print(f"  Total vues forums      : {f_stats.get('total_views', 0)} | Moy: {f_stats.get('avg_views_per_post',0)}")
    dist = f_stats.get('reply_distribution', {})
    print(f"  Distrib. réponses      : 0={dist.get('0_replies',0)}  1={dist.get('1_reply',0)}  2-5={dist.get('2_to_5_replies',0)}  6+={dist.get('6_plus_replies',0)}")
    top3 = f_stats.get('top3_most_replied_posts', [])
    if top3:
        try:
            top_title = str(top3[0].get('title',''))[:55]
            top_title.encode(sys.stdout.encoding or 'utf-8')
        except Exception:
            top_title = top_title.encode('ascii','ignore').decode()
        print(f"  Post + répondu         : {top_title} ({top3[0].get('reply_count',0)} rép.)")
    print(f"  --- Knowledge Base ---")
    print(f"  Acceptés               : {kb_report['count']} ({k_stats.get('accepted_pct',0)}%)")
    print(f"  Trop anciens           : {k_stats.get('rejected_too_old', 0)} ({k_stats.get('rejected_too_old_pct',0)}%)")
    print("="*55)

    return report

def main():
    run_prepare()

if __name__ == "__main__":
    main()
