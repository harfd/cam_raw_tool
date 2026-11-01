import os
from pathlib import Path
os.environ['RAW_STUDIO_DATA_DIR'] = str(Path(__file__).resolve().parents[1] / 'work' / 'test-data')
os.environ['RAW_STUDIO_TOKEN'] = 'test-session-token'
