#!/usr/bin/env python3
"""
PoC - Collecte de contenu Gainsight/inSided (communauté STMicroelectronics)

Objectif du PoC :
  - Récupérer 10 items de Knowledge Base + 10 items de Product Forums
  - publiés après le 31 mai 2026 (champ `publishedAt`)
  - Générer l'URL SEO-friendly de chaque item
  - Sauvegarder le résultat dans un fichier JSON (output/poc_result.json)

Usage :
  1. Copier .env.example en .env et remplir CLIENT_ID / CLIENT_SECRET
  2. pip install -r requirements.txt
  3. python main.py
"""
#!/usr/bin/env python3
"""
PoC - Collecte de contenu Gainsight/inSided (communauté STMicroelectronics)

Objectif du PoC :
  - Récupérer 10 items de Knowledge Base + 10 items de Product Forums
  - publiés après le 31 mai 2026 (champ `publishedAt`)
  - Générer l'URL SEO-friendly de chaque item
  - Sauvegarder le résultat dans un fichier JSON (output/poc_result.json)

Usage :
  1. Copier .env.example en .env et remplir CLIENT_ID / CLIENT_SECRET
  2. pip install -r requirements.txt
  3. python main.py
"""

import os
import re
import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

load_dotenv(override=True)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
AUTH_URL = os.getenv("AUTH_URL", "https://api2-eu-west-1.insided.com/oauth2/token")
API_BASE_URL = os.getenv("API_BASE_URL", "https://api2-eu-west-1.insided.com/v2")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://community.st.com")

# "basic" -> client_id/client_secret envoyés via HTTP Basic Auth (le plus courant avec Kong)
# "body"  -> client_id/client_secret envoyés dans le body x-www-form-urlencoded
AUTH_METHOD = os.getenv("AUTH_METHOD", "basic").lower()

OAUTH_SCOPE = os.getenv("OAUTH_SCOPE", "read")

PAGE_SIZE = 100
MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 2  # backoff exponentiel : 2, 4, 8, 16, 32...
REQUEST_DELAY_SECONDS = 0.3  # pause polie entre 2 requêtes (rate limit inconnu -> prudence)

# Date de début de collecte : lit RAG_START_DATE depuis .env
# Format attendu : ISO 8601 (ex. 2026-08-08T00:00:00Z)
# Seuls les items publiés APRÈS cette date sont extraits dans output/.
_raw_start_date = os.getenv("RAG_START_DATE", "")
try:
    DATE_THRESHOLD = datetime.fromisoformat(_raw_start_date.replace("Z", "+00:00"))
    print(f"[CONFIG] DATE_THRESHOLD = {DATE_THRESHOLD.isoformat()} (lu depuis RAG_START_DATE dans .env)")
except (ValueError, AttributeError):
    DATE_THRESHOLD = datetime(2026, 5, 31, tzinfo=timezone.utc)
    print(
        f"[CONFIG] [WARN] RAG_START_DATE manquant ou invalide dans .env (valeur : '{_raw_start_date}').\n"
        f"          Valeur par défaut utilisée : {DATE_THRESHOLD.isoformat()}"
    )

TARGET_COUNT = 99999  # Extraction complète : toutes les catégories sans limite d'items

# Toutes les catégories à extraire
KB_CATEGORIES = ["60", "61", "62", "63", "64", "65", "66", "68"]
FORUM_CATEGORIES = [
    "25", "26", "28", "29", "30", "31", "32", "33", "34", "35",
    "36", "39", "46", "48", "49", "50", "51", "52", "53", "54",
    "57", "118", "120", "121", "133", "134", "138", "142", "151"
]

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_KB_DIR = OUTPUT_DIR / "knowledge_base"
OUTPUT_FORUMS_DIR = OUTPUT_DIR / "forums"


# --------------------------------------------------------------------------
# Authentification
# --------------------------------------------------------------------------

def get_access_token(force_refresh: bool = False) -> str:
    """Récupère un token d'accès via OAuth2 (mise en cache)."""
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit(
            "ERREUR : CLIENT_ID / CLIENT_SECRET manquants.\n"
            "Renseigne-les dans le fichier .env (voir .env.example)."
        )

    cache_file = Path(__file__).parent / ".token_cache.json"

    if not force_refresh and cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                cache = json.load(f)
            last_login = cache.get("last_login", 0)
            token = cache.get("access_token", "")
            # Cache valide 3500 secondes (un peu moins d'1h)
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
        sys.exit(f"ERREUR : AUTH_METHOD invalide '{AUTH_METHOD}' (attendu: 'basic' ou 'body').")

    print(f"[AUTH] Demande de token à {AUTH_URL} (méthode: {AUTH_METHOD})...")
    resp = requests.post(AUTH_URL, data=data, auth=auth, timeout=30)

    if resp.status_code != 200:
        sys.exit(
            f"ERREUR AUTH ({resp.status_code}) : {resp.text}\n"
            "-> Vérifie AUTH_URL, AUTH_METHOD, CLIENT_ID, CLIENT_SECRET dans .env."
        )

    token = resp.json().get("access_token")
    if not token:
        sys.exit(f"ERREUR : pas de 'access_token' dans la réponse : {resp.text}")

    try:
        with open(cache_file, "w") as f:
            json.dump({"access_token": token, "last_login": time.time()}, f)
        print("[AUTH] Token obtenu et sauvegardé dans le cache.")
    except Exception as e:
        print(f"[AUTH] Token obtenu mais impossible de sauvegarder le cache: {e}")

    return token


# --------------------------------------------------------------------------
# Appels API avec retry / backoff
# --------------------------------------------------------------------------

def api_get(url: str, headers: dict, params: dict) -> dict:
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
            print(f"[RATE LIMIT] 429 reçu, pause de {wait}s (tentative {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"[ERREUR SERVEUR] {resp.status_code}, pause de {wait}s (tentative {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)
            continue

        if resp.status_code == 401:
            print("[API] 401 Unauthorized détecté (token expiré ?). Régénération du token...")
            new_token = get_access_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {new_token}"
            time.sleep(1)
            continue

        # Erreur non récupérable (403, 404...)
        resp.raise_for_status()

    sys.exit(f"ERREUR : échec après {MAX_RETRIES} tentatives sur {url}")


# --------------------------------------------------------------------------
# Slugification (aucun champ 'slug' fourni par l'API -> génération maison)
# --------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convertit un texte en slug kebab-case simple, façon community.st.com."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def build_seo_url(item: dict) -> str:
    """Reconstruit l'URL SEO-friendly : {base}/{category-slug}-{categoryId}/{title-slug}-{publicId}"""
    category_slug = slugify(item.get("categoryName", ""))
    title_slug = slugify(item.get("title", ""))
    category_id = item.get("categoryId")
    public_id = item.get("publicId")
    return f"{SITE_BASE_URL}/{category_slug}-{category_id}/{title_slug}-{public_id}"


# Session réutilisable pour accélérer les requêtes HTTP publiques (scraping).
# Avantages :
#   - HTTP Keep-Alive : la connexion TCP reste ouverte entre les requêtes
#     → évite le coût de la poignée de main SSL à chaque appel (~50-200 ms gagné par requête)
#   - Partage du User-Agent entre tous les appels sans répétition
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})

def scrape_all_replies(url: str) -> list:
    """
    Scrape la page publique d'un topic et extrait toutes ses réponses.

    Retourne une liste de dicts :
        [
            {"is_best": bool, "html": str},
            ...
        ]

    ---
    STRATÉGIE DE DÉTECTION DE LA MEILLEURE RÉPONSE (100 % fiable)
    ---
    La plateforme inSided (Gainsight Community) utilise deux zones distinctes
    pour afficher les réponses d'un topic résolu :

      Zone A — Bloc épinglé en haut de page
          Lorsqu'un topic est marqué "Solved", la meilleure réponse est copiée
          et affichée en évidence AVANT la liste des réponses. Ce bloc possède
          lui aussi l'élément <span data-qa="pill-best-answer">, ce qui provoque
          un faux positif si on scanne tout le document sans restriction.

      Zone B — Fil chronologique (.paginated-threaded-replies)
          C'est ici que se trouvent les VRAIES réponses individuelles, chacune
          dans un <div class="threaded-reply-item">. Le badge
          <span data-qa="pill-best-answer"> n'apparaît qu'UNE SEULE FOIS dans
          cette zone, sur la réponse réellement acceptée par l'auteur.

    Solution : on scope TOUJOURS dans `.paginated-threaded-replies` avant de
    chercher `.threaded-reply-item`. Cela exclut définitivement le bloc épinglé
    et garantit qu'un seul post reçoit is_best=True.

    Vérifié empiriquement sur plusieurs topics ST Community :
        - stm32u375-adf1-stereo-... : best answer = reply 3 (JonathanC) ✅
        - mcu-suggestion            : best answer = reply 4 (Nico3)     ✅
    """
    replies = []
    try:
        resp = session.get(url, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')

            # ── ÉTAPE 1 : Trouver le conteneur du fil de discussion ──────────
            # On cherche en priorité '.paginated-threaded-replies' qui contient
            # uniquement les réponses chronologiques (Zone B), excluant ainsi
            # le bloc épinglé (Zone A) qui provoquerait un faux is_best.
            # Les fallbacks couvrent d'éventuelles variations de classe CSS
            # en cas de mise à jour de la plateforme inSided.
            thread_container = (
                soup.find(class_='paginated-threaded-replies') or  # inSided standard
                soup.find(class_='thread__list') or                # variante possible
                soup.find(class_='replies-list') or                # autre variante
                soup                                               # fallback total
            )

            # ── ÉTAPE 2 : Récupérer les réponses individuelles ───────────────
            # Chaque réponse est encapsulée dans un <div class="threaded-reply-item">
            # avec l'attribut data-qa="threaded-reply-item".
            post_divs = thread_container.find_all(class_="threaded-reply-item")

            if not post_divs:
                # Fallback : si la structure DOM change, chercher des conteneurs
                # génériques de type "post" en évitant les conteneurs trop larges
                # (listes, wrappers) pour ne capturer que les posts unitaires.
                post_divs = thread_container.find_all(
                    lambda tag: tag.name in ['div', 'article', 'li']
                    and tag.get('class')
                    and any('post' in c.lower() for c in tag.get('class'))
                    and not any('list' in c.lower() or 'container' in c.lower() for c in tag.get('class'))
                )

            # ── ÉTAPE 3 : Analyser chaque réponse ───────────────────────────
            for pd in post_divs:
                is_best = False

                # Le badge officiel inSided pour la meilleure réponse.
                # Attribut HTML : <span data-qa="pill-best-answer">BEST ANSWER</span>
                # Scoper dans thread_container (étape 1) garantit que ce badge
                # n'est trouvé qu'une seule fois, sur le bon post.
                if pd.find(attrs={"data-qa": "pill-best-answer"}):
                    is_best = True

                # Extraire le contenu HTML brut de la réponse
                content_div = pd.find(class_='qa-qa-post-content') or pd.find(class_='post__content')
                if content_div:
                    html = str(content_div)

                    # Déduplication : si le même HTML apparaît deux fois
                    # (cas très rare de doublon DOM), on fusionne en conservant
                    # is_best=True si l'un des doublons l'est.
                    existing = next((r for r in replies if r['html'] == html), None)
                    if existing:
                        if is_best:
                            existing['is_best'] = True
                    else:
                        replies.append({
                            "is_best": is_best,
                            "html": html,
                        })

    except Exception as e:
        print(f"  [Scrape Error] {url} -> {e}")

    return replies


# --------------------------------------------------------------------------
# Collecte paginée + filtre de date, jusqu'à obtenir N items valides
# --------------------------------------------------------------------------

def collect_items(category_id: str, token: str, target_count: int, label: str) -> dict:
    """
    Parcourt les pages de /v2/topics pour une catégorie donnée, avec reprise sur erreur.
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
        # Sauvegarde de l'état
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

        # Si c'est un forum, scraper les réponses en parallèle avec ThreadPoolExecutor pour aller 5x à 10x plus vite
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

            # Scraping parallèle de 10 topics simultanés
            if items_to_process:
                from concurrent.futures import ThreadPoolExecutor
                def _fetch_replies(it):
                    it["scraped_replies"] = scrape_all_replies(it["_seoUrl"])
                    return it

                with ThreadPoolExecutor(max_workers=10) as executor:
                    processed_batch = list(executor.map(_fetch_replies, items_to_process))

                for item in processed_batch:
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
# Sauvegarde : 1 fichier JSON par item (nom = slug du titre, contenu = titre)
# --------------------------------------------------------------------------

def save_items(items: list, output_folder: Path, label: str) -> None:
    """Écrit un fichier JSON par item (nom déterministe avec ID pour éviter les doublons)."""
    output_folder.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in items:
        base_name = slugify(item.get("title", "untitled"))
        public_id = item.get("publicId") or item.get("id") or ""
        if public_id:
            file_name = f"{base_name}-{public_id}.json"
        else:
            file_name = f"{base_name}.json"
        file_path = output_folder / file_name
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        written += 1
    print(f"[OK] {label} : {written} fichier(s) écrit(s) dans {output_folder}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run_extract(active_forum_ids: list = None, active_kb_ids: list = None) -> dict:
    """
    Extrait les items de l'API pour les catégories ciblées.

    Paramètres optionnels (transmis par run_pipeline.py depuis run_scan()) :
        active_forum_ids : liste des IDs de catégories forum ayant des items récents.
                           Si None ou vide → utilise la liste complète FORUM_CATEGORIES.
        active_kb_ids    : liste des IDs de catégories KB ayant des items récents.
                           Si None ou vide → utilise la liste complète KB_CATEGORIES.

    Ce ciblage évite de paginer des catégories vides (0 items récents détectés au scan),
    ce qui réduit considérablement le temps d'exécution.
    """
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
        save_items(result["items"], OUTPUT_KB_DIR, f"KB-{cat_id}")
        ids = [str(item.get("publicId") or item.get("id", "")) for item in result["items"]]
        extracted_ids["knowledge_base"][f"cat_{cat_id}"] = {"count": len(ids), "ids": ids}
        total_kb += len(result["items"])
        all_kb_pages += result["last_page"]

    # --- Forums ---
    print(f"\n=== FORUMS ({len(forum_cats)} catégories) ===")
    for cat_id in forum_cats:
        result = collect_items(cat_id, token, TARGET_COUNT, f"Forum-{cat_id}")
        save_items(result["items"], OUTPUT_FORUMS_DIR, f"Forum-{cat_id}")
        ids = [str(item.get("publicId") or item.get("id", "")) for item in result["items"]]
        extracted_ids["forums"][f"cat_{cat_id}"] = {"count": len(ids), "ids": ids}
        total_forums += len(result["items"])
        all_forum_pages += result["last_page"]

    print(f"\n[OK] Extraction terminée.")
    print(f"     Knowledge Base : {total_kb} items extraits")
    print(f"     Forums         : {total_forums} items extraits")
    print(f"     Résultat dans  : {OUTPUT_DIR}")

    end_time_dt = datetime.now()
    duration = (end_time_dt - start_time_dt).total_seconds()

    # Sauvegarde du fichier d'IDs extraits dans logs/
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_ts = start_time_dt.strftime('%Y%m%d_%H%M%S')
    ids_file = logs_dir / f"extracted_ids_{run_ts}.txt"

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

    return {
        "kb_extracted": total_kb,
        "forum_extracted": total_forums,
        "kb_pages_total": all_kb_pages,
        "forum_pages_total": all_forum_pages,
        "duration_seconds": duration
    }


def main():
    run_extract()

if __name__ == "__main__":
    main()