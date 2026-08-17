#!/usr/bin/env python3
"""
Module de configuration & clients partagés du pipeline.

Centralise pour main.py, scan_categories.py et prepare_rag.py :
  - la lecture du .env (identifiants, URL, RAG_START_DATE, catégories)
  - les chemins de sortie (output/, rag-ready/, logs/)
  - l'authentification OAuth2 (get_access_token, avec cache .token_cache.json)
  - l'appel API avec retry/backoff (api_get)
  - les helpers communs (slugify, is_recent_enough)

Importé par les 3 étapes, il n'exécute aucune action au chargement
(simple définition de constantes/fonctions).
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

import run_logger

# --------------------------------------------------------------------------
# Base / environnement
# --------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
AUTH_URL = os.getenv("AUTH_URL", "https://api2-eu-west-1.insided.com/oauth2/token")
API_BASE_URL = os.getenv("API_BASE_URL", "https://api2-eu-west-1.insided.com/v2")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://community.st.com")

# "basic" -> client_id/client_secret envoyés via HTTP Basic Auth (le plus courant avec Kong)
# "body"  -> client_id/client_secret envoyés dans le body x-www-form-urlencoded
AUTH_METHOD = os.getenv("AUTH_METHOD", "basic").lower()
OAUTH_SCOPE = os.getenv("OAUTH_SCOPE", "read")

# Date de début de collecte : lit RAG_START_DATE depuis .env (format ISO 8601).
# Seuls les items publiés APRÈS cette date sont conservés dans output/ et rag-ready/.
RAG_START_DATE_STR = os.getenv("RAG_START_DATE", "2026-03-15T00:00:00Z")
try:
    DATE_THRESHOLD = datetime.fromisoformat(RAG_START_DATE_STR.replace("Z", "+00:00"))
except (ValueError, AttributeError):
    DATE_THRESHOLD = datetime(2026, 3, 15, tzinfo=timezone.utc)
    print(
        f"[CONFIG] [WARN] RAG_START_DATE manquant ou invalide dans .env (valeur : '{RAG_START_DATE_STR}').\n"
        f"          Valeur par défaut utilisée : {DATE_THRESHOLD.isoformat()}"
    )

# --------------------------------------------------------------------------
# Catégories (surchargeables via .env : RAG_KB_CATEGORIES / RAG_FORUM_CATEGORIES)
# --------------------------------------------------------------------------

_DEFAULT_KB_CATEGORIES = ["60", "61", "62", "63", "64", "65", "66", "68"]
_DEFAULT_FORUM_CATEGORIES = [
    "25", "26", "28", "29", "30", "31", "32", "33", "34", "35",
    "36", "39", "46", "48", "49", "50", "51", "52", "53", "54",
    "57", "118", "120", "121", "133", "134", "138", "142", "151",
]


def _env_list(key: str, default: list) -> list:
    """Lit une liste CSV dans le .env ; retourne la liste par défaut si vide."""
    raw = os.getenv(key, "").strip()
    if not raw:
        return list(default)
    return [c.strip() for c in raw.split(",") if c.strip()]


KB_CATEGORIES = _env_list("RAG_KB_CATEGORIES", _DEFAULT_KB_CATEGORIES)
FORUM_CATEGORIES = _env_list("RAG_FORUM_CATEGORIES", _DEFAULT_FORUM_CATEGORIES)

# --------------------------------------------------------------------------
# Chemins de sortie
# --------------------------------------------------------------------------

OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_KB_DIR = OUTPUT_DIR / "knowledge_base"
OUTPUT_FORUMS_DIR = OUTPUT_DIR / "forums"
RAG_READY_DIR = BASE_DIR / "rag-ready"
LOGS_DIR = BASE_DIR / "logs"

# --------------------------------------------------------------------------
# Réglages réseau / retry / pagination
# --------------------------------------------------------------------------

PAGE_SIZE = 100
MAX_RETRIES = 5
RETRY_BACKOFF_SECONDS = 2       # backoff exponentiel : 2, 4, 8, 16, 32...
REQUEST_DELAY_SECONDS = 0.3     # pause polie entre 2 requêtes API
SCRAPE_DELAY_SECONDS = 0.5      # base de pause entre 2 requêtes de scraping HTML
TARGET_COUNT = 99999            # extraction complète (aucune limite d'items)

# --------------------------------------------------------------------------
# Helpers communs
# --------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convertit un texte en slug kebab-case (façon community.st.com)."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def is_recent_enough(published_at_raw) -> bool:
    """Vérifie si la date de publication est >= RAG_START_DATE."""
    if not published_at_raw:
        return False
    try:
        pub_date = datetime.fromisoformat(str(published_at_raw).replace("Z", "+00:00"))
        return pub_date >= DATE_THRESHOLD
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------
# Authentification OAuth2 (avec cache .token_cache.json)
# --------------------------------------------------------------------------

def get_access_token(force_refresh: bool = False) -> str:
    """Récupère un token d'accès via OAuth2 Client Credentials (mise en cache)."""
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit(
            "ERREUR : CLIENT_ID / CLIENT_SECRET manquants.\n"
            "Renseigne-les dans le fichier .env (voir .env.example)."
        )

    cache_file = BASE_DIR / ".token_cache.json"

    if not force_refresh and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
            last_login = cache.get("last_login", 0)
            token = cache.get("access_token", "")
            # Cache valide ~3500 secondes (un peu moins d'1h)
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
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"access_token": token, "last_login": time.time()}, f)
        print("[AUTH] Token obtenu et sauvegardé dans le cache.")
    except Exception as e:
        print(f"[AUTH] Token obtenu mais impossible de sauvegarder le cache: {e}")

    return token


# --------------------------------------------------------------------------
# Appel API avec retry / backoff
# --------------------------------------------------------------------------

def api_get(url: str, headers: dict, params: dict = None) -> dict:
    """GET avec retry + backoff exponentiel (429, 5xx, 401) ; lève une exception en échec total."""
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
            run_logger.error(f"[RATE LIMIT] 429 sur {url} (pause {wait}s)")
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"[ERREUR SERVEUR] {resp.status_code}, pause de {wait}s (tentative {attempt}/{MAX_RETRIES})...")
            run_logger.error(f"[ERREUR SERVEUR] HTTP {resp.status_code} sur {url}")
            time.sleep(wait)
            continue

        if resp.status_code == 401:
            print("[API] 401 Unauthorized détecté (token expiré ?). Régénération du token...")
            run_logger.error(f"[API] 401 Unauthorized sur {url} (régénération du token)")
            new_token = get_access_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {new_token}"
            time.sleep(1)
            continue

        # Erreur non récupérable (403, 404...)
        resp.raise_for_status()

    raise Exception(f"Échec après {MAX_RETRIES} tentatives sur {url}")
