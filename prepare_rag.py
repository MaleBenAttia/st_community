#!/usr/bin/env python3
"""
Préparation RAG - STMicroelectronics

Lit les fichiers JSON bruts générés par main.py dans `output/`, applique les filtres
(best answer pour les forums, date >= RAG_START_DATE), nettoie le HTML en Markdown,
et sauvegarde le résultat propre dans `rag-ready/` (nom de fichier = {publicId}.json,
récupéré du nom du fichier source, rangé par catégorie slugifiée identique à `output/`).
Génère également un rapport d'exécution (JSON).

Point d'entrée : run_pipeline.py (scan → extraction → rôles → RAG).
"""

import sys
import json
from pathlib import Path
from datetime import datetime

from bs4 import BeautifulSoup
import markdownify

from config import (
    OUTPUT_DIR,
    RAG_READY_DIR,
    RAG_START_DATE_STR,
    is_recent_enough,
    slugify,
)

# ─── Rôles d'auteurs reconnus ────────────────────────────────────────────────
# Agents officiels STMicroelectronics (comptes ST vérifiés sur la communauté).
# Un topic est comptabilisé « ST reply > 0 » dès qu'AU MOINS UNE réponse
# provient d'un auteur ayant l'un de ces rôles — peu importe combien d'agents
# ST ont répondu (1 ou 10 = même compteur +1).
ST_AGENT_ROLES = {"ST Technical Moderator", "ST Community Manager", "ST Employee"}

# Membres de la communauté bénéficiant du badge « Super User » (rang expert).
# Même logique binaire : un topic est comptabilisé « Super User > 0 » dès
# qu'AU MOINS UN Super User y a participé — que ce soit 1 ou plusieurs réponses
# du même Super User ou de Super Users différents : le topic compte pour +1.
# Cela reflète la PRÉSENCE d'un Super User, pas le nombre total de ses messages.
SUPER_USER_ROLES = {"Super User"}


# --------------------------------------------------------------------------
# Fonctions de Traitement HTML
# --------------------------------------------------------------------------

def clean_html_to_markdown(html_content: str) -> str:
    """Convertit du HTML en Markdown propre pour le RAG (un paragraphe par bloc)."""
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, 'html.parser')

    # Remplacer les balises <oembed> par des liens simples
    for oembed in soup.find_all('oembed'):
        url = oembed.get('url')
        if url:
            new_tag = soup.new_tag('a', href=url)
            new_tag.string = url
            oembed.replace_with(new_tag)

    # Remplacer les balises <iframe> par des liens simples
    for iframe in soup.find_all('iframe'):
        src = iframe.get('src')
        if src:
            new_tag = soup.new_tag('a', href=src)
            new_tag.string = src
            iframe.replace_with(new_tag)

    html_processed = str(soup)
    md_text = markdownify.markdownify(html_processed, heading_style="ATX")

    # Conserve les paragraphes originaux séparés par des sauts de ligne clairs
    lines = [line.strip() for line in md_text.splitlines() if line.strip()]
    final_text = "\n\n".join(lines)

    # Fallback si markdownify donne un texte vide (ex: HTML avec que des balises non supportées)
    if not final_text.strip():
        final_text = soup.get_text(separator="\n").strip()

    return final_text


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


def _category_dir(output_dir: Path, category_name: str) -> Path:
    """Dossier de catégorie identique à celui utilisé par main.py (config.slugify)."""
    cat_slug = slugify(category_name) or "unknown"
    cat_dir = output_dir / cat_slug
    cat_dir.mkdir(parents=True, exist_ok=True)
    return cat_dir


# --------------------------------------------------------------------------
# Traitement par Type
# --------------------------------------------------------------------------

def process_forums(run_id: str = None) -> dict:
    input_dir = OUTPUT_DIR / run_id / "forums" if run_id else OUTPUT_DIR / "forums"
    output_dir = RAG_READY_DIR / run_id / "forums" if run_id else RAG_READY_DIR / "forums"
    output_dir.mkdir(parents=True, exist_ok=True)

    ok_urls = []
    filtered_urls = []
    processed_count = 0
    rag_items = []  # liste consolidée des topics RAG-ready (1 objet = 1 topic)

    # ── Compteurs de replies et vues ─────────────────────────────────────────
    total_replies = 0
    reply_counts = []          # liste de (reply_count, title, url) pour min/max/top3
    total_views = 0
    total_images = 0
    filtered_no_best_answer = 0  # rejetés : pas de bestAnswer (= Ongoing)
    filtered_too_old = 0         # rejetés : antérieurs à RAG_START_DATE
    filtered_other = 0           # rejetés : autres raisons (pas d'ID, etc.)

    # ── Compteurs ST (présence d'au moins 1 agent ST dans le topic) ──────────
    # IMPORTANT : Ces compteurs mesurent des TOPICS, PAS des messages individuels.
    # Un topic avec 3 réponses d'agents ST différents ne compte que pour +1.
    # La logique est binaire : a-t-il au moins 1 réponse d'un agent ST ? Oui/Non.
    st_with = 0      # topics résolus (Solved) : au moins 1 réponse d'agent ST
    st_without = 0   # topics résolus (Solved) : aucune réponse d'agent ST
    ongoing_with = 0      # topics Ongoing (non résolus) : au moins 1 réponse ST
    ongoing_without = 0   # topics Ongoing (non résolus) : aucune réponse ST

    # ── Breakdown Super User x ST (tous les 4 groupes) ───────────────────────
    # Croisement de 2 critères binaires (présence ST ? présence Super User ?)
    # → 4 groupes possibles par statut (Solved / Ongoing) :
    #   - solved_with_st_su    : Solved + ST présent   + Super User présent
    #   - solved_with_st_nosu  : Solved + ST présent   + Super User absent
    #   - solved_without_st_su : Solved + ST absent    + Super User présent
    #   - solved_without_st_nosu: Solved + ST absent   + Super User absent
    # Idem pour les Ongoing.
    # Exemple : 1 topic avec 1 agent ST + 2 Super Users → solved_with_st_su += 1
    # (pas solved_with_st_su += 2 : c'est bien LE TOPIC qui est compté, pas les messages)
    solved_with_st_su = 0
    solved_with_st_nosu = 0
    solved_without_st_su = 0
    solved_without_st_nosu = 0
    ongoing_with_st_su = 0
    ongoing_with_st_nosu = 0
    ongoing_without_st_su = 0
    ongoing_without_st_nosu = 0
    # Période d'activité des posts analysés
    activity_min = None
    activity_max = None

    if not input_dir.exists():
        print("Aucun dossier de forums trouvé.")
        return {"count": 0, "ok_urls": [], "filtered_urls": [], "stats": {}}

    print("\n--- Traitement des Forums ---")
    for file_path in input_dir.rglob("*.json"):
        with open(file_path, "r", encoding="utf-8") as f:
            topic = json.load(f)

        topic_url = topic.get("_seoUrl", file_path.name)

        # Filtre de date : tout post antérieur à RAG_START_DATE est écarté
        # (fichier supprimé de output/ et totalement exclu des compteurs).
        if not is_recent_enough(topic.get("publishedAt")):
            filtered_too_old += 1
            try:
                file_path.unlink()
            except Exception:
                pass
            continue

        # Période d'activité (min/max publishedAt sur les posts analysés)
        pub_dt = None
        if topic.get("publishedAt"):
            try:
                pub_dt = datetime.fromisoformat(str(topic["publishedAt"]).replace("Z", "+00:00"))
            except ValueError:
                pass
        if pub_dt:
            if activity_min is None or pub_dt < activity_min:
                activity_min = pub_dt
            if activity_max is None or pub_dt > activity_max:
                activity_max = pub_dt

        # ── Détection binaire des rôles (une seule passe par topic) ─────────
        # On vérifie la PRÉSENCE (any()) — pas le décompte — de chaque type
        # d'auteur parmi toutes les réponses du topic.
        # Peu importe que 1 ou 5 agents ST aient répondu : has_st_reply = True.
        # Peu importe que 1 ou 3 Super Users aient posté  : has_su_reply = True.
        scraped_replies = topic.get("scraped_replies", [])
        has_st_reply = any((r.get("role") or "") in ST_AGENT_ROLES for r in scraped_replies)
        has_su_reply = any((r.get("role") or "") in SUPER_USER_ROLES for r in scraped_replies)

        cat_dir = _category_dir(output_dir, topic.get("categoryName", ""))
        # Toujours traiter le fichier pour appliquer les corrections de scraping récents

        # 1. Filtre: bestAnswer doit être true
        if not topic.get("bestAnswer", False):
            filtered_urls.append({"url": topic_url, "reason": "no_best_answer"})
            filtered_no_best_answer += 1
            if has_st_reply:
                ongoing_with += 1
                if has_su_reply:
                    ongoing_with_st_su += 1
                else:
                    ongoing_with_st_nosu += 1
            else:
                ongoing_without += 1
                if has_su_reply:
                    ongoing_without_st_su += 1
                else:
                    ongoing_without_st_nosu += 1
            continue

        topic_id = topic.get("id")
        if not topic_id:
            filtered_urls.append({"url": topic_url, "reason": "no_id"})
            filtered_other += 1
            if has_st_reply:
                ongoing_with += 1
                if has_su_reply:
                    ongoing_with_st_su += 1
                else:
                    ongoing_with_st_nosu += 1
            else:
                ongoing_without += 1
                if has_su_reply:
                    ongoing_without_st_su += 1
                else:
                    ongoing_without_st_nosu += 1
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
        best_answer_meta = []

        if scraped_replies:
            for reply in scraped_replies:
                html_reply = reply.get("html", "")
                is_best = reply.get("is_best", False)
                md_reply = clean_html_to_markdown(html_reply)

                if md_reply:
                    if is_best and md_reply not in best_answers:
                        best_answers.append(md_reply)
                        best_answer_meta.append({
                            "author": reply.get("author", ""),
                            "role": reply.get("role", ""),
                        })
                    reply_images = extract_images_from_html(html_reply)
                    all_images.update(reply_images)

        scraped_replies_out = [
            {
                "is_best": reply.get("is_best", False),
                "html": reply.get("html", ""),
                "author": reply.get("author", ""),
                "role": reply.get("role", ""),
            }
            for reply in scraped_replies
        ]

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
            rag_item["best_answer_author"] = best_answer_meta[0]["author"]
            rag_item["best_answer_author_role"] = best_answer_meta[0]["role"]
        elif len(best_answers) > 1:
            for idx, ans in enumerate(best_answers, start=1):
                rag_item[f"best_answer_content{idx}"] = ans
                rag_item[f"best_answer_author{idx}"] = best_answer_meta[idx - 1]["author"]
                rag_item[f"best_answer_author_role{idx}"] = best_answer_meta[idx - 1]["role"]
        else:
            # Fallback : si best_answers est vide mais qu'il y a au moins une réponse extraite
            all_scraped_md = [clean_html_to_markdown(r.get("html", "")) for r in scraped_replies if clean_html_to_markdown(r.get("html", ""))]
            if all_scraped_md:
                rag_item["best_answer_content"] = all_scraped_md[0]
                first_reply = scraped_replies[0]
                rag_item["best_answer_author"] = first_reply.get("author", "")
                rag_item["best_answer_author_role"] = first_reply.get("role", "")
            else:
                rag_item["best_answer_content"] = ""
                rag_item["best_answer_author"] = ""
                rag_item["best_answer_author_role"] = ""

        rag_item["content_text"] = question_md
        rag_item["images"] = list(all_images)
        rag_item["author"] = topic.get("author", {}).get("username", "")
        rag_item["scraped_replies"] = scraped_replies_out

        # ── Embedding des réponses ST dans le topic RAG-ready ───────────────
        # Collecte de toutes les réponses individuelles d'agents ST (pour le RAG),
        # mais le compteur KPI lui ne s'incrémente que de +1 par topic (binaire).
        st_replies = [
            {"author": reply.get("author", ""), "role": reply.get("role", "")}
            for reply in scraped_replies
            if reply.get("role") in ST_AGENT_ROLES
        ]
        rag_item["st_agent_reply"] = {
            "has_st_reply": bool(st_replies),   # True si au moins 1 agent ST a répondu
            "replies": st_replies,               # liste complète des réponses ST individuelles
        }

        # ── Affectation dans l'un des 4 groupes Solved x ST x Super User ────
        # Chaque topic (Solved) est classé dans exactement UN des 4 groupes :
        #   ST présent + SU présent | ST présent + SU absent
        #   ST absent  + SU présent | ST absent  + SU absent
        # → compteur += 1 (pas += nombre de messages ST ou SU)
        if has_st_reply:
            st_with += 1
            if has_su_reply:
                solved_with_st_su += 1    # Solved, ST > 0, Super User > 0
            else:
                solved_with_st_nosu += 1  # Solved, ST > 0, Super User = 0
        else:
            st_without += 1
            if has_su_reply:
                solved_without_st_su += 1    # Solved, ST = 0, Super User > 0
            else:
                solved_without_st_nosu += 1  # Solved, ST = 0, Super User = 0

        # Silhouette exacte demandée : englobé dans {"forum": [ ... ]}
        wrapped_item = {"forum": [rag_item]}

        # Nom du fichier source préservé ({publicId}.json) pour rester cohérent avec output/
        out_path = cat_dir / file_path.name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(wrapped_item, f, ensure_ascii=False, indent=4)

        processed_count += 1
        ok_urls.append(topic_url)
        rag_items.append(rag_item)

    # ── Calcul des stats finales ─────────────────────────────────────────
    total_input = processed_count + filtered_no_best_answer + filtered_other
    rejected_total = total_input - processed_count
    avg_replies  = round(total_replies / processed_count, 2) if processed_count > 0 else 0
    avg_views    = round(total_views   / processed_count, 2) if processed_count > 0 else 0
    min_replies  = min(r for r, _, _ in reply_counts) if reply_counts else 0
    max_replies  = max(r for r, _, _ in reply_counts) if reply_counts else 0
    resolution_rate = round(processed_count / total_input * 100, 1) if total_input > 0 else 0
    pct_no_best  = round(filtered_no_best_answer / total_input * 100, 1) if total_input > 0 else 0

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

    # Top 10 posts les plus vus (on recollecte depuis rag_items)
    top10_viewed = sorted(rag_items, key=lambda x: x.get("views", 0), reverse=True)[:10]
    top10_viewed_out = [{"title": x["title"], "url": x["url"], "views": x.get("views", 0)} for x in top10_viewed]

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
        "rejected_other":                 filtered_other,
        "deleted_too_old":                filtered_too_old,
        # Réponses (replies)
        "total_replies":                  total_replies,
        "avg_replies_per_post":           avg_replies,
        "min_replies":                    min_replies,
        "max_replies":                    max_replies,
        # Réponses agents ST (solved)
        "st_agent_stats": {
            "forums_with_st_reply":       st_with,
            "forums_without_st_reply":    st_without,
            "st_reply_pct":               round(st_with / processed_count * 100, 1) if processed_count > 0 else 0,
        },
        # Réponses agents ST sur les posts rejetés (Ongoing / non résolus)
        "st_agent_stats_ongoing": {
            "forums_with_st_reply":       ongoing_with,
            "forums_without_st_reply":    ongoing_without,
            "st_reply_pct":               round(ongoing_with / rejected_total * 100, 1) if rejected_total > 0 else 0,
        },
        # Période d'activité des posts analysés (min/max publishedAt)
        "activity_range": {
            "start": activity_min.isoformat() if activity_min else "",
            "end": activity_max.isoformat() if activity_max else "",
        },
        # ── Breakdown Super User : 4 groupes (ST x SU) pour Solved et Ongoing ──
        # Chaque champ représente un NOMBRE DE TOPICS (pas de messages).
        # Exemple de lecture : solved_with_st.with_su = N
        #   → N topics résolus où au moins 1 agent ST ET au moins 1 Super User ont participé.
        # su_pct = part (%) des topics du groupe où un Super User est intervenu.
        "super_user_stats": {
            "solved_with_st": {
                "with_su": solved_with_st_su,       # Solved + ST > 0 + SU > 0  (nb topics)
                "without_su": solved_with_st_nosu,  # Solved + ST > 0 + SU = 0  (nb topics)
                "su_pct": round(solved_with_st_su / (solved_with_st_su + solved_with_st_nosu) * 100, 1) if (solved_with_st_su + solved_with_st_nosu) > 0 else 0,
            },
            "solved_without_st": {
                "with_su": solved_without_st_su,       # Solved + ST = 0 + SU > 0  (nb topics)
                "without_su": solved_without_st_nosu,  # Solved + ST = 0 + SU = 0  (nb topics)
                "su_pct": round(solved_without_st_su / (solved_without_st_su + solved_without_st_nosu) * 100, 1) if (solved_without_st_su + solved_without_st_nosu) > 0 else 0,
            },
            "ongoing_with_st": {
                "with_su": ongoing_with_st_su,       # Ongoing + ST > 0 + SU > 0  (nb topics)
                "without_su": ongoing_with_st_nosu,  # Ongoing + ST > 0 + SU = 0  (nb topics)
                "su_pct": round(ongoing_with_st_su / (ongoing_with_st_su + ongoing_with_st_nosu) * 100, 1) if (ongoing_with_st_su + ongoing_with_st_nosu) > 0 else 0,
            },
            "ongoing_without_st": {
                "with_su": ongoing_without_st_su,       # Ongoing + ST = 0 + SU > 0  (nb topics)
                "without_su": ongoing_without_st_nosu,  # Ongoing + ST = 0 + SU = 0  (nb topics)
                "su_pct": round(ongoing_without_st_su / (ongoing_without_st_su + ongoing_without_st_nosu) * 100, 1) if (ongoing_without_st_su + ongoing_without_st_nosu) > 0 else 0,
            },
        },
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
        "top10_most_viewed_posts":        top10_viewed_out,
        # Images
        "total_images_in_content":        total_images,
        # Par catégorie
        "by_category":                    cat_breakdown,
    }

    print(f"  -> {processed_count} sujets de forum préparés pour le RAG.")
    print(f"     Taux de résolution : {resolution_rate}%")
    if filtered_too_old:
        print(f"     {filtered_too_old} sujet(s) trop ancien(s) supprimé(s) de output/forums.")
    print(f"     Réponses totales   : {total_replies} | Moyenne : {avg_replies} | Max : {max_replies}")
    if top3_replied:
        try:
            print(f"     Post le + répondu  : {top3_replied[0][1][:80]}")
        except Exception:
            pass
    return {"count": processed_count, "ok_urls": ok_urls, "filtered_urls": filtered_urls, "stats": stats, "rag_items": rag_items}


def process_knowledge_base(run_id: str = None) -> dict:
    input_dir = OUTPUT_DIR / run_id / "knowledge_base" if run_id else OUTPUT_DIR / "knowledge_base"
    output_dir = RAG_READY_DIR / run_id / "knowledge_base" if run_id else RAG_READY_DIR / "knowledge_base"
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
    for file_path in input_dir.rglob("*.json"):
        with open(file_path, "r", encoding="utf-8") as f:
            article = json.load(f)

        article_url = article.get("_seoUrl", file_path.name)

        cat_dir = _category_dir(output_dir, article.get("categoryName", ""))

        # 1. Filtre: Date (tout article antérieur à RAG_START_DATE est écarté)
        if not is_recent_enough(article.get("publishedAt")):
            filtered_too_old += 1
            try:
                file_path.unlink()
            except Exception:
                pass
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

        # Nom du fichier source préservé ({publicId}.json) pour rester cohérent avec output/
        out_path = cat_dir / file_path.name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(wrapped_item, f, ensure_ascii=False, indent=4)

        processed_count += 1
        ok_urls.append(article_url)
        rag_items.append(rag_item)

    total_input = processed_count
    accepted_pct = round(processed_count / total_input * 100, 1) if total_input > 0 else 0

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
        "deleted_too_old":        filtered_too_old,
        "total_images_in_content": total_images,
        "by_category":            cat_breakdown_kb,
    }

    print(f"  -> {processed_count} articles préparés pour le RAG.")
    if filtered_too_old:
        print(f"     {filtered_too_old} article(s) trop ancien(s) supprimé(s) de output/knowledge_base.")
    return {"count": processed_count, "ok_urls": ok_urls, "filtered_urls": filtered_urls, "stats": stats, "rag_items": rag_items}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run_prepare(run_id: str = None) -> dict:
    print("Démarrage du pipeline de préparation RAG...")
    start_time_dt = datetime.now()
    start_time_iso = start_time_dt.isoformat()

    forums_report = process_forums(run_id)
    kb_report = process_knowledge_base(run_id)

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
    print(f"  Trop anciens (supprimés) : {f_stats.get('deleted_too_old', 0)}")
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
    print(f"  Trop anciens (supprimés) : {k_stats.get('deleted_too_old', 0)}")
    print("="*55)

    return report
