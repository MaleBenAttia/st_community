"""
Serveur Backend Flask pour le Dashboard RAG STMicroelectronics.

Propose les endpoints nécessaires pour :
1. Servir le Dashboard HTML.
2. Exposer les métriques et statistiques calculées (/api/stats).
3. Déclencher l'exécution du pipeline en arrière-plan avec mise à jour du .env (/api/run).
4. Interrompre le pipeline en cours (/api/stop).
5. Diffuser les logs d'exécution en temps réel via SSE (/api/logs).
"""

import os
import sys
import json
import re
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_file, send_from_directory

app = Flask(__name__)
# Chemin vers le dossier racine du projet
BASE_DIR = Path(__file__).parent.parent
ENV_PATH = BASE_DIR / ".env"
STATS_PATH = Path(__file__).parent / "latest_stats.json"
LOGS_DIR = BASE_DIR / "logs"

current_process = None

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.Html")

@app.route("/api/stats")
def get_stats():
    if STATS_PATH.exists():
        with open(STATS_PATH, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"error": "No stats found yet. Please run the pipeline."}), 404

RUN_NAME_RE = re.compile(r"^\d{8}_\d{6}_pipeline$")
RUN_FILES = ("run.log", "ErrorLog.txt", "stats.json", "scan_report.txt", "extracted_ids.txt")
RUN_FILE_MIME = {
    "stats.json": "application/json",
    "run.log": "text/plain; charset=utf-8",
    "ErrorLog.txt": "text/plain; charset=utf-8",
    "scan_report.txt": "text/plain; charset=utf-8",
    "extracted_ids.txt": "text/plain; charset=utf-8",
}

def _run_folders():
    return sorted(LOGS_DIR.glob("*_pipeline"), reverse=True)

def _count_errors(folder):
    ep = folder / "ErrorLog.txt"
    if not ep.exists():
        return 0
    try:
        return sum(1 for line in open(ep, encoding="utf-8") if line.strip())
    except Exception:
        return 0

def _read_run_log(folder):
    lp = folder / "run.log"
    if not lp.exists():
        return ""
    try:
        return lp.read_text(encoding="utf-8")
    except Exception:
        return ""

def _read_run_stats(folder):
    sp = folder / "stats.json"
    if not sp.exists():
        return {}
    try:
        with open(sp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _name_to_iso(name):
    """Convertit un nom de dossier '20260818_145517_pipeline' en ISO si possible."""
    m = RUN_NAME_RE.match(name or "")
    if not m:
        return None
    date_part, time_part = name.replace("_pipeline", "").split("_")
    return f"{date_part[0:4]}-{date_part[4:6]}-{date_part[6:8]}T{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}"

def _run_summary(folder):
    stats = _read_run_stats(folder)
    info = stats.get("pipeline_run_info", {}) or {}
    start = info.get("start_time") or _name_to_iso(folder.name)
    return {
        "name": folder.name,
        "start_time": start,
        "total_duration_seconds": info.get("total_duration_seconds"),
        "errors": _count_errors(folder),
        "has_stats": bool(stats),
    }

@app.route("/api/runs")
def list_runs():
    """Renvoie TOUS les runs du pipeline (logs/<ts>_pipeline), du plus récent au plus ancien."""
    folders = _run_folders()
    if not folders:
        return jsonify({"error": "No run found yet. Please run the pipeline."}), 404
    return jsonify({"runs": [_run_summary(f) for f in folders]})

@app.route("/api/runs/<name>")
def get_run(name):
    """Renvoie le détail d'un run précis (stats, erreurs, fin de log)."""
    if not RUN_NAME_RE.match(name):
        return jsonify({"error": "Invalid run name."}), 404
    folder = LOGS_DIR / name
    if not folder.is_dir():
        return jsonify({"error": "Run not found."}), 404
    return jsonify({
        "name": folder.name,
        "stats": _read_run_stats(folder),
        "errors": _count_errors(folder),
        "log": _read_run_log(folder)[-30000:],
    })

@app.route("/api/runs/<name>/files")
def list_run_files(name):
    """Renvoie la liste des fichiers disponibles d'un run (stats, log, erreurs...)."""
    if not RUN_NAME_RE.match(name):
        return jsonify({"error": "Invalid run name."}), 404
    folder = LOGS_DIR / name
    if not folder.is_dir():
        return jsonify({"error": "Run not found."}), 404
    files = []
    for fn in RUN_FILES:
        fp = folder / fn
        if fp.is_file():
            try:
                size = fp.stat().st_size
            except Exception:
                size = 0
            files.append({"name": fn, "size": size})
    return jsonify({"files": files})

@app.route("/api/runs/<name>/files/<filename>")
def get_run_file(name, filename):
    """Sert le fichier brut d'un run (nom validé par liste blanche)."""
    if not RUN_NAME_RE.match(name) or filename not in RUN_FILES:
        return jsonify({"error": "Invalid run name or file."}), 404
    folder = LOGS_DIR / name
    if not folder.is_dir():
        return jsonify({"error": "Run not found."}), 404
    fp = folder / filename
    if not fp.is_file():
        return jsonify({"error": "File not found."}), 404
    return send_file(fp, mimetype=RUN_FILE_MIME.get(filename, "text/plain; charset=utf-8"), as_attachment=False)

@app.route("/api/run", methods=["POST"])
def run_pipeline():
    global current_process
    data = request.json
    start_date = data.get("start_date")
    full = bool(data.get("full", False))
    
    if start_date:
        update_env_date(start_date)

    if current_process and current_process.poll() is None:
        return jsonify({"status": "error", "message": "Pipeline already running"}), 400

    log_file = Path(__file__).parent / "current_run.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("Démarrage du pipeline...\n")
        
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if start_date:
        env["RAG_START_DATE"] = start_date
        os.environ["RAG_START_DATE"] = start_date
    if full:
        env["FULL_RESCRAPE"] = "1"

    current_process = subprocess.Popen(
        [sys.executable, "-u", str(BASE_DIR / "run_pipeline.py")],
        cwd=str(BASE_DIR),
        stdout=open(log_file, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env=env
    )
    
    return jsonify({"status": "started", "message": "Pipeline is running in background"})

@app.route("/api/stop", methods=["POST"])
def stop_pipeline():
    global current_process
    if current_process and current_process.poll() is None:
        current_process.terminate()
        current_process = None
        log_file = Path(__file__).parent / "current_run.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n==================================================\n")
            f.write("   PIPELINE ARRÊTÉ PAR L'UTILISATEUR\n")
            f.write("==================================================\n")
        return jsonify({"status": "stopped", "message": "Pipeline stopped"})
    return jsonify({"status": "not_running", "message": "No pipeline running"})

@app.route("/api/logs")
def stream_logs():
    def generate():
        log_file = Path(__file__).parent / "current_run.log"
        if not log_file.exists():
            yield "data: En attente des logs...\n\n"
            
        with open(log_file, "r", encoding="utf-8") as f:
            while True:
                line = f.readline()
                if line:
                    yield f"data: {line}\n\n"
                else:
                    # Pour éviter une boucle infinie à 100% CPU quand il n'y a pas de nouvelle ligne
                    import time
                    time.sleep(0.5)
                    # TODO: condition de sortie quand le process est terminé. 
                    # Pour un POC, ce stream continu est suffisant, le front fermera la connexion.

    return Response(generate(), mimetype="text/event-stream")

def update_env_date(new_date):
    """Met à jour RAG_START_DATE dans le fichier .env de manière sécurisée"""
    os.environ["RAG_START_DATE"] = new_date
    if not ENV_PATH.exists():
        return
        
    lines = []
    found = False
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        for line in lines:
            if line.startswith("RAG_START_DATE="):
                f.write(f"RAG_START_DATE={new_date}\n")
                found = True
            else:
                f.write(line)
        if not found:
            f.write(f"\nRAG_START_DATE={new_date}\n")

if __name__ == "__main__":
    print("Dashboard Server running on http://127.0.0.1:5000")
    app.run(port=5000, debug=True)
