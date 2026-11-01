import json
import os
from urllib.parse import urlparse
import keyring
from .store import DATA_DIR
from .models import SettingsInput

SERVICE = 'AI RAW Studio / DeepSeek'
ACCOUNT = 'api-key'
_session_key = ''
_path = DATA_DIR / 'settings.json'

def config():
    defaults = {'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash'}
    if _path.exists():
        defaults.update(json.loads(_path.read_text('utf-8')))
    return defaults

def api_key():
    if _session_key:
        return _session_key
    if os.getenv('DEEPSEEK_API_KEY'):
        return os.environ['DEEPSEEK_API_KEY']
    try:
        return keyring.get_password(SERVICE, ACCOUNT) or ''
    except keyring.errors.KeyringError:
        return ''

def public_config():
    return {**config(), 'has_key': bool(api_key())}

def update_settings(settings: SettingsInput):
    global _session_key
    url = urlparse(settings.base_url)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('服务地址必须是 HTTPS 地址，且不能包含账号、查询参数或片段。')
    old = config()
    key = settings.api_key.get_secret_value().strip() if settings.api_key is not None else ''
    if '\n' in key or '\r' in key or len(key) > 1000:
        raise ValueError('API Key 格式不正确。')
    if settings.clear_key or settings.api_key is not None or old['base_url'] != settings.base_url.rstrip('/'):
        try:
            keyring.delete_password(SERVICE, ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass
        _session_key = ''
    if settings.api_key is not None:
        if settings.remember_key and key:
            keyring.set_password(SERVICE, ACCOUNT, key)
        _session_key = key
    _path.write_text(json.dumps({'base_url': settings.base_url.rstrip('/'), 'model': settings.model}, ensure_ascii=False), 'utf-8')
    return public_config()
