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
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, Response, send_from_directory

app = Flask(__name__)
# Chemin vers le dossier racine du projet
BASE_DIR = Path(__file__).parent.parent
ENV_PATH = BASE_DIR / ".env"
STATS_PATH = Path(__file__).parent / "latest_stats.json"

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

@app.route("/api/run", methods=["POST"])
def run_pipeline():
    global current_process
    data = request.json
    start_date = data.get("start_date")
    
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
