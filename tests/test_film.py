import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError
from backend import film


@pytest.fixture
def setup(tmp_path,monkeypatch):
    job={'id':'a'*32,'regions':[{'id':'b'*32,'enabled':True,'feather':2,'adjustments':{'exposure':.7}}]}
    directory=tmp_path/job['id'];directory.mkdir()
    (directory/'source.NEF').write_bytes(b'original source')
    Image.fromarray(np.full((10,10),127,dtype=np.uint8)).save(directory/('b'*32+'.png'))
    runtime=tmp_path/'runtime';runtime.mkdir();(runtime/'python.exe').touch()
    (runtime/'catalog.json').write_text(json.dumps({'films':[{'id':'kodak_portra_400'}],'papers':[{'id':'kodak_portra_endura'}]}))
    monkeypatch.setattr(film,'JOBS_DIR',tmp_path);monkeypatch.setattr(film,'DATA_DIR',tmp_path)
    monkeypatch.setattr(film,'runtime_dir',lambda:runtime)
    monkeypatch.setattr(film,'_active',None);monkeypatch.setattr(film,'_process',None);monkeypatch.setattr(film,'_cancelled',set())
    queued=[]
    monkeypatch.setattr(film,'_executor',SimpleNamespace(submit=lambda *args:queued.append(args)))
    return job,directory,queued


def test_validation_and_unavailable_catalog(tmp_path,monkeypatch):
    for kwargs in ({'exposure':float('nan')},{'halation':3},{'film':'../source'},{'format':'xmp'},{'unknown':True}):
        with pytest.raises(ValidationError):film.FilmRequest(**kwargs)
    monkeypatch.setattr(film,'runtime_dir',lambda:tmp_path)
    assert not film.catalog()['available']


def test_snapshot_cancel_exclusivity_and_recovery(setup):
    job,directory,queued=setup
    task=film.start(job,film.FilmRequest(include_local_exposure=True))
    request_path=directory/'film'/task['operation']/'request.json'
    snapshot=json.loads(request_path.read_text(encoding='utf-8'))
    assert snapshot['masks'][0]['exposure']==.7
    assert 'decision' not in snapshot and 'api_key' not in snapshot
    Image.fromarray(np.zeros((10,10),dtype=np.uint8)).save(directory/('b'*32+'.png'))
    assert np.array(Image.open(request_path.parent/('b'*32+'.png'))).mean()==127
    with pytest.raises(RuntimeError):film.start(job,film.FilmRequest())
    with pytest.raises(ValueError):film.result_file(job['id'],'../latest','download')
    film.cancel(job['id']);queued[0][0](*queued[0][1:])
    assert film.state(job['id'])['status']=='cancelled' and not film.busy(job['id'])
    next_task=film.start(job,film.FilmRequest())
    film.recover()
    assert film.state(job['id'])['status']=='interrupted'
    assert (directory/'source.NEF').read_bytes()==b'original source'


def test_successful_result_and_failed_worker(setup,monkeypatch):
    job,directory,queued=setup
    def fake_process(args,**kwargs):
        request=json.loads(Path(args[-1]).read_text(encoding='utf-8'));out=Path(request['output'])
        assert args[1:3]==['-I','-u'] and kwargs['creationflags']==0x08000000
        assert not any('TOKEN' in k.upper() or 'API_KEY' in k.upper() for k in kwargs['env'])
        (out/'result.json').write_text(json.dumps({'filename':'film-test.tif','width':10,'height':10,'bit_depth':16}))
        (out/'film-test.tif').write_bytes(b'II*\x00')
        return SimpleNamespace(wait=lambda timeout:0)
    monkeypatch.setattr(film.subprocess,'Popen',fake_process)
    task=film.start(job,film.FilmRequest(format='tiff'));queued[-1][0](*queued[-1][1:])
    assert film.state(job['id'])['status']=='complete'
    assert film.result_file(job['id'],task['operation'],'download').read_bytes()==b'II*\x00'
    monkeypatch.setattr(film.subprocess,'Popen',lambda *a,**kw:SimpleNamespace(wait=lambda timeout:1))
    film.start(job,film.FilmRequest());queued[-1][0](*queued[-1][1:])
    assert film.state(job['id'])['status']=='failed' and not film.busy(job['id'])
    assert film.state(job['id'])['previous']['operation']==task['operation']
    assert film.result_file(job['id'],task['operation'],'download').exists()
