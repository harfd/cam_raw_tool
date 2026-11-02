"""Real NEF / process / ICC / bit-depth validation. Does not use an AI API."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import httpx

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--packaged',action='store_true');parser.add_argument('--full',action='store_true');args=parser.parse_args()
directory=root/'work'/('film-smoke-packaged' if args.packaged else 'film-smoke');directory.mkdir(exist_ok=True)
source=root/'DSC_0002.NEF';original_hash=hashlib.sha256(source.read_bytes()).hexdigest()
command=[str(root/'dist/raw-studio-server/raw-studio-server.exe')] if args.packaged else [sys.executable,'-m','backend.server']
env={**os.environ,'RAW_STUDIO_DATA_DIR':str(directory/'data')}
with (directory/'backend.log').open('wb') as log:
    child=subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=log,creationflags=0x08000000)
    try:
        conf=json.loads(child.stdout.readline())
        with httpx.Client(base_url=conf['url'],headers={'Authorization':'Bearer '+conf['token']},timeout=120) as client:
            for _ in range(100):
                try:
                    if client.get('/api/health').status_code==200:break
                except httpx.ConnectError:pass
                time.sleep(.1)
            catalog=client.get('/api/film/catalog').json();assert catalog['available']
            with source.open('rb') as stream:
                response=client.post('/api/jobs',files={'raw':('film-validation.NEF',stream,'application/octet-stream')});response.raise_for_status();job_id=response.json()['id']
            for _ in range(200):
                job=client.get('/api/jobs/'+job_id).json()
                if 'metrics' in job:break
                time.sleep(.2)
            assert 'metrics' in job
            created=client.post(f'/api/jobs/{job_id}/regions',json={'name':'人物曝光验证','bbox':[.3,.58,.49,.99]});created.raise_for_status()
            region=created.json()['regions'][-1]
            client.put(f"/api/jobs/{job_id}/regions/{region['id']}",json={'adjustments':{'exposure':.5}}).raise_for_status()
            recipe=client.post(f'/api/jobs/{job_id}/parameters',json={'style':'natural'}).json()
            def wait():
                last=None
                for _ in range(1800):
                    state=client.get(f'/api/jobs/{job_id}/film').json()
                    if state.get('stage')!=last:print(state.get('stage'),flush=True);last=state.get('stage')
                    if state['status'] not in ('queued','running'):break
                    time.sleep(1)
                return state
            options={'film':'kodak_portra_400','paper':'kodak_portra_endura','auto_exposure':True,'grain':True,'halation':1,'include_local_exposure':True}
            # A real worker must be cancellable, and deletion must be blocked while running.
            client.post(f'/api/jobs/{job_id}/film/render',json={**options,'format':'tiff'}).raise_for_status()
            assert client.delete('/api/jobs/'+job_id).status_code==409
            client.post(f'/api/jobs/{job_id}/film/cancel',json={}).raise_for_status()
            assert wait()['status']=='cancelled'
            client.post(f'/api/jobs/{job_id}/film/render',json={**options,'format':'preview'}).raise_for_status()
            preview=wait();assert preview['status']=='complete',preview
            assert preview['result']['width']<=960 and preview['result']['local_exposure_masks']==1
            for kind in ('preview','before'):
                response=client.get(f"/api/jobs/{job_id}/film/{preview['operation']}/{kind}");response.raise_for_status();(directory/f'{kind}.jpg').write_bytes(response.content)
            if args.full:
                client.post(f'/api/jobs/{job_id}/film/render',json={**options,'format':'tiff'}).raise_for_status()
                complete=wait();assert complete['status']=='complete',complete
                response=client.get(f"/api/jobs/{job_id}/film/{complete['operation']}/download");response.raise_for_status();output=directory/'film-validation.tif';output.write_bytes(response.content)
                validator="import tifffile,numpy as np,json,sys; t=tifffile.TiffFile(sys.argv[1]);p=t.pages[0];a=p.asarray();assert a.dtype==np.uint16 and a.shape[2]==3;assert 34675 in p.tags;assert np.any(a%257!=0);print(json.dumps({'shape':a.shape,'dtype':str(a.dtype),'icc':len(p.tags[34675].value),'levels':len(np.unique(a[:,:,1]))}))"
                runtime=root/('dist/raw-studio-server/film-runtime' if args.packaged else '.tools/film-runtime')
                checked=json.loads(subprocess.check_output([str(runtime/'python.exe'),'-I','-c',validator,str(output)],text=True))
                assert checked['shape'][:2]==[job['metadata']['height'],job['metadata']['width']]
                complete['verified_tiff']=checked
            else:complete=preview
            after=client.post(f'/api/jobs/{job_id}/parameters',json={'style':'natural'}).json();assert after==recipe
            assert hashlib.sha256(source.read_bytes()).hexdigest()==original_hash
            complete['validation']={'original_unchanged':True,'xmp_recipe_unchanged':True,'cancel':'passed','local_exposure':'passed','packaged':args.packaged}
            (directory/'report.json').write_text(json.dumps(complete,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'status':'passed','elapsed_seconds':complete['elapsed_seconds'],'tiff':complete.get('verified_tiff'),'films':len(catalog['films']),'papers':len(catalog['papers'])}),flush=True)
    finally:
        child.kill();child.wait()
