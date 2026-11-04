import argparse
import json
import os
import secrets
import socket
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    token = os.environ.setdefault('RAW_STUDIO_TOKEN', secrets.token_urlsafe(32))
    import uvicorn
    from backend.main import app
    from backend.store import recover_jobs
    recover_jobs()
    from backend.film import recover
    recover()
    from backend.photoshop import recover as recover_photoshop
    recover_photoshop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', args.port))
    sock.listen(128)
    print(json.dumps({'url': f'http://127.0.0.1:{sock.getsockname()[1]}', 'token': token}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])

if __name__ == '__main__':
    main()
