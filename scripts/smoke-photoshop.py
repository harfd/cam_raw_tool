"""Opt-in real Photoshop/ACR check. Uses disposable copies, never a fake renderer."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['RAW_STUDIO_DATA_DIR'] = str(ROOT / 'work' / ('photoshop-smoke-' + uuid4().hex[:8]))
os.environ['RAW_STUDIO_TOKEN'] = 'local-photoshop-smoke'

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from backend.main import app
from backend.store import JOBS_DIR


def main():
    source = ROOT / 'DSC_0002.NEF'
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    results = {}
    with TestClient(app, headers={'Authorization': 'Bearer local-photoshop-smoke'}) as client:
        conf = client.get('/api/photoshop').json()
        if not conf['available']: raise RuntimeError(conf['message'])
        with source.open('rb') as raw:
            response = client.post('/api/jobs', files={'raw': (source.name, raw)})
        response.raise_for_status();job_id = response.json()['id'];prefix = '/api/jobs/' + job_id
        for _ in range(300):
            job = client.get(prefix).json()
            if job['status'] not in ('queued', 'decoding'): break
            time.sleep(.1)
        assert job['status'] == 'ready', job
        neutral = {'strength': 0, 'use_ai': False, 'include_local': False,
                   'overrides': {name: 0 for name in ('Exposure2012', 'Contrast2012', 'Highlights2012', 'Shadows2012', 'Whites2012', 'Blacks2012')}}

        def run(name, body):
            started = time.monotonic()
            response = client.post(prefix + '/validation/render', json=body)
            response.raise_for_status();snapshot = response.json()
            assert client.delete(prefix).status_code == 409
            for _ in range(500):
                snapshot = client.get(prefix + '/validation/' + snapshot['id']).json()
                if snapshot['photoshop']['status'] != 'running': break
                time.sleep(.5)
            assert snapshot['photoshop']['status'] == 'complete', snapshot['photoshop']
            report = snapshot['report']
            assert report['automation']['engine'] == 'local-photoshop-camera-raw'
            assert report['automation']['camera_profile'] == 'Adobe Standard'
            assert report['automation']['input_depth'] == 'BitsPerChannelType.SIXTEEN'
            again = client.post(prefix + '/validation/render', json=body).json()
            assert again['id'] == snapshot['id'], 'Identical requests should reuse a complete result'
            result_root = JOBS_DIR / job_id / 'validation' / snapshot['id']
            pixels = np.array(Image.open(result_root / 'acr.png')).astype(float)
            results[name] = {'snapshot_id': snapshot['id'], 'seconds': round(time.monotonic()-started, 2),
                             'automation': report['automation'], 'mean_rgb': pixels.mean(axis=(0, 1)).tolist()}
            print(json.dumps({'case': name, **results[name]}, ensure_ascii=False), flush=True)
            return pixels, result_root

        baseline, base_root = run('neutral', neutral)
        brighter, _ = run('exposure', {**neutral, 'overrides': {**neutral['overrides'], 'Exposure2012': .8}})
        assert brighter.mean() > baseline.mean() + 8, 'ACR must actually change pixels when exposure changes'
        complex_body = {**neutral, 'white_balance': {'mode': 'custom', 'temperature': 6100, 'tint': 8},
                        'overrides': {**neutral['overrides'], 'Contrast2012': 11, 'HueAdjustmentGreen': -16,
                                      'ColorGradeMidtoneHue': 35, 'ColorGradeMidtoneSat': 8,
                                      'PostCropVignetteAmount': -18, 'GrainAmount': 12},
                        'curve_overrides': {'blue': [{'x': 0, 'y': 5}, {'x': 128, 'y': 140}, {'x': 255, 'y': 255}]}}
        complex_pixels, _ = run('curves-white-balance-color', complex_body)
        assert np.abs(complex_pixels-baseline).mean() > 2
        changed = client.post(prefix + '/regions', json={'name': '左侧测试', 'bbox': [.05, .1, .4, .8]})
        changed.raise_for_status();region = changed.json()['regions'][-1]
        response = client.put(prefix + '/regions/' + region['id'], json={'adjustments': {'exposure': .8, 'blue': 10}, 'feather': 0})
        response.raise_for_status()
        local, local_root = run('local-mask', {**neutral, 'include_local': True})
        left = np.abs(local[:, :int(local.shape[1]*.35)] - baseline[:, :int(local.shape[1]*.35)]).mean()
        right = np.abs(local[:, int(local.shape[1]*.6):] - baseline[:, int(local.shape[1]*.6):]).mean()
        assert left > 2 and left > right * 2, (left, right)
        results['local-mask']['left_change'] = left;results['local-mask']['right_change'] = right
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original
        summary = {'status': 'passed', 'source_unchanged': True, 'data_dir': os.environ['RAW_STUDIO_DATA_DIR'], 'cases': results}
        out = Path(os.environ['RAW_STUDIO_DATA_DIR']) / 'summary.json'
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Real Photoshop checks passed: ' + str(out), flush=True)


if __name__ == '__main__': main()
