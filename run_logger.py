#!/usr/bin/env python3
"""
Logger par run : chaque exécution du pipeline crée un dossier horodaté dans logs/
avec run.log (tee de la console), ErrorLog.txt (erreurs) et stats.json (statistiques).

Usage :
    with RunLogger("pipeline") as rl:
        rl.error("message d'erreur")
        rl.save_stats({...})
        # chemin du dossier courant : rl.folder (ou run_logger.current_run_dir())
"""

import io
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
LOGS_DIR = BASE / "logs"

_current = None  # instance RunLogger active (singleton)


class _Tee(io.TextIOBase):
    """Duplique l'écriture entre un flux et un fichier de log."""

    def __init__(self, stream, file):
        self.stream = stream
        self.file = file

    def write(self, s):
        self.stream.write(s)
        try:
            self.file.write(s)
            self.file.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self.stream.flush()
            self.file.flush()
        except Exception:
            pass


class RunLogger:
    """Contexte de run : crée logs/<ts>_<label>/ et capture toute la sortie console."""

    def __init__(self, label="pipeline"):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.folder = LOGS_DIR / f"{ts}_{label}"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.run_log = open(self.folder / "run.log", "w", encoding="utf-8")
        self.error_log = open(self.folder / "ErrorLog.txt", "w", encoding="utf-8")

        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        sys.stdout = _Tee(self._old_stdout, self.run_log)
        sys.stderr = _Tee(self._old_stderr, self.run_log)

        global _current
        _current = self
        print(f"[LOGS] Dossier du run : {self.folder}")

    def error(self, msg):
        """Journalise une erreur dans ErrorLog.txt + console + run.log."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        try:
            self.error_log.write(line + "\n")
            self.error_log.flush()
            self.run_log.write(line + "\n")
            self.run_log.flush()
        except Exception:
            pass
        print(f"ERROR: {msg}")

    def save_stats(self, stats):
        """Écrit les statistiques du run dans stats.json (dans le dossier du run)."""
        with open(self.folder / "stats.json", "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=4)

    def close(self):
        sys.stdout = self._old_stdout
        sys.stderr = self._old_stderr
        try:
            self.run_log.close()
        except Exception:
            pass
        try:
            self.error_log.close()
        except Exception:
            pass
        global _current
        _current = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def current_run_dir():
    """Retourne le dossier du run actif (ou None si aucun run logger actif)."""
    return _current.folder if _current else None


def current_run_id():
    """Retourne l'identifiant du run actif (nom du dossier logs/<ts>_pipeline), ou None."""
    return _current.folder.name if _current else None


def error(msg):
    """Journalise une erreur : vers ErrorLog.txt si un run est actif, sinon console."""
    if _current:
        _current.error(msg)
    else:
        print(f"ERROR: {msg}")