import json
import os
import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(os.getenv('RAW_STUDIO_DATA_DIR', str(Path(os.getenv('LOCALAPPDATA', Path.cwd() / 'work')) / 'AI RAW Studio')))
DATA_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR = DATA_DIR / 'jobs'
JOBS_DIR.mkdir(exist_ok=True)
_lock = threading.RLock()

def connect():
    db = sqlite3.connect(DATA_DIR / 'studio.sqlite3', timeout=20)
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return db

def save_job(job):
    with _lock, connect() as db:
        db.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?)', (job['id'], json.dumps(job, ensure_ascii=False, allow_nan=False)))

def get_job(job_id):
    with connect() as db:
        row = db.execute('SELECT payload FROM jobs WHERE id = ?', (job_id,)).fetchone()
    return json.loads(row[0]) if row else None

def list_jobs():
    with connect() as db:
        rows = db.execute('SELECT payload FROM jobs ORDER BY rowid DESC LIMIT 30').fetchall()
    return [json.loads(r[0]) for r in rows]

def recover_jobs():
    for job in list_jobs():
        if job['status'] in ('queued', 'decoding', 'analyzing','refining','correcting'):
            job.pop('active_refinement_id',None)
            job.pop('active_correction_id',None)
            job.update(status='ready' if 'metrics' in job else 'failed', error='上次任务被中断，可重新分析或重新导入。')
            save_job(job)
