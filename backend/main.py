import hmac
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from . import ai_engine, settings, segmentation, quality, film, acr_validation, photoshop
from .models import AnalysisRequest, ExportRequest, RenderRequest, SettingsInput, RegionCreate, RegionUpdate, BrushStroke, RefinementRequest, QualityRequest
from .refinement import merge_refinement, undo_refinement, context_images
from .parameter_engine import STYLES, RANGES, build_recipe
from .preview import render
from .raw_decoder import decode, ensure_precision
from .store import JOBS_DIR, get_job, list_jobs, recover_jobs, save_job
from .xmp import build_xmp, template_info

app = FastAPI(title='AI RAW Studio', docs_url=None, redoc_url=None, openapi_url=None)
TOKEN = os.getenv('RAW_STUDIO_TOKEN', '')
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='raw-worker')
lock = threading.RLock()
MAX_UPLOAD = 150 * 1024 * 1024
DEFAULT_TEMPLATE = {'version': '17.3', 'process_version': '15.4', 'kind': 'sidecar'}
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173', 'http://tauri.localhost', 'tauri://localhost'],
                   allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Authorization', 'Content-Type'])

@app.middleware('http')
async def authorize(request: Request, call_next):
    if request.method != 'OPTIONS':
        header = request.headers.get('authorization', '')
        if not TOKEN or not hmac.compare_digest(header, 'Bearer ' + TOKEN):
            return Response(status_code=401)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    return response

def require_job(job_id):
    if not re.fullmatch('[a-f0-9]{32}', job_id):
        raise HTTPException(404, '任务不存在')
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, '任务不存在')
    return job

def ready_job(job_id):
    job = require_job(job_id)
    if 'metrics' not in job:
        raise HTTPException(409, '照片尚未完成解码')
    if (JOBS_DIR / job_id / "source.NEF").is_file():
        ensure_precision(JOBS_DIR / job_id)
    return populate_wb_reference(job)

def populate_wb_reference(job):
    job_id=job['id']
    if 'white_balance_reference' not in job['metrics']:
        reference=job.get('template',{}).get('white_balance_reference')
        template_path=JOBS_DIR/job_id/'template.xmp'
        if reference is None and template_path.exists():
            try:reference=template_info(template_path).get('white_balance_reference')
            except Exception:pass
        job['metrics']['white_balance_reference']=reference or {'temperature':5500,'tint':0,'source':'估计参考值','estimated':True}
    return job

def decode_task(job_id):
    job = require_job(job_id)
    job.update(status='decoding', error=None)
    save_job(job)
    try:
        metadata, metrics, warnings = decode(JOBS_DIR / job_id / 'source.NEF', JOBS_DIR / job_id)
        job.update(status='ready', metadata=metadata, metrics=metrics, warnings=warnings)
        populate_wb_reference(job)
    except Exception:
        logging.exception('RAW decode failed: %s', job_id)
        job.update(status='failed', error='RAW 解码失败。请确认文件完整且相机格式受 LibRaw 支持。')
    save_job(job)

def analysis_task(job_id, intent, conf, key,auto_correct=False):
    job = require_job(job_id)
    try:
        upgrade_preview(job)
        directory = JOBS_DIR / job_id
        if not job.get('regions'):
            job['regions'] = segmentation.segment(directory)
        regions = [segmentation.region_summary(directory, r) for r in job['regions']]
        decision = ai_engine.analyze(directory / 'ai.jpg', job['metrics'], intent, conf, key, regions,
                                     diagnostic_path=directory / 'ai-validation.json')
        job.update(status='complete', decision=decision, ai_model=conf['model'], intent=intent, error=None)
        job.pop('edit_state',None)
        job.pop('refinement_history',None)
        segmentation.apply_plan(job)
        job=quality_after_ai(job,RenderRequest(style=decision['recommended_style']),auto_correct)
    except ValueError as exc:
        job.update(status='ready', error=str(exc))
    except Exception:
        job.update(status='ready', error='AI 分析失败，可重试。本地分析结果已保留。')
    save_job(job)

@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': '0.9.0'}

def upgrade_preview(job):
    if job['metrics'].get('preview_version', 1) < 2:
        metadata, metrics, warnings = decode(JOBS_DIR / job['id'] / 'source.NEF', JOBS_DIR / job['id'])
        job.update(metadata=metadata, metrics=metrics, warnings=warnings)
    populate_wb_reference(job)

@app.get('/api/settings')
def get_settings():
    return settings.public_config()

@app.put('/api/settings')
def put_settings(body: SettingsInput):
    try:
        return settings.update_settings(body)
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(400, str(exc)) from None
        raise HTTPException(400, '无法保存凭据，请取消“记住 Key”后重试。') from None

@app.get('/api/styles')
def styles():
    return {'styles': STYLES, 'ranges': RANGES}

@app.get('/api/jobs')
def jobs():
    return list_jobs()

@app.get('/api/film/catalog')
def film_catalog():
    return film.catalog()

@app.get('/api/jobs/{job_id}/film')
def film_state(job_id: str):
    ready_job(job_id)
    return film.state(job_id)

@app.post('/api/jobs/{job_id}/film/render', status_code=202)
def film_render(job_id: str, body: film.FilmRequest):
    with lock:
        job = editable_job(job_id)
        try:
            return film.start(job, body)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None

@app.post('/api/jobs/{job_id}/film/cancel')
def film_cancel(job_id: str):
    ready_job(job_id)
    film.cancel(job_id)
    return film.state(job_id)

@app.get('/api/jobs/{job_id}/film/{operation}/{kind}')
def film_file(job_id: str, operation: str, kind: str):
    ready_job(job_id)
    if kind not in ('preview', 'before', 'download'):
        raise HTTPException(404, '胶片文件不存在。')
    try:
        path = film.result_file(job_id, operation, kind)
        if not path.is_file():
            raise FileNotFoundError()
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, '胶片结果不存在或尚未完成。') from None
    return FileResponse(path, media_type='image/tiff' if path.suffix == '.tif' else 'image/jpeg', filename=path.name)

@app.get('/api/jobs/{job_id}')
def job_detail(job_id: str):
    return require_job(job_id)

@app.post('/api/jobs', status_code=202)
async def create_job(raw: UploadFile = File(...), template: UploadFile | None = File(None)):
    if not (raw.filename or '').lower().endswith('.nef'):
        raise HTTPException(400, '第一版请导入 NEF 文件。')
    job_id = uuid4().hex
    directory = JOBS_DIR / job_id
    directory.mkdir()
    info = DEFAULT_TEMPLATE.copy()
    try:
        with (directory / 'source.NEF').open('wb') as stream:
            size = 0
            while chunk := await raw.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, 'NEF 超过 150 MB 限制。')
                stream.write(chunk)
        if not size:
            raise HTTPException(400, 'NEF 文件为空。')
        if template:
            content = await template.read(16 * 1024 * 1024 + 1)
            if len(content) > 16 * 1024 * 1024:
                raise HTTPException(413, 'XMP 超过 16 MB 限制。')
            (directory / 'template.xmp').write_bytes(content)
            try:
                info = template_info(directory / 'template.xmp')
            except Exception:
                raise HTTPException(400, 'XMP 模板无效或不包含 Camera Raw 设置。') from None
        job = {'id': job_id, 'filename': Path(raw.filename.replace('\\', '/')).name,
               'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'queued', 'template': info, 'error': None}
        save_job(job)
        executor.submit(decode_task, job_id)
        return job
    except Exception:
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()
        raise
    finally:
        await raw.close()
        if template:
            await template.close()

@app.post('/api/jobs/{job_id}/analyze', status_code=202)
def analyze_job(job_id: str, body: AnalysisRequest):
    with lock:
        job = ready_job(job_id)
        if job['status'] in ('analyzing','refining','correcting'):
            raise HTTPException(409, 'AI 正在分析，请稍候。')
        key = settings.api_key()
        if not key:
            raise HTTPException(400, '请先在设置中填写 API Key。')
        job.update(status='analyzing', error=None)
        save_job(job)
        executor.submit(analysis_task, job_id, body.intent, settings.config(), key,body.auto_correct)
    return job

@app.get('/api/jobs/{job_id}/original')
def original(job_id: str):
    ready_job(job_id)
    directory=JOBS_DIR/job_id
    from .preview import load_source
    from .raw_decoder import SRGB_ICC
    from PIL import Image
    import io, numpy as np
    output=io.BytesIO()
    Image.fromarray(np.rint(load_source(directory/'original.jpg')*255).astype(np.uint8)).save(output,format='PNG',icc_profile=SRGB_ICC)
    return Response(output.getvalue(),media_type='image/png')

def compute(job, body):
    try:
        return build_recipe(job['metrics'], job.get('decision'), body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

def quality_after_ai(job,state,auto_correct=False):
    try:
        if auto_correct:
            job,entry=quality.correct(job,state,JOBS_DIR/job['id'],True)
            if entry:job['refinement_history']=(job.get('refinement_history',[])+[entry])[-20:]
        else:job['quality_report']=quality.check(job,state,JOBS_DIR/job['id'])
        job.pop('quality_error',None)
    except Exception:
        logging.exception('Effect check failed: %s',job['id'])
        job.pop('quality_report',None)
        job['quality_error']='效果检查未完成，原有调色方案已保留，请重试检查。'
    return job

@app.post('/api/jobs/{job_id}/quality/check')
def check_quality(job_id:str,body:QualityRequest):
    with lock:
        job=editable_job(job_id)
        compute(job,body.state)
        try:report=quality.check(job,body.state,JOBS_DIR/job_id)
        except Exception:
            logging.exception('Effect check failed: %s',job_id)
            raise HTTPException(500,'效果检查失败，原有参数未改变。') from None
        job['quality_report']=report
        job.pop('quality_error',None)
        save_job(job)
        return job

def correction_task(job_id,body,operation,prior_status):
    job=ready_job(job_id)
    try:
        job,entry=quality.correct(job,body.state,JOBS_DIR/job_id,body.protect_manual)
        if entry:job['refinement_history']=(job.get('refinement_history',[])+[entry])[-20:]
        job.pop('quality_error',None)
        job.update(status=prior_status,error=None)
    except Exception:
        logging.exception('Automatic correction failed: %s',job_id)
        job.update(status=prior_status,error='自动修正失败，原有方案已保留，可重试。')
    with lock:
        if require_job(job_id).get('active_correction_id')==operation:
            job.pop('active_correction_id',None)
            save_job(job)

@app.post('/api/jobs/{job_id}/quality/correct',status_code=202)
def correct_quality(job_id:str,body:QualityRequest):
    with lock:
        job=editable_job(job_id)
        compute(job,body.state)
        operation=uuid4().hex;prior_status=job['status']
        job.update(status='correcting',active_correction_id=operation,error=None)
        save_job(job)
        executor.submit(correction_task,job_id,body,operation,prior_status)
        return job

def refinement_task(job_id,body,conf,key,operation,prior_status):
    job=ready_job(job_id)
    try:
        recipe=build_recipe(job['metrics'],job.get('decision'),body.state)
        directory=JOBS_DIR/job_id
        current=render(directory/'original.jpg',recipe['parameters'],recipe['curve'],
                       segmentation.selected_regions(job,body.state),directory,curves=recipe['curves'],white_balance=recipe['white_balance'])
        context,mask_image=context_images(job,body.state,recipe,current,directory)
        patch=ai_engine.refine(directory/'ai.jpg',current,job['metrics'],body.instruction,context,conf,key,
                               lambda patch:merge_refinement(job,body.state,patch),
                               diagnostic_path=directory/'refinement-validation.json',mask_image=mask_image)
        updated,entry=merge_refinement(job,body.state,patch)
        entry['instruction']=body.instruction
        updated['refinement_history']=(job.get('refinement_history',[])+[entry])[-20:]
        updated.update(status=prior_status,error=None)
        job=quality_after_ai(updated,RenderRequest.model_validate(updated['edit_state']))
    except ValueError as exc:
        job.update(status=prior_status,error=str(exc))
    except Exception:
        logging.exception('AI refinement failed: %s',job_id)
        job.update(status=prior_status,error='AI 增量修改失败，原有参数已保留，可重试。')
    with lock:
        latest=require_job(job_id)
        if latest.get('active_refinement_id')==operation:
            job.pop('active_refinement_id',None)
            save_job(job)

@app.post('/api/jobs/{job_id}/refine',status_code=202)
def refine_job(job_id:str,body:RefinementRequest):
    with lock:
        job=editable_job(job_id)
        if not body.instruction.strip():
            raise HTTPException(400,'请输入本次修改要求。')
        compute(job,body.state)
        key=settings.api_key()
        if not key:raise HTTPException(400,'请先在设置中填写 API Key。')
        prior_status=job['status']
        operation=uuid4().hex
        job.update(status='refining',active_refinement_id=operation,error=None)
        save_job(job)
        executor.submit(refinement_task,job_id,body,settings.config(),key,operation,prior_status)
    return job

@app.post('/api/jobs/{job_id}/refine/undo')
def undo_refinement_job(job_id:str):
    with lock:
        job=editable_job(job_id)
        try:job=undo_refinement(job)
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        job['error']=None
        save_job(job)
        return job

@app.post('/api/jobs/{job_id}/parameters')
def parameters(job_id: str, body: RenderRequest):
    job = ready_job(job_id)
    recipe = compute(job, body)
    recipe['regions'] = segmentation.selected_regions(job, body)
    return recipe

@app.post('/api/jobs/{job_id}/preview')
def preview(job_id: str, body: RenderRequest):
    job = ready_job(job_id)
    recipe = compute(job, body)
    return Response(render(JOBS_DIR / job_id / 'original.jpg', recipe['parameters'], recipe['curve'],
                             segmentation.selected_regions(job, body), JOBS_DIR / job_id, curves=recipe['curves'],white_balance=recipe['white_balance']), media_type='image/png')

@app.post('/api/jobs/{job_id}/export')
def export(job_id: str, body: ExportRequest):
    job = ready_job(job_id)
    recipe = compute(job, body)
    data = build_xmp(recipe['parameters'], body.name, body.mode, job['template'], recipe['curve'],
                     segmentation.selected_regions(job, body), JOBS_DIR / job_id, curves=recipe['curves'],white_balance=recipe['white_balance'])
    return Response(data, media_type='application/rdf+xml', headers={'Content-Disposition': 'attachment; filename="AI_RAW_Studio.xmp"'})

def editable_job(job_id):
    job = ready_job(job_id)
    if job['status'] in ('analyzing','refining','correcting'):
        raise HTTPException(409, 'AI 分析期间请暂缓修改选区。')
    return job

def require_region(job, region_id):
    region = next((r for r in job.get('regions', []) if r['id'] == region_id), None)
    if region is None:
        raise HTTPException(404, '选区不存在')
    return region

@app.post('/api/jobs/{job_id}/segment')
def segment_job(job_id: str):
    with lock:
        job = editable_job(job_id)
        try:
            upgrade_preview(job)
            if not job.get('regions'):
                job['regions'] = segmentation.segment(JOBS_DIR / job_id)
            save_job(job)
            return job
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

@app.post('/api/jobs/{job_id}/regions')
def create_region(job_id: str, body: RegionCreate):
    with lock:
        job = editable_job(job_id)
        if len(job.get('regions', [])) >= 12:
            raise HTTPException(400, '最多保留 12 个选区。')
        try:
            region = segmentation.create_custom(JOBS_DIR / job_id, body.name, body.bbox)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        job.setdefault('regions', []).append(region)
        save_job(job)
        return job

@app.get('/api/jobs/{job_id}/regions/{region_id}/mask')
def region_mask(job_id: str, region_id: str):
    job = ready_job(job_id)
    region = require_region(job, region_id)
    return FileResponse(JOBS_DIR / job_id / (region['id'] + '.png'), media_type='image/png')

@app.put('/api/jobs/{job_id}/regions/{region_id}')
def update_region(job_id: str, region_id: str, body: RegionUpdate):
    with lock:
        job = editable_job(job_id)
        region = require_region(job, region_id)
        values = body.model_dump(exclude_none=True)
        region.update(values)
        if body.adjustments is not None:
            region.update(manual_adjustments=True, adjustment_source='手动局部调整')
        region['revision'] = region.get('revision', 0) + 1
        save_job(job)
        return job

@app.post('/api/jobs/{job_id}/regions/{region_id}/paint')
def paint_region(job_id: str, region_id: str, body: BrushStroke):
    with lock:
        job = editable_job(job_id)
        region = require_region(job, region_id)
        segmentation.paint(JOBS_DIR / job_id, region, body)
        save_job(job)
        return job

@app.post('/api/jobs/{job_id}/regions/{region_id}/undo')
def undo_region(job_id: str, region_id: str):
    import shutil
    with lock:
        job = editable_job(job_id)
        region = require_region(job, region_id)
        directory = JOBS_DIR / job_id
        previous = directory / (region_id + '.previous.png')
        if not previous.exists():
            raise HTTPException(400, '没有可撤销的笔画。')
        shutil.copy2(previous, directory / (region_id + '.png'))
        previous.unlink()
        region['revision'] = region.get('revision', 0) + 1
        region['area'] = segmentation.region_summary(directory, region)['area']
        save_job(job)
        return job

@app.post('/api/jobs/{job_id}/regions/{region_id}/refine')
def refine_region(job_id: str, region_id: str):
    with lock:
        job = editable_job(job_id)
        region = require_region(job, region_id)
        try:
            segmentation.refine_region(JOBS_DIR / job_id, region)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        save_job(job)
        return job

@app.delete('/api/jobs/{job_id}/regions/{region_id}')
def delete_region(job_id: str, region_id: str):
    with lock:
        job = editable_job(job_id)
        region = require_region(job, region_id)
        for suffix in ['.png', '.previous.png']:
            path = JOBS_DIR / job_id / (region['id'] + suffix)
            path.unlink(missing_ok=True)
        job['regions'] = [r for r in job['regions'] if r['id'] != region_id]
        save_job(job)
        return job

@app.delete('/api/jobs/{job_id}')
def delete_job(job_id: str):
    from .store import connect
    with lock:
        job = require_job(job_id)
        if job['status'] in ('queued', 'decoding', 'analyzing','refining','correcting') or film.busy(job_id) or photoshop.busy(job_id):
            raise HTTPException(409, '请等待任务结束再删除。')
        directory = JOBS_DIR / job_id
        import shutil
        if not directory.resolve().is_relative_to(JOBS_DIR.resolve()) or directory.resolve() == JOBS_DIR.resolve():
            raise HTTPException(400, '缓存位置无效，无法删除。')
        shutil.rmtree(directory)
        with connect() as db:
            db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
    return {'deleted': True}


@app.post('/api/jobs/{job_id}/detail')
def preview_detail(job_id: str, body: RenderRequest, x: float=.5, y: float=.5):
    from .preview import detail
    import math
    if not math.isfinite(x) or not math.isfinite(y) or not 0<=x<=1 or not 0<=y<=1:
        raise HTTPException(400,'查看位置超出图像。')
    with lock:
        job=editable_job(job_id)
        return Response(detail(JOBS_DIR/job_id,compute(job,body),segmentation.selected_regions(job,body),x,y),media_type='image/png')


@app.post('/api/jobs/{job_id}/validation')
def create_validation(job_id: str, body: RenderRequest):
    with lock:
        job=editable_job(job_id)
        return acr_validation.create(job,body,compute(job,body),JOBS_DIR/job_id)


@app.get('/api/photoshop')
def photoshop_connection():
    return photoshop.catalog()


@app.post('/api/jobs/{job_id}/validation/render', status_code=202)
def render_validation(job_id: str, body: RenderRequest, refresh: bool=False):
    with lock:
        job=editable_job(job_id)
        recipe=compute(job,body)
        signature=acr_validation.signature(job,body)
        roots=sorted((JOBS_DIR/job_id/'validation').glob('*/snapshot.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        for path in roots:
            record=json.loads(path.read_text('utf-8'))
            task=photoshop.state(path.parent)
            if record['signature']==signature and task and (task['status']=='running' or (not refresh and task['status']=='complete' and task.get('bridge_version')==1 and (path.parent/'report.json').is_file())):
                return validation_record(path.parent)
        if photoshop.busy():raise HTTPException(409,'Photoshop 正在生成另一份预览，请等待完成后重试。')
        conf=photoshop.catalog()
        if not conf['available']:raise HTTPException(400,conf['message'])
        try:
            record=acr_validation.create(job,body,recipe,JOBS_DIR/job_id,package=False)
            record['photoshop']=photoshop.start(job_id,record)
            return record
        except ValueError as exc:raise HTTPException(400,str(exc)) from None
        except RuntimeError as exc:raise HTTPException(409,str(exc)) from None


def validation_root(job_id, snapshot_id):
    require_job(job_id)
    if not re.fullmatch('[a-f0-9]{32}',snapshot_id):raise HTTPException(404,'对照快照不存在。')
    root=JOBS_DIR/job_id/'validation'/snapshot_id
    if not (root/'snapshot.json').exists():raise HTTPException(404,'对照快照不存在。')
    return root


def validation_record(root):
    record=json.loads((root/'snapshot.json').read_text('utf-8'))
    task=photoshop.state(root)
    if task:record['photoshop']=task
    if (not task or task['status']=='complete') and (root/'report.json').exists():
        record['report']=json.loads((root/'report.json').read_text('utf-8'))
    return record


@app.get('/api/jobs/{job_id}/validation/{snapshot_id}')
def validation_detail(job_id: str,snapshot_id: str):
    with lock:return validation_record(validation_root(job_id,snapshot_id))


@app.get('/api/jobs/{job_id}/validation/{snapshot_id}/{kind}')
def validation_file(job_id: str,snapshot_id: str,kind: str):
    names={'package':'package.zip','reference':'reference.png','acr':'acr.png','difference':'difference.png','report':'report.json'}
    with lock:
        root=validation_root(job_id,snapshot_id)
        if kind not in names or not (root/names[kind]).is_file():raise HTTPException(404,'对照文件尚未生成。')
        return FileResponse(root/names[kind],filename=names[kind])


@app.post('/api/jobs/{job_id}/validation/{snapshot_id}/compare')
async def compare_validation(job_id: str,snapshot_id: str,image: UploadFile=File(...),
                             assume_srgb: bool=False,acr_version: str='',camera_profile: str=''):
    try:
        content=await image.read(MAX_UPLOAD+1)
        with lock:
            root=validation_root(job_id,snapshot_id)
            try:return acr_validation.compare(root,content,assume_srgb,acr_version,camera_profile)
            except ValueError as exc:raise HTTPException(400,str(exc)) from None
    finally:await image.close()


@app.get('/api/jobs/{job_id}/validation')
def latest_validation(job_id: str):
    with lock:
        require_job(job_id)
        roots=list((JOBS_DIR/job_id/'validation').glob('*/snapshot.json'))
        if not roots:return None
        root=max(roots,key=lambda p:p.stat().st_mtime).parent
        return validation_record(root)
