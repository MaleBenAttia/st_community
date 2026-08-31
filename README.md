# Pipeline de collecte RAG & Dashboard Analytique — STMicroelectronics Community

Système complet d'extraction et de préparation de données pour un pipeline **RAG (Retrieval-Augmented Generation)** à partir de la communauté STMicroelectronics (Gainsight/inSided).

Le pipeline est **entièrement orchestré par un point d'entrée unique** (`run_pipeline.py`) qui enchaîne : Scan → Extraction → Mise à jour des rôles → Préparation RAG. La configuration partagée (auth, API, dates, catégories, chemins, helpers) est centralisée dans `config.py`.

---

## Architecture du projet

```
.
├── config.py                   ← Configuration & clients partagés (env, auth OAuth2, api_get, slugify, dates, catégories, chemins)
├── run_pipeline.py             ← Orchestrateur principal (SEUL point d'entrée : Scan → Extraction → MàJ rôles → RAG)
├── run_logger.py               ← Logger par run : logs/<ts>_pipeline/ (run.log, ErrorLog.txt, stats.json)
├── scan_categories.py          ← Étape 1 : Scan des volumes par catégorie (ne s'exécute que via run_pipeline)
├── main.py                     ← Étape 2 : Extraction API + scraping HTML des réponses (3 workers, anti-blocage)
├── build_author_roles.py       ← Étape 2bis : régénère author_roles.json depuis output/
├── author_roles.py             ← Module rôles (lecture de la référence statique)
├── author_roles.json           ← Référence statique des rôles d'auteurs (éditable à la main)
├── prepare_rag.py              ← Étape 3 : Filtrage, nettoyage, conversion Markdown & RAG-ready
│
├── Dashboard/                  ← Application Web Dashboard (Flask + Interface UI)
│   ├── app.py                  ← Serveur backend Flask (API, gestion subprocess & SSE logs)
│   ├── dashboard.Html          ← Interface graphique moderne (Glassmorphism, onglets & contrôle)
│   ├── latest_stats.json       ← Copie des dernières statistiques générées pour l'UI
│   └── static/floating/        ← Bundle React (build Vite) : éléments SVG flottants animés
│
├── frontend/                   ← Sources React des éléments flottants (Vite + plugin React)
│   ├── package.json
│   ├── vite.config.js          ← build → Dashboard/static/floating/
│   └── src/
│       ├── floating-elements.jsx ← 3 composants SVG SMIL animés (Stm32Chip, CircuitTrace, EmWave) — palette officielle ST
│       ├── decor.jsx             ← mise en scène décorative (positions flottantes)
│       ├── floating.css          ← animations float / reduced-motion
│       └── main.jsx              ← mount React dans #floating-decor (no-op si absent)
│
├── .env / .env.example         ← Identifiants, URL, RAG_START_DATE, catégories
├── requirements.txt
└── README.md
```

### Dossiers de données générés

```
.
├── output/                  ← Données brutes extraites par main.py
│   ├── knowledge_base/<cat>/ ← 1 fichier JSON par article KB ({publicId}.json)
│   └── forums/<cat>/         ← 1 fichier JSON par topic de forum ({publicId}.json)
│
├── rag-ready/               ← Données filtrées et nettoyées pour le RAG
│   ├── knowledge_base/<cat>/ ← Articles KB (HTML → Markdown, encapsulés dans {"kb": [...]})
│   └── forums/<cat>/         ← Topics résolus avec best answer (HTML → Markdown, {"forum": [...]})
│
└── logs/                    ← Un dossier par run d'exécution
    └── <YYYYMMDD_HHMMSS>_pipeline/  ← run.log, ErrorLog.txt, stats.json, scan_report.txt, extracted_ids.txt
```

---

## Installation

```powershell
# 1. Créer et activer un environnement virtuel
python -m venv venv
.\venv\Scripts\Activate.ps1
venv\Scripts\activate

# 2. Installer les dépendances Python (Flask, scraping, waitress…)
pip install -r requirements.txt

# 3. (Optionnel) Dépendances frontend — uniquement pour REBUILD du décor SVG flottant
cd frontend
npm install
npm run build  
cd ..
```

> Le bundle frontend buildé est **versionné** dans `Dashboard/static/floating/` : en production, aucune étape npm n'est nécessaire — seul `pip install -r requirements.txt` suffit.

---

## Configuration (`.env`)

Créer un fichier `.env` à la racine à partir du modèle `.env.example` :

```env
# Authentification API inSided
CLIENT_ID=votre_client_id
CLIENT_SECRET=votre_client_secret
AUTH_URL=https://api2-eu-west-1.insided.com/oauth2/token
API_BASE_URL=https://api2-eu-west-1.insided.com/v2
SITE_BASE_URL=https://community.st.com
AUTH_METHOD=basic          # 'basic' (HTTP Basic Auth) ou 'body' (x-www-form-urlencoded)
OAUTH_SCOPE=read

# Configuration RAG
RAG_START_DATE=2026-06-30T00:00:00Z   # Date limite (ISO 8601) : seuls les items publiés APRÈS cette date sont conservés

# Catégories (optionnel : par défaut listes complètes intégrées dans config.py)
RAG_KB_CATEGORIES=60,61,62,63,64,65,66,68
RAG_FORUM_CATEGORIES=25,26,28,29,30,31,32,33,34,35,36,39,46,48,49,50,51,52,53,54,57,118,120,121,133,134,138,142,151
```

Toutes ces variables sont lues et interprétées une seule fois par `config.py` (cache de module) et partagées par les 3 étapes.

> **⚠️ Ne jamais commiter le fichier `.env`.** Il contient vos identifiants d'accès.

---

## Utilisation

### Option 1 — Via le Dashboard Web (Recommandé)

Un serveur local Flask permet de visualiser les métriques et de piloter le pipeline directement depuis le navigateur.

```powershell
python Dashboard/app.py
```

Accédez à **[http://127.0.0.1:5000](http://127.0.0.1:5000)** dans votre navigateur.

**Fonctionnalités du Dashboard :**
- **Onglet "Knowledge Base"** : Métriques, articles validés, distribution des vues et catégories KB. Breakdown par catégorie et liste d'articles validés repliables (**Voir plus ▾ / Voir moins ▴**).
- **Onglet "Community Forums"** : Taux de résolution, **Top 10 des posts les plus vus**, posts les plus répondus, statistiques d'interaction, et **2 grands blocs KPI** :
  - **Solved Posts** (résolus) avec sous-répartition colorée *Replied with ST agent* (vert) / *Replied without ST agent* (bleu), en nombre et pourcentage.
  - **Ongoing** (non résolus) avec sous-répartition colorée *With ST agent* (ambre) / *Without ST agent* (rouge).
  - Breakdown par catégorie repliable (**Voir plus ▾ / Voir moins ▴**) et cartes à hauteur égale.
- **Onglet "Pipeline Control"** :
  - Modification dynamique de `RAG_START_DATE`.
  - Case **"Full re-scrape"** : ré-extraction complète (tous les topics re-scrapés, reprise incrémentale ignorée) — à cocher pour un état 100 % frais, plus lent (~20 min).
  - Bouton **"Start Pipeline"** pour lancer le traitement en arrière-plan.
  - Bouton **"Stop Execution"** pour interrompre immédiatement le pipeline.
  - Console de logs en temps réel (Server-Sent Events).
  - Section **"Run History"** : la sélection d'un run (par date/heure) **change toute la plateforme** — tous les onglets (Global, Knowledge Base, Community Forums) + header (dates, Scrap date, **Activity date = filtre `From RAG_START_DATE` du run**, Run) + fichiers réels (`stats.json`, `run.log`, `ErrorLog.txt`, `extracted_ids.txt`) + fin de log. Au chargement, le **dernier run terminé (avec stats)** est affiché. Un rafraîchissement automatique (20 s) met à jour la **liste** des runs et recharge le **run affiché**, sans jamais changer la sélection ; la date choisie reste verrouillée.

---

## Fonctionnalités Clés & Robustesse

### 1. Nommage Déterministe `{publicId}.json`
Les fichiers dans `output/` et `rag-ready/` sont nommés **`{publicId}.json`** (ex. `166940.json` — le `publicId` est la référence publique de la plateforme inSided, à distinguer du champ interne `id`) et rangés dans un sous-dossier par catégorie (`<categoryName>` slugifié par `config.slugify`, identique entre `output/` et `rag-ready/`). Lors des ré-exécutions ou des mises à jour d'un item, **le nouveau contenu écrase automatiquement l'ancien**, évitant tout doublon d'extraction.

### 2. Détection 100 % Fiable de la Meilleure Réponse (Best Answer)
Sur inSided, la réponse validée est dupliquée dans un bloc épinglé en haut de page (Zone A) et dans le fil chronologique (Zone B). Pour éviter les doublons et les fausses attributions, `main.py` et `prepare_rag.py` s'appuient uniquement sur le conteneur principal `.paginated-threaded-replies` et la présence de `[data-qa="pill-best-answer"]`.

### 3. Multithreading, Anti-Blocage & Reprise Incrémentale
- Scraping HTML des topics de forums parallélisé via `ThreadPoolExecutor` (**3 workers**) avec **jitter aléatoire** autour de `SCRAPE_DELAY_SECONDS` (0.5 s) pour éviter les salves synchronisées.
- **Anti-blocage IP** : tout échec HTTP non-200 est compté ; après **5 échecs consécutifs**, une **pause longue (30-60 s)** est appliquée avant de reprendre (mécanisme thread-safe).
- **Backoff exponentiel** (429, 5xx, Timeout) avec prise en compte de l'en-tête `Retry-After` ; un `401` régénère automatiquement le token OAuth2.
- **Reprise incrémentale intelligente** : lors des ré-exécutions, un topic déjà scrapé (fichier `{publicId}.json` présent avec `scraped_replies` non vide) est géré selon son statut :
  - déjà **résolu** (`bestAnswer` true) → **sauté** (rapide, fichier conservé) ;
  - non résolu et toujours non résolu côté API → sauté, mais **métadonnées rafraîchies** (vues, réponses, statut) sans re-scrape ;
  - **non résolu puis devenu résolu** (l'API le confirme) → **re-scrapé** pour capter le nouveau best answer et les réponses ST (un forum peut être résolu aujourd'hui mais pas hier).
  - Option **"Full re-scrape"** (Dashboard) ou `FULL_RESCRAPE=1` (CLI) pour tout re-scraper sans condition.
- Scan préalable des catégories actives (`scan_categories.py`) pour ne paginer que les catégories non vides.
- Pagination avec **arrêt anticipé** : dès qu'une page ne contient plus aucun item après `RAG_START_DATE`, l'extraction s'arrête (l'API renvoie les topics du plus récent au plus ancien).
- Mise en cache automatique du jeton d'accès OAuth2 (`.token_cache.json`) pendant ~58 minutes.

### 4. Prise en compte des Médias et Vidéos
Les réponses ne contenant que des vidéos ou des intégrations externes (balises HTML `<oembed>` et `<iframe>`) sont détectées par `prepare_rag.py` et transformées automatiquement en liens cliquables Markdown avant conversion, évitant ainsi la perte de données et les réponses vides.

### 5. Rôles d'auteurs & réponses d'agents ST
- Les rôles sont extraits du HTML des réponses (`.rank-title`) puis complétés via la référence statique **`author_roles.json`** (source de vérité manuelle, éditable à la main).
- Chaque run régénère `author_roles.json` (`build_author_roles.py`) **sans écraser les modifications manuelles** (merge : un rôle non vide déjà présent est conservé) ; les auteurs non résolus sont listés dans `_roles_non_resolus` et signalés dans le log.
- Chaque topic RAG-ready contient **`st_agent_reply`** (`has_st_reply` + liste des réponses ST) pour identifier les topics "solved" par un agent ST (Technical Moderator / Community Manager / Employee).
- Les KPIs agrégés exposés dans `stats.json` / `latest_stats.json` (`step_3_forums_stats`) :
  - **`st_agent_stats`** : répartition ST sur les topics **résolus** (`forums_with_st_reply`, `forums_without_st_reply`, `st_reply_pct`) ;
  - **`st_agent_stats_ongoing`** : même répartition sur les topics **non résolus** (`ongoing`) — alimente le bloc KPI "Ongoing" du Dashboard.
  - **`super_user_stats`** : breakdown croisé ST × Super User sur les 4 groupes (Solved et Ongoing).

#### ⚠️ Logique de comptage binaire par TOPIC (pas par message)

> **Un topic = une unité.** Que ce soit pour les agents ST ou les Super Users, la statistique mesure la **PRÉSENCE** (oui/non), pas le nombre de messages individuels.

| Situation dans un topic | `ST reply` | `Super User` | Compteur |
|---|---|---|---|
| 1 agent ST + 2 Super Users + 1 community user | > 0 | > 0 | `solved_with_st_su += 1` |
| 1 agent ST + 0 Super User | > 0 | = 0 | `solved_with_st_nosu += 1` |
| 0 agent ST + 3 Super Users | = 0 | > 0 | `solved_without_st_su += 1` |
| 0 agent ST + 0 Super User | = 0 | = 0 | `solved_without_st_nosu += 1` |

Exemple concret : un topic avec 1 réponse d'agent ST + 2 réponses de Super Users → `solved_with_st_su += 1` (et non `+= 2`). C'est bien **le topic** qui est compté dans le KPI, pas le nombre de messages.

### 6. Logs par run
Chaque exécution du pipeline crée `logs/<YYYYMMDD_HHMMSS>_pipeline/` contenant `run.log` (tee console), `ErrorLog.txt` (erreurs), `stats.json` (KPIs), `scan_report.txt` et `extracted_ids.txt`. Le Dashboard affiche par défaut le **dernier run** (le plus récent chronologiquement) à chaque chargement de page.


---

## Structure des Données RAG-Ready (`rag-ready/`)

Les fichiers sont nommés `{publicId}.json` (même nom que la source `output/`) et encapsulés dans un objet racine typé — **contrat de données pour le frontend**.

### Knowledge Base (`rag-ready/knowledge_base/<categorie>/*.json`)
```json
{
    "kb": [
        {
            "id": "165889",
            "publicId": "167588",
            "type": "knowledge_base",
            "title": "How to measure and reduce current consumption...",
            "url": "https://community.st.com/...",
            "category": "STM32 MCUs",
            "tags": ["STM32U3 series"],
            "published_at": "2026-08-10T15:22:32+00:00",
            "views": 61,
            "content_text": "## Introduction...",
            "images": ["https://..."],
            "author": "Deepak_1805"
        }
    ]
}
```

### Community Forums (`rag-ready/forums/<categorie>/*.json`)
```json
{
    "forum": [
        {
            "id": "166528",
            "publicId": "166549",
            "title": "RM0468 - BOR_LVL discrepancy",
            "url": "https://community.st.com/...",
            "category": "STM32 MCUs Products",
            "tags": ["Documentation", "STM32H7 series"],
            "published_at": "2026-06-30T13:13:49+00:00",
            "views": 42,
            "reply_count": 1,
            "best_answer": true,
            "best_answer_content": "Hello @embd...\n\nThe BOR_LEV bit...",
            "best_answer_author": "ST Technical Moderator name",
            "best_answer_author_role": "ST Technical Moderator",
            "content_text": "Hi\n\nWhile reviewing...",
            "images": [],
            "author": "embd",
            "scraped_replies": [
                {"is_best": true, "html": "...", "author": "...", "role": "Super User"}
            ],
            "st_agent_reply": {
                "has_st_reply": true,
                "replies": [{"author": "...", "role": "ST Technical Moderator"}]
            }
        }
    ]
}
```

---

## Catégories Couvertes

- **29 Catégories Forums** (MCUs, MPUs, MEMS, TouchGFX, Motor Control, Security, Edge AI, VS Code tools, etc.)
- **8 Catégories Knowledge Base** (STM32 MCUs, MPUs, Sensors, Analog, Power management, Quality & Reliability, etc.)

La liste exacte est définie par défaut dans `config.py` et surchargeable via les variables `RAG_KB_CATEGORIES` / `RAG_FORUM_CATEGORIES` du `.env`.