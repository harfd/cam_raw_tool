"""Download the pinned local segmentation model and retain its license."""
import hashlib
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'backend/assets/segformer'
REVISION='6700676d80f989a1e7096fd6d89e88e9b9ca61ce'
SHA256='341333427d74b95391227b7d5935c1854094f7c4b7cc0d144dc6720735dba3bd'
BASE=f'https://huggingface.co/nvidia/segformer-b0-finetuned-ade-512-512/resolve/{REVISION}/'

def main():
    TARGET.mkdir(parents=True,exist_ok=True)
    with httpx.Client(follow_redirects=True,timeout=180) as client:
        for name in ['config.json','preprocessor_config.json','model.onnx']:
            destination=TARGET/name
            if destination.exists() and (name!='model.onnx' or hashlib.sha256(destination.read_bytes()).hexdigest()==SHA256):
                continue
            response=client.get(BASE+name);response.raise_for_status()
            temporary=destination.with_suffix(destination.suffix+'.download')
            temporary.write_bytes(response.content)
            if name=='model.onnx' and hashlib.sha256(response.content).hexdigest()!=SHA256:
                temporary.unlink()
                raise RuntimeError('Model checksum mismatch')
            temporary.replace(destination)
        response=client.get('https://raw.githubusercontent.com/NVlabs/SegFormer/master/LICENSE')
        response.raise_for_status();(TARGET/'LICENSE.txt').write_bytes(response.content)
    (TARGET/'SOURCE.txt').write_text(f'Model: NVIDIA SegFormer B0 / ADE20K\nSource: {BASE}\nONNX SHA256: {SHA256}\nThe model retains the NVIDIA Source Code License for SegFormer.\nResearch and evaluation use only; see LICENSE.txt.\n',encoding='utf-8')
    print('Local model ready; checksum and license retained.')

if __name__=='__main__':main()
