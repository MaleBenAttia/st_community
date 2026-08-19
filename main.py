#!/usr/bin/env python3
"""
Étape 2 du pipeline - Collecte de contenu Gainsight/inSided (communauté STMicroelectronics)

Objectif :
  - Extraire les items (Knowledge Base + Product Forums) publiés après RAG_START_DATE
    via l'API inSided (paginateur avec arrêt anticipé sur les pages trop anciennes).
  - Scraper les réponses HTML de chaque topic de forum en parallèle (3 workers,
    jitter anti-blocage + pause longue après 5 échecs consécutifs) pour récupérer
    best answer, auteurs et rôles.
  - Remplir les rôles d'auteurs via la référence statique author_roles.json (source de
    vérité manuelle) et signaler les auteurs non résolus.
  - Sauvegarder un fichier JSON par item dans output/ (nom = {publicId}.json,
    rangé par catégorie).
   - Reprise incrémentale intelligente : un topic déjà résolu (bestAnswer true)
     est sauté ; un topic non résolu est re-vérifié côté API (bestAnswer frais,
     déjà présent dans la pagination) et re-scrapé dès qu'il devient résolu
     (le best answer peut être marqué aujourd'hui mais pas hier). Les métadonnées
     (views, replyCount) des topics sautés sont rafraîchies sans re-scrape.
   - Force re-scrape : flag force_rescrape=True (ou env FULL_RESCRAPE=1) pour
     tout re-scraper sans tenir compte de la reprise incrémentale.

Point d'entrée : run_pipeline.py (scan → extraction → rôles → RAG).
"""

import json
import random
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import author_roles
import run_logger

from config import (
    API_BASE_URL,
    DATE_THRESHOLD,
    FORUM_CATEGORIES,
    KB_CATEGORIES,
    OUTPUT_DIR,
    OUTPUT_FORUMS_DIR,
    OUTPUT_KB_DIR,
    PAGE_SIZE,
    REQUEST_DELAY_SECONDS,
    SCRAPE_DELAY_SECONDS,
    SITE_BASE_URL,
    TARGET_COUNT,
    api_get,
    get_access_token,
    slugify,
)

# Auteurs dont le role reste vide apres le repli statique author_roles.json (message d'erreur final)
UNRESOLVED = set()

# Anti-blocage scraping : pause longue après N échecs consécutifs (détection blocage IP)
CONSECUTIVE_SCRAPE_FAILURES_LIMIT = 5
SCRAPE_BLOCK_PAUSE_SECONDS = (30, 60)
_scrape_failures = 0
_scrape_failures_lock = threading.Lock()

# Session réutilisable (HTTP Keep-Alive) pour accélérer les requêtes HTML publiques.
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})


# --------------------------------------------------------------------------
# Anti-blocage
# --------------------------------------------------------------------------

def _register_scrape_failure() -> None:
    """Compte un échec ; déclenche une pause longue après N échecs consécutifs (blocage IP)."""
    global _scrape_failures
    pause = None
    with _scrape_failures_lock:
        _scrape_failures += 1
        if _scrape_failures >= CONSECUTIVE_SCRAPE_FAILURES_LIMIT:
            _scrape_failures = 0
            pause = random.uniform(*SCRAPE_BLOCK_PAUSE_SECONDS)
    if pause:
        msg = (f"[SCRAPE] Détection d'un blocage ({CONSECUTIVE_SCRAPE_FAILURES_LIMIT} "
               f"échecs consécutifs). Pause de {pause:.0f}s...")
        print(msg)
        run_logger.error(msg)
        time.sleep(pause)


def _reset_scrape_failures() -> None:
    """Réinitialise le compteur d'échecs consécutifs (un scrape a réussi)."""
    global _scrape_failures
    with _scrape_failures_lock:
        _scrape_failures = 0


def build_seo_url(item: dict) -> str:
    """Reconstruit l'URL SEO-friendly : {base}/{category-slug}-{categoryId}/{title-slug}-{publicId}"""
    category_slug = slugify(item.get("categoryName", ""))
    title_slug = slugify(item.get("title", ""))
    category_id = item.get("categoryId")
    public_id = item.get("publicId")
    return f"{SITE_BASE_URL}/{category_slug}-{category_id}/{title_slug}-{public_id}"


# --------------------------------------------------------------------------
# Scraping HTML des réponses
# --------------------------------------------------------------------------

def scrape_all_replies(url: str) -> list:
    """
    Scrape la page publique d'un topic et extrait toutes ses réponses.
    Extrait les réponses chronologiques et identifie la réponse acceptée (best answer).
    Intègre un système de réessai (retry) pour éviter les blocages serveur (Rate Limit / Timeout).
    """
    replies = []
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        # Jitter aléatoire autour de SCRAPE_DELAY_SECONDS pour éviter les salves synchronisées
        time.sleep(random.uniform(SCRAPE_DELAY_SECONDS * 0.6, SCRAPE_DELAY_SECONDS * 1.4))
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code != 200:
                # Statut non-200 (429 rate limit, 403 blocage, 5xx...) -> retry avec backoff
                msg = f"[Scrape] HTTP {resp.status_code} sur {url} (Tentative {attempt}/{max_retries})"
                print(msg)
                run_logger.error(msg)
                _register_scrape_failure()
                retry_after = resp.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else (2 ** attempt))
                continue

            _reset_scrape_failures()

            soup = BeautifulSoup(resp.content, 'html.parser')

            # ÉTAPE 1 : Détections prioritaires de la réponse épinglée (Best Answer / Solved Box)
            best_answer_box = (
                soup.find(class_='qa-answer-field') or
                soup.find(class_='reply-flexbox--bestanswer') or
                soup.find(attrs={"data-qa": "qa-answer-field"})
            )
            best_answer_html = None
            if best_answer_box:
                content_div = best_answer_box.find(class_='post__content') or best_answer_box.find(class_='qa-qa-post-content')
                if content_div:
                    best_answer_html = str(content_div)

            # ÉTAPE 2 : Conteneur principal du fil de discussion
            thread_container = (
                soup.find(class_='paginated-threaded-replies') or
                soup.find(class_='threaded-replies') or
                soup.find(class_='thread__list') or
                soup.find(class_='replies-list') or
                soup
            )

            # ÉTAPE 3 : Extrait les posts individuels du fil
            post_divs = thread_container.find_all(class_="threaded-reply-item")
            if not post_divs:
                post_divs = thread_container.find_all(
                    lambda tag: tag.name in ['div', 'article', 'li']
                    and tag.get('class')
                    and any('post' in c.lower() for c in tag.get('class'))
                    and not any('list' in c.lower() or 'container' in c.lower() for c in tag.get('class'))
                )

            found_best = False
            for pd in post_divs:
                is_best = False
                if pd.find(attrs={"data-qa": "pill-best-answer"}) or pd.find(class_="best-answer"):
                    is_best = True

                content_div = pd.find(class_='qa-qa-post-content') or pd.find(class_='post__content')
                if content_div:
                    html = str(content_div)

                    if best_answer_html and html == best_answer_html:
                        is_best = True

                    if is_best:
                        found_best = True

                    author_el = pd.find(class_='qa-username')
                    rank_el = pd.find(class_='rank-title')
                    author_name = author_el.get_text(strip=True) if author_el else ""
                    author_role = rank_el.get_text(strip=True) if rank_el else ""

                    existing = next((r for r in replies if r['html'] == html), None)
                    if existing:
                        if is_best:
                            existing['is_best'] = True
                    else:
                        replies.append({
                            "is_best": is_best,
                            "html": html,
                            "author": author_name,
                            "role": author_role,
                        })

            # Si une box best answer est présente mais n'a pas été retrouvée dans les posts extraits
            if best_answer_html and not found_best:
                existing = next((r for r in replies if r['html'] == best_answer_html), None)
                if existing:
                    existing['is_best'] = True
                else:
                    best_author = best_answer_box.find(class_='qa-username')
                    best_rank = best_answer_box.find(class_='rank-title')
                    box_author = ""
                    reply_label = best_answer_box.find(class_='reply-label')
                    if reply_label:
                        label_text = reply_label.get_text(" ", strip=True)
                        if "by" in label_text:
                            box_author = label_text.split("by", 1)[1].strip()
                    replies.insert(0, {
                        "is_best": True,
                        "html": best_answer_html,
                        "author": best_author.get_text(strip=True) if best_author else box_author,
                        "role": best_rank.get_text(strip=True) if best_rank else "",
                    })
                    found_best = True

            author_roles.fill_missing_roles(replies)
            UNRESOLVED.update(author_roles.unresolved_authors(replies))

            return replies # Succès, on quitte la boucle de retry

        except Exception as e:
            print(f"  [Scrape Error] {url} -> {e} (Tentative {attempt}/{max_retries})")
            run_logger.error(f"[Scrape Error] {url} -> {e} (Tentative {attempt}/{max_retries})")
            _register_scrape_failure()
            time.sleep(2 ** attempt) # Backoff exponentiel

    return replies # Renvoie ce qu'on a (probablement vide) si échec total


# --------------------------------------------------------------------------
# Rafraîchissement léger des métadonnées d'un topic déjà scrapé (sans re-scrape)
# --------------------------------------------------------------------------

def _refresh_metadata(existing_file: Path, existing: dict, fresh: dict) -> None:
    """Met à jour views/replyCount/bestAnswer sur le fichier existant si l'API est plus récente."""
    changed = False
    for key in ("views", "replyCount", "bestAnswer", "lastActivityAt", "closed", "status"):
        fresh_val = fresh.get(key)
        if fresh_val is not None and existing.get(key) != fresh_val:
            existing[key] = fresh_val
            changed = True
    if changed:
        try:
            existing_file.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"  [WARN] Échec rafraîchissement métadonnées {existing_file.name} -> {e}")


# --------------------------------------------------------------------------
# Collecte paginée + filtre de date, jusqu'à obtenir N items valides
# --------------------------------------------------------------------------

def collect_items(category_id: str, token: str, target_count: int, label: str, force_rescrape: bool = False, out_dir: Path = None) -> dict:
    """
    Parcourt les pages de /v2/topics pour une catégorie donnée, avec reprise sur erreur.
    out_dir : dossier de sortie des forums (permet le mode "1 dossier par run").
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_BASE_URL}/topics"

    collected = []

    state_file = Path(__file__).parent / ".scraper_state.json"
    start_page = 1

    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
            if str(state.get("category_id")) == str(category_id):
                start_page = state.get("page", 1)
                print(f"[{label}] Reprise détectée à la page {start_page}")
        except Exception:
            pass

    page = start_page
    print(f"\n[{label}] Collecte sur categoryId={category_id} (cible : {target_count} items)...")

    while len(collected) < target_count:
        # Sauvegarde de l'état (reprise en cas d'interruption)
        try:
            with open(state_file, "w") as f:
                json.dump({"category_id": category_id, "page": page}, f)
        except Exception:
            pass

        params = {"categoryId": category_id, "pageSize": PAGE_SIZE, "page": page}
        data = api_get(url, headers, params)
        results = data.get("result", [])

        if not results:
            print(f"[{label}] Page {page} vide -> fin de la catégorie {category_id}.")
            break

        print(f"[{label}] Page {page} : {len(results)} items reçus.")

        # ── Arrêt anticipé basé sur la date ─────────────────────────────────
        # L'API inSided retourne les topics du plus récent au plus ancien.
        # Si AUCUN item de la page courante n'est dans la période voulue,
        # toutes les pages suivantes seront encore plus anciennes → on arrête.
        has_recent_in_page = any(
            datetime.fromisoformat(item.get("publishedAt", "").replace("Z", "+00:00")) >= DATE_THRESHOLD
            for item in results
            if item.get("publishedAt")
        )
        if not has_recent_in_page:
            print(f"[{label}] Page {page} : aucun item après {DATE_THRESHOLD.date()} -> arrêt anticipé.")
            break

        # Si c'est un forum, scraper les réponses en parallèle avec ThreadPoolExecutor
        if "Forum" in label and results:
            items_to_process = []
            for item in results:
                published_at_raw = item.get("publishedAt")
                if not published_at_raw:
                    continue
                try:
                    published_at = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
                    if published_at < DATE_THRESHOLD:
                        continue
                except ValueError:
                    continue

                seo_url = build_seo_url(item)
                item["_seoUrl"] = seo_url
                items_to_process.append(item)

            # Scraping parallèle de 3 topics simultanés (throttled + jitter pour éviter les blocages).
            # Reprise incrémentale intelligente :
            #   - déjà résolu (bestAnswer true)     -> skip (fichier conservé tel quel)
            #   - non résolu, toujours non résolu   -> skip + rafraîchissement métadonnées
            #   - non résolu, devient résolu (API)  -> RE-SCRAPE (capter le nouveau best answer)
            # force_rescrape=True -> tout re-scraper sans tenir compte de la reprise.
            if items_to_process:
                from concurrent.futures import ThreadPoolExecutor
                forums_out = out_dir or OUTPUT_FORUMS_DIR
                def _fetch_replies(it):
                    cat_dir = forums_out / slugify(it.get("categoryName", "unknown"))
                    public_id = it.get("publicId") or it.get("id") or ""
                    existing_file = cat_dir / f"{public_id}.json"
                    if not force_rescrape and existing_file.exists():
                        try:
                            existing = json.loads(existing_file.read_text(encoding="utf-8"))
                            if existing.get("scraped_replies"):
                                if existing.get("bestAnswer"):
                                    return None  # déjà résolu -> on garde tel quel
                                if not it.get("bestAnswer"):
                                    _refresh_metadata(existing_file, existing, it)
                                    return None  # toujours non résolu -> pas de re-scrape
                                # bestAnswer false (fichier) -> true (API) : devient résolu -> re-scrape
                        except Exception:
                            pass
                    it["scraped_replies"] = scrape_all_replies(it["_seoUrl"])
                    return it

                with ThreadPoolExecutor(max_workers=3) as executor:
                    processed_batch = list(executor.map(_fetch_replies, items_to_process))

                for item in processed_batch:
                    if item is None:
                        continue
                    collected.append(item)
                    if len(collected) >= target_count:
                        break
        else:
            for item in results:
                published_at_raw = item.get("publishedAt")
                if not published_at_raw:
                    continue
                try:
                    published_at = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
                    if published_at < DATE_THRESHOLD:
                        continue
                except ValueError:
                    continue

                seo_url = build_seo_url(item)
                item["_seoUrl"] = seo_url
                collected.append(item)
                if len(collected) >= target_count:
                    break

        page += 1
        time.sleep(REQUEST_DELAY_SECONDS)

        if page > 50:
            print(f"[{label}] Limite de 50 pages atteinte, arrêt.")
            break

    print(f"[{label}] Terminé : {len(collected)}/{target_count} items trouvés.")

    # Nettoyage de l'état si on a terminé la catégorie avec succès
    if state_file.exists():
        try:
            state_file.unlink()
        except Exception:
            pass

    return {"items": collected, "last_page": page - 1}


# --------------------------------------------------------------------------
# Sauvegarde : 1 fichier JSON par item (nom = {publicId}.json, par catégorie)
# --------------------------------------------------------------------------

def save_items(items: list, output_folder: Path, label: str) -> None:
    """Écrit un fichier JSON par item, rangé par catégorie (dossier par categoryName)."""
    output_folder.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in items:
        public_id = item.get("publicId") or item.get("id") or ""
        if public_id:
            file_name = f"{public_id}.json"
        else:
            file_name = "unknown.json"
        cat_folder = slugify(item.get("categoryName", "unknown")) or "unknown"
        cat_dir = output_folder / cat_folder
        cat_dir.mkdir(parents=True, exist_ok=True)
        file_path = cat_dir / file_name
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        written += 1
    print(f"[OK] {label} : {written} fichier(s) écrit(s) dans {output_folder}")


# --------------------------------------------------------------------------
# Extraction principale
# --------------------------------------------------------------------------

def run_extract(active_forum_ids: list = None, active_kb_ids: list = None, force_rescrape: bool = False, run_id: str = None) -> dict:
    """
    Extrait les items de l'API pour les catégories ciblées.

    Paramètres optionnels (transmis par run_pipeline.py depuis run_scan()) :
        active_forum_ids : liste des IDs de catégories forum ayant des items récents.
                           Si None ou vide → utilise la liste complète FORUM_CATEGORIES.
        active_kb_ids    : liste des IDs de catégories KB ayant des items récents.
                           Si None ou vide → utilise la liste complète KB_CATEGORIES.
        force_rescrape   : True → ré-extraction complète (tous les topics sont
                           re-scrapés, la reprise incrémentale est ignorée).
        run_id           : identifiant du run → les fichiers sont écrits dans
                           output/<run_id>/forums et output/<run_id>/knowledge_base
                           (conserve chaque run séparément).

    Ce ciblage évite de paginer des catégories vides (0 items récents détectés au scan),
    ce qui réduit considérablement le temps d'exécution.
    """
    run_dir = OUTPUT_DIR / run_id if run_id else OUTPUT_DIR
    forums_dir = run_dir / "forums"
    kb_dir = run_dir / "knowledge_base"
    print(f"[EXTRACT] Dossier de sortie : {run_dir}")
    if force_rescrape:
        print("[EXTRACT] MODE FULL RE-SCRAPE : tous les topics seront re-scrapés (reprise ignorée).")
    # Sélection des catégories à traiter
    # Si le scan a fourni une liste non vide, on l'utilise ; sinon fallback complet
    forum_cats = active_forum_ids if active_forum_ids else FORUM_CATEGORIES
    kb_cats    = active_kb_ids    if active_kb_ids    else KB_CATEGORIES

    if active_forum_ids is not None:
        print(f"[EXTRACT] Ciblage forum depuis scan : {len(forum_cats)}/{len(FORUM_CATEGORIES)} catégories actives.")
    if active_kb_ids is not None:
        print(f"[EXTRACT] Ciblage KB depuis scan    : {len(kb_cats)}/{len(KB_CATEGORIES)} catégories actives.")

    print("Démarrage du pipeline d'extraction (catégories ciblées)...")
    start_time_dt = datetime.now()
    token = get_access_token()

    total_kb = 0
    total_forums = 0
    all_kb_pages = 0
    all_forum_pages = 0

    # Dictionnaire pour tracer les IDs extraits par catégorie
    extracted_ids: dict = {"knowledge_base": {}, "forums": {}}

    # --- Knowledge Base ---
    print(f"\n=== KNOWLEDGE BASE ({len(kb_cats)} catégories) ===")
    for cat_id in kb_cats:
        result = collect_items(cat_id, token, TARGET_COUNT, f"KB-{cat_id}")
        save_items(result["items"], kb_dir, f"KB-{cat_id}")
        ids = [str(item.get("publicId") or item.get("id", "")) for item in result["items"]]
        extracted_ids["knowledge_base"][f"cat_{cat_id}"] = {"count": len(ids), "ids": ids}
        total_kb += len(result["items"])
        all_kb_pages += result["last_page"]

    # --- Forums ---
    print(f"\n=== FORUMS ({len(forum_cats)} catégories) ===")
    for cat_id in forum_cats:
        result = collect_items(cat_id, token, TARGET_COUNT, f"Forum-{cat_id}", force_rescrape=force_rescrape, out_dir=forums_dir)
        save_items(result["items"], forums_dir, f"Forum-{cat_id}")
        ids = [str(item.get("publicId") or item.get("id", "")) for item in result["items"]]
        extracted_ids["forums"][f"cat_{cat_id}"] = {"count": len(ids), "ids": ids}
        total_forums += len(result["items"])
        all_forum_pages += result["last_page"]

    print(f"\n[OK] Extraction terminée.")
    print(f"     Knowledge Base : {total_kb} items extraits")
    print(f"     Forums         : {total_forums} items extraits")
    print(f"     Résultat dans  : {run_dir}")

    end_time_dt = datetime.now()
    duration = (end_time_dt - start_time_dt).total_seconds()

    # Sauvegarde du fichier d'IDs extraits dans le dossier du run (ou logs/ si run standalone)
    run_dir = run_logger.current_run_dir()
    logs_dir = Path(run_dir) if run_dir else (Path(__file__).parent / "logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_ts = start_time_dt.strftime('%Y%m%d_%H%M%S')
    ids_file = logs_dir / f"extracted_ids.txt"

    lines = [
        f"FICHIER DES IDs EXTRAITS - Run {run_ts}",
        f"Date : {start_time_dt.isoformat()}",
        f"Durée extraction : {duration:.1f} sec",
        f"Total KB : {total_kb} | Total Forums : {total_forums}",
        "=" * 55,
        "",
        "--- KNOWLEDGE BASE ---",
    ]
    for cat_key, data in extracted_ids["knowledge_base"].items():
        lines.append(f"  {cat_key} ({data['count']} items) : {', '.join(data['ids']) if data['ids'] else 'aucun'}")
    lines += ["", "--- FORUMS ---"]
    for cat_key, data in extracted_ids["forums"].items():
        lines.append(f"  {cat_key} ({data['count']} items) : {', '.join(data['ids']) if data['ids'] else 'aucun'}")

    with open(ids_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] IDs extraits sauvegardés dans : {ids_file}")

    # Message d'erreur : auteurs dont le role reste vide (a completer dans author_roles.json)
    if UNRESOLVED:
        msg = "Auteurs sans role (completer manuellement dans author_roles.json) : " + ", ".join(sorted(UNRESOLVED))
        print("[MSG ERREUR] " + msg)
        run_logger.error(msg)
    else:
        print("[OK] Toutes les reponses ont un role (aucun auteur sans role).")

    return {
        "start_time": start_time_dt.isoformat(),
        "end_time": end_time_dt.isoformat(),
        "kb_extracted": total_kb,
        "forum_extracted": total_forums,
        "kb_pages_total": all_kb_pages,
        "forum_pages_total": all_forum_pages,
        "duration_seconds": duration
    }
