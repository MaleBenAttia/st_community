# Pipeline de collecte RAG & Dashboard Analytique — STMicroelectronics Community

Système complet d'extraction, de préparation de données pour un pipeline **RAG (Retrieval-Augmented Generation)**, et d'un **Dashboard Web interactif** à partir de la communauté STMicroelectronics (Gainsight/inSided).

Le pipeline est divisé en 3 étapes autonomes, orchestrées soit par la ligne de commande, soit directement depuis l'interface Web.

---

## Architecture du projet

```
.
├── Dashboard/                  ← Application Web Dashboard (Flask + Interface UI)
│   ├── app.py                  ← Serveur backend Flask (API, gestion subprocess & SSE logs)
│   ├── dashboard.Html          ← Interface graphique moderne (Glassmorphism, onglets & contrôle)
│   └── latest_stats.json       ← Copie des dernières statistiques générées pour l'UI
│
├── run_pipeline.py              ← Orchestrateur principal (Scan → Extraction → RAG)
├── scan_categories.py       ← Étape 1 : Scan des volumes par catégorie
├── main.py                  ← Étape 2 : Extraction brute de l'API (avec scraping multithread)
└── prepare_rag.py           ← Étape 3 : Filtrage, nettoyage, conversion Markdown & RAG-ready
```

### Dossiers de données générés

```
.
├── output/                  ← Données brutes extraites par main.py
│   ├── knowledge_base/      ← Fichiers JSON par article KB
│   └── forums/              ← Fichiers JSON par topic de forum
│
├── rag-ready/               ← Données filtrées et nettoyées pour le RAG
│   ├── knowledge_base/      ← Articles KB (HTML → Markdown, encapsulés dans {"kb": [...]})
│   └── forums/              ← Topics résolus avec best answer (HTML → Markdown, encapsulés dans {"forum": [...]})
│
├── logs/                    ← Rapports d'exécution et KPIs horodatés (pipeline_stats_*.json)
└── scan_report.txt          ← Rapport du dernier scan des catégories
```

---

## Installation

```powershell
# 1. Créer et activer un environnement virtuel
python -m venv venv
venv\Scripts\activate

# 2. Installer les dépendances (y compris Flask)
pip install -r requirements.txt
```

---

## Configuration (`.env`)

Créer un fichier `.env` à la racine à partir du modèle `.env.example` :

```env
# Authentification API inSided
CLIENT_ID=votre_client_id
CLIENT_SECRET=votre_client_secret
AUTH_URL=https://api2-eu-west-1.insided.com/oauth2/token
API_BASE_URL=https://api2-eu-west-1.insided.com/v2
AUTH_METHOD=basic          # 'basic' (HTTP Basic Auth) ou 'body' (x-www-form-urlencoded)
OAUTH_SCOPE=read

# Configuration RAG
RAG_START_DATE=2026-06-30T00:00:00Z   # Date limite (ISO 8601)
```

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
- **Onglet "Knowledge Base"** : Métriques, articles validés, distribution des vues et catégories KB.
- **Onglet "Community Forums"** : Taux de résolution, posts les plus vus/répondus, statistiques d'interaction.
- **Onglet "Pipeline Control"** :
  - Modification dynamique de `RAG_START_DATE`.
  - Bouton **"Start Pipeline"** pour lancer le traitement en arrière-plan.
  - Bouton **"Stop Execution"** pour interrompre immédiatement le pipeline.
  - Console de logs en temps réel (Server-Sent Events).

---

### Option 2 — En Ligne de Commande (CLI)

#### Lancement du Pipeline Complet
```powershell
python run_pipeline.py
```

#### Lancement étape par étape

| Script | Commande | Description |
|---|---|---|
| `scan_categories.py` | `python scan_categories.py` | Scanne et identifie les catégories avec items récents |
| `main.py` | `python main.py` | Extrait les articles/posts bruts dans `output/` |
| `prepare_rag.py` | `python prepare_rag.py` | Filtre (Best Answer, date), nettoie le HTML et génère `rag-ready/` |

---

## Fonctionnalités Clés & Robustesse

### 1. Nommage Déterministe & Gestion des Doublons
Les fichiers dans `output/` et `rag-ready/` sont nommés de manière strictement déterministe sous la forme `{slug}-{publicId}.json`. Lors des ré-exécutions ou des mises à jour d'un article, **le nouveau contenu écrase automatiquement l'ancien**, évitant tout doublon d'extraction.

### 2. Détection 100 % Fiable de la Meilleure Réponse (Best Answer)
Sur inSided, la réponse validée est dupliquée dans un bloc épinglé en haut de page (Zone A) et dans le fil chronologique (Zone B). Pour éviter les doublons et les fausse attributions, `main.py` et `prepare_rag.py` s'appuient uniquement sur le conteneur principal `.paginated-threaded-replies` et la présence de `[data-qa="pill-best-answer"]`.

### 3. Multithreading & Performance
- Scraping HTML des sujets de forums parallélisé via `ThreadPoolExecutor` (10 workers).
- Scan préalable des catégories actives (`scan_categories.py`) pour éviter de paginer inutilement les catégories vides.
- Mise en cache automatique du jeton d'accès OAuth2 (`.token_cache.json`) pendant 58 minutes.
- Support du rechargement d'environnement `override=True` pour prendre en compte les changements de date à la volée.

---

## Structure des Données RAG-Ready (`rag-ready/`)

### Knowledge Base (`rag-ready/knowledge_base/*.json`)
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

### Community Forums (`rag-ready/forums/*.json`)
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
            "content_text": "Hi\n\nWhile reviewing...",
            "images": [],
            "author": "embd"
        }
    ]
}
```

---

## Catégories Couvertes

- **29 Catégories Forums** (MCUs, MPUs, MEMS, TouchGFX, Motor Control, Security, Edge AI, VS Code tools, etc.)
- **8 Catégories Knowledge Base** (STM32 MCUs, MPUs, Sensors, Analog, Power management, Quality & Reliability, etc.)
