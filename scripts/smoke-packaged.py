"""Verify the bundled service without requiring a real API key."""
import json
import os
import subprocess
import time
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
env = {**os.environ, 'RAW_STUDIO_DATA_DIR': str(root / 'work' / 'packaged-test')}
child = subprocess.Popen([str(root / 'dist/raw-studio-server/raw-studio-server.exe')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
try:
    line = child.stdout.readline()
    if not line:
        raise RuntimeError(child.stderr.read()[-3000:])
    config = json.loads(line)
    with httpx.Client(base_url=config['url'], headers={'Authorization': 'Bearer ' + config['token']}, timeout=30) as client:
        for _ in range(30):
            try:
                health=client.get('/api/health')
                assert health.status_code == 200 and health.json()['version']=='0.9.0'
                break
            except httpx.ConnectError:
                time.sleep(.2)
        with (root / 'DSC_0002.NEF').open('rb') as raw:
            response = client.post('/api/jobs', files={'raw': ('DSC_0002.NEF', raw)})
        response.raise_for_status()
        job_id = response.json()['id']
        for _ in range(100):
            job = client.get('/api/jobs/' + job_id).json()
            if job['status'] not in ('queued', 'decoding'): break
            time.sleep(.2)
        assert job['status'] == 'ready', job
        neutral={'strength':0,'use_ai':False,'include_local':False,'overrides':{k:0 for k in ['Exposure2012','Highlights2012','Shadows2012','Whites2012']}}
        checked=client.post(f'/api/jobs/{job_id}/quality/check',json={'state':neutral})
        checked.raise_for_status()
        assert checked.json()['quality_report']['status']=='ok'
        correcting=client.post(f'/api/jobs/{job_id}/quality/correct',json={'state':neutral})
        assert correcting.status_code==202
        for _ in range(100):
            complete=client.get('/api/jobs/'+job_id).json()
            if complete['status']!='correcting':break
            time.sleep(.1)
        assert complete['quality_report']['correction']['changed'] is False and complete.get('error') is None
        assert client.post(f'/api/jobs/{job_id}/refine',json={'instruction':'x'}).status_code==422
        assert client.post(f'/api/jobs/{job_id}/refine/undo',json={}).status_code==400
        body = {'style': 'cinematic', 'mode': 'photo', 'strength': .7, 'name': 'AI RAW Studio 验证',
                'overrides':{'RedHue':18,'BlueSaturation':-12,'ParametricLights':10,'HueAdjustmentGreen':-16,'ColorGradeMidtoneHue':35,'ColorGradeMidtoneSat':8,'ColorGradeMidtoneLum':7,'ColorGradeBlending':70,'PostCropVignetteAmount':-18,'PostCropVignetteStyle':2,'PostCropVignetteFeather':80},
                'white_balance':{'mode':'custom','temperature':6100,'tint':8},
                'curve_overrides':{'blue':[{'x':0,'y':5},{'x':128,'y':140},{'x':255,'y':255}]}}
        assert client.post(f'/api/jobs/{job_id}/preview', json=body).content.startswith(b'\x89PNG')
        frozen=client.post(f'/api/jobs/{job_id}/validation',json=body)
        frozen.raise_for_status();snapshot=frozen.json()
        prefix=f"/api/jobs/{job_id}/validation/{snapshot['id']}"
        reference=client.get(prefix+'/reference');reference.raise_for_status()
        compared=client.post(prefix+'/compare',files={'image':('reference.png',reference.content,'image/png')},params={'acr_version':'test loopback'})
        compared.raise_for_status();assert compared.json()['rmse_255']<.51
        assert client.get(prefix+'/package').content.startswith(b'PK')
        assert client.post(f'/api/jobs/{job_id}/detail',json=body).content.startswith(b'\x89PNG')
        segmentation = client.post(f'/api/jobs/{job_id}/segment', json={})
        segmentation.raise_for_status()
        subject = next(region for region in segmentation.json()['regions'] if region['kind']=='subject')
        changed = client.put(f"/api/jobs/{job_id}/regions/{subject['id']}",json={'adjustments':{'exposure':.5}})
        changed.raise_for_status()
        exported = client.post(f'/api/jobs/{job_id}/export', json=body)
        exported.raise_for_status()
        assert b'Mask/Aggregate' in exported.content and b'Mask/Paint' in exported.content
        from xml.etree import ElementTree as ET
        CRS='http://ns.adobe.com/camera-raw-settings/1.0/'
        RDF='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
        desc=ET.fromstring(exported.content).find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
        assert desc.get(f'{{{CRS}}}RedHue')=='18' and desc.get(f'{{{CRS}}}ParametricLights')=='10'
        assert desc.get(f'{{{CRS}}}WhiteBalance')=='Custom' and desc.get(f'{{{CRS}}}Temperature')=='6100' and desc.get(f'{{{CRS}}}Tint')=='8'
        assert desc.get(f'{{{CRS}}}ColorGradeMidtoneLum')=='7' and desc.get(f'{{{CRS}}}PostCropVignetteAmount')=='-18'
        assert [p.text for p in desc.findall(f'{{{CRS}}}ToneCurvePV2012Blue/{{{RDF}}}Seq/{{{RDF}}}li')]==['0, 5','128, 140','255, 255']
        (root / 'work' / 'ACR_validation.xmp').write_bytes(exported.content)
        bridge=client.get('/api/photoshop');bridge.raise_for_status()
        real_photoshop='not requested'
        if os.getenv('RAW_STUDIO_SMOKE_PHOTOSHOP')=='1':
            assert bridge.json()['available'],bridge.json()
            rendering=client.post(f'/api/jobs/{job_id}/validation/render',json=body)
            rendering.raise_for_status();actual=rendering.json()
            assert actual['photoshop']['status']=='running'
            assert client.delete(f'/api/jobs/{job_id}').status_code==409
            for _ in range(250):
                actual=client.get(f"/api/jobs/{job_id}/validation/{actual['id']}").json()
                if actual['photoshop']['status']!='running':break
                time.sleep(1)
            assert actual['photoshop']['status']=='complete',actual
            assert actual['report']['automation']['verified_mask_nodes']>0
            assert actual['report']['automation']['input_depth']=='BitsPerChannelType.SIXTEEN'
            (root/'work/packaged-photoshop-report.json').write_text(json.dumps(actual['report'],ensure_ascii=False,indent=2),encoding='utf-8')
            real_photoshop='passed'
        print(json.dumps({'photoshop_bridge':bridge.json()['available'],'real_photoshop_render':real_photoshop},ensure_ascii=False))
        print(json.dumps({'packaged_service': 'passed', 'raw_decode': 'passed', 'preview': 'passed', 'local_model': 'passed', 'mask_export': 'passed','color_panels':'passed','refinement_routes':'passed','quality_check_and_correction':'passed','acr_snapshot_loopback':'passed','full_resolution_detail':'passed'}, ensure_ascii=False))
finally:
    child.terminate()
    child.wait(timeout=15)
