"""Isolated, offline spektrafilm worker; never changes the Camera Raw recipe."""
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from pydantic import Field
from typing import Literal
from .models import StrictModel
from .store import JOBS_DIR, DATA_DIR


class FilmRequest(StrictModel):
    film: str = Field(default='kodak_portra_400', pattern=r'^[a-z0-9_]+$', max_length=120)
    paper: str = Field(default='kodak_portra_endura', pattern=r'^[a-z0-9_]+$', max_length=120)
    exposure: float = Field(default=0, ge=-4, le=4)
    print_exposure: float = Field(default=0, ge=-3, le=3)
    auto_exposure: bool = True
    grain: bool = True
    halation: float = Field(default=1, ge=0, le=2)
    include_local_exposure: bool = False
    format: Literal['preview', 'tiff', 'jpeg'] = 'preview'


_lock = threading.RLock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='film-worker')
_active = None
_process = None
_cancelled = set()


def runtime_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / 'film-runtime'
    return Path(__file__).resolve().parents[1] / '.tools' / 'film-runtime'


def catalog():
    directory = runtime_dir()
    path = directory / 'catalog.json'
    if not path.exists() or not (directory / 'python.exe').exists():
        return {'available': False, 'message': '胶片引擎尚未准备，请运行项目的胶片引擎准备脚本。', 'films': [], 'papers': []}
    result = json.loads(path.read_text(encoding='utf-8'))
    result['available'] = True
    return result


def _directory(job_id, operation):
    if not re.fullmatch('[a-f0-9]{32}', operation):
        raise ValueError('胶片任务不存在。')
    return JOBS_DIR / job_id / 'film' / operation


def _write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    for attempt in range(10):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 9:raise
            time.sleep(.02)


def state(job_id):
    pointer = JOBS_DIR / job_id / 'film' / 'latest.json'
    if not pointer.exists():
        return {'status': 'idle'}
    operation = json.loads(pointer.read_text())['operation']
    result = json.loads((_directory(job_id, operation) / 'state.json').read_text(encoding='utf-8'))
    progress = _directory(job_id, operation) / 'progress.json'
    if result['status'] == 'running' and progress.exists():
        result['stage'] = json.loads(progress.read_text(encoding='utf-8'))['stage']
    previous = pointer.parent / 'last-complete.json'
    if result['status'] != 'complete' and previous.exists():
        prior = json.loads(previous.read_text())['operation']
        result['previous'] = json.loads((_directory(job_id, prior) / 'state.json').read_text(encoding='utf-8'))
    return result


def start(job, body):
    global _active
    conf = catalog()
    if not conf['available']:
        raise ValueError(conf['message'])
    if body.film not in {x['id'] for x in conf['films']} or body.paper not in {x['id'] for x in conf['papers']}:
        raise ValueError('请选择引擎内置的胶片和相纸。')
    with _lock:
        if _active:
            raise RuntimeError('已有胶片任务正在渲染，请等待完成或取消。')
        operation = uuid4().hex
        directory = _directory(job['id'], operation)
        directory.mkdir(parents=True)
        payload = {'operation': operation, 'job_id': job['id'], 'status': 'queued',
                   'options': body.model_dump(), 'started_at': time.time(), 'stage': '等待引擎启动'}
        _write(directory / 'state.json', payload)
        request = {'source': str(JOBS_DIR / job['id'] / 'source.NEF'), 'output': str(directory),
                   'options': body.model_dump(), 'parent_pid': os.getpid(), 'masks': []}
        if body.include_local_exposure:
            import shutil
            for region in job.get('regions', []):
                exposure = region.get('adjustments', {}).get('exposure', 0)
                if region.get('enabled') and exposure and re.fullmatch('[a-f0-9]{32}', region['id']):
                    name = region['id'] + '.png'
                    if not (JOBS_DIR / job['id'] / name).is_file():
                        raise ValueError('局部选区数据缺失，请修复选区后重试。')
                    shutil.copy2(JOBS_DIR / job['id'] / name, directory / name)
                    request['masks'].append({'file': name, 'exposure': exposure, 'feather': region.get('feather', 0)})
        _write(directory / 'request.json', request)
        payload['local_snapshot'] = [dict(id=r['id'], revision=r.get('revision',0), feather=r.get('feather',0), exposure=r.get('adjustments',{}).get('exposure',0)) for r in job.get('regions',[]) if r.get('enabled') and r.get('adjustments',{}).get('exposure',0)] if body.include_local_exposure else []
        _write(directory / 'state.json', payload)
        _write(directory.parent / 'latest.json', {'operation': operation})
        _active = (job['id'], operation)
        _executor.submit(_run, job['id'], operation)
        return payload


def _run(job_id, operation):
    global _active, _process
    directory = _directory(job_id, operation)
    payload = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    try:
        with _lock:
            if operation in _cancelled:
                raise InterruptedError()
            payload.update(status='running', stage='正在启动胶片引擎')
            _write(directory / 'state.json', payload)
            runtime = runtime_dir()
            cache = DATA_DIR / 'film-cache'
            cache.mkdir(exist_ok=True)
            env = dict(os.environ, NUMBA_CACHE_DIR=str(cache), NUMBA_NUM_THREADS='4',
                       OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='4', PYTHONUTF8='1',
                       MPLCONFIGDIR=str(cache / 'matplotlib'))
            # The worker receives no API configuration or key.
            for key in list(env):
                if any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'SECRET')):
                    env.pop(key)
            log = (directory / 'engine.log').open('wb')
            worker = Path(__file__).with_name('film_worker.py')
            _process = subprocess.Popen([str(runtime / 'python.exe'), '-I', '-u', str(worker), str(directory / 'request.json')],
                cwd=runtime, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=0x08000000 if os.name == 'nt' else 0)
            process = _process
        try:
            code = process.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
            raise ValueError('胶片渲染超过一小时，已停止。请降低图像尺寸或关闭颗粒后重试。')
        finally:
            log.close()
        if operation in _cancelled:
            raise InterruptedError()
        if code != 0 or not (directory / 'result.json').exists():
            raise ValueError('胶片引擎渲染失败，请重试；详细原因保存在本机任务的 engine.log 中。')
        result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
        payload.update(status='complete', stage='渲染完成', result=result)
    except InterruptedError:
        payload.update(status='cancelled', stage='已取消')
    except Exception as exc:
        payload.update(status='failed', stage='渲染失败', error=str(exc))
    finally:
        payload['elapsed_seconds'] = round(time.time() - payload['started_at'], 1)
        with _lock:
            _write(directory / 'state.json', payload)
            if payload['status'] == 'complete':
                _write(directory.parent / 'last-complete.json', {'operation': operation})
            _process = None
            _active = None
            _cancelled.discard(operation)


def cancel(job_id):
    with _lock:
        if _active and _active[0] == job_id:
            _cancelled.add(_active[1])
            if _process and _process.poll() is None:
                _process.kill()


def busy(job_id):
    with _lock:
        return bool(_active and _active[0] == job_id)


def result_file(job_id, operation, kind):
    directory = _directory(job_id, operation)
    payload = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    if payload['status'] != 'complete':
        raise ValueError('胶片任务尚未完成。')
    name = {'preview': 'preview.jpg', 'before': 'before.jpg'}.get(kind, payload['result']['filename'])
    if not re.fullmatch(r'(preview\.jpg|before\.jpg|film-[a-z0-9_]+\.(tif|jpg))',name):
        raise ValueError('胶片结果文件名无效。')
    return directory / name


def recover():
    # Only interrupted operations are changed; successful results remain downloadable.
    for path in JOBS_DIR.glob('*/film/*/state.json'):
        try:payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):continue
        if payload['status'] in ('queued', 'running'):
            payload.update(status='interrupted', stage='上次胶片任务已中断，请重新生成')
            _write(path, payload)
