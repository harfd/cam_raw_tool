"""Local Photoshop COM bridge. Only private RAW copies and owned documents are edited."""
import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from . import acr_validation
from .store import JOBS_DIR
from .xmp import CRS, RDF

_lock = threading.RLock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='photoshop-worker')
_active = None
TIMEOUT = 240


def catalog():
    if os.name != 'nt':
        return {'available': False, 'message': 'Photoshop 联动需要 Windows 桌面版 Photoshop 和 Camera Raw。'}
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'Photoshop.Application\CLSID') as key:
            clsid = winreg.QueryValue(key, None)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, 'CLSID\\' + clsid + r'\LocalServer32') as key:
            command = winreg.QueryValue(key, None).strip()
        match = re.match(r'^"([^"]+\.exe)"|^(.+?\.exe)(?:\s|$)', command, re.I)
        path = Path(os.path.expandvars(next(g for g in match.groups() if g))) if match else None
        if not path or not path.is_file():
            raise OSError('Photoshop executable is missing')
        return {'available': True, 'message': '已找到 Photoshop，可自动生成 ACR 实际预览。', 'path': str(path)}
    except OSError:
        return {'available': False, 'message': '未找到可用的 Photoshop 接口。请安装或修复桌面版 Photoshop，并确保已安装 Camera Raw。'}


def _write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 9: raise
            time.sleep(.02)


def state(root):
    path = root / 'photoshop.json'
    return json.loads(path.read_text('utf-8')) if path.exists() else None


def busy(job_id=None):
    with _lock:
        return bool(_active and (job_id is None or _active[0] == job_id))


def sidecar(source, destination):
    """A preset becomes complete private RAW settings, with a stable comparison baseline."""
    tree = ET.parse(source)
    desc = tree.getroot().find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
    if desc is None:
        raise ValueError('对照 XMP 无效。')
    for key in list(desc.attrib):
        name = key.removeprefix('{' + CRS + '}')
        if name in {'PresetType', 'UUID', 'CameraModelRestriction'} or name.startswith('Supports'):
            del desc.attrib[key]
    for child in list(desc):
        if child.tag in {f'{{{CRS}}}{name}' for name in ('Name', 'Group', 'Description')}:
            desc.remove(child)
    defaults = {'CameraProfile': 'Adobe Standard', 'WhiteBalance': 'As Shot',
                'AutoTone': 'False', 'AutoExposure': 'False', 'AutoWhiteVersion': '0',
                'HasCrop': 'False', 'CropAngle': '0', 'LensProfileEnable': '0',
                'LensManualDistortionAmount': '0', 'PerspectiveUpright': '0',
                'PerspectiveVertical': '0', 'PerspectiveHorizontal': '0', 'PerspectiveRotate': '0',
                'PerspectiveScale': '100', 'PerspectiveAspect': '0', 'PerspectiveX': '0', 'PerspectiveY': '0'}
    for key, value in defaults.items():
        if key == 'WhiteBalance' and desc.get(f'{{{CRS}}}{key}'):
            continue
        desc.set(f'{{{CRS}}}{key}', value)
    tree.write(destination, encoding='utf-8', xml_declaration=True)


def script(root):
    # ASCII JSON quoting preserves Windows paths, non-Latin names and quotes in ExtendScript.
    config = {'raw': str(root / 'adobe' / 'ACR-check.NEF'),
              'output': str(root / 'adobe' / 'rendered.tif'),
              'result': str(root / 'adobe' / 'result.json'),
              'metadata': str(root / 'adobe' / 'applied.xmp')}
    return 'var RAW_STUDIO = ' + json.dumps(config, ensure_ascii=True) + ';\n' + JSX


# No UI input, no global presets installation and no changes to user's open documents.
# COM's DoJavaScript executes inside Photoshop. Restore app state even when RAW opening fails.
JSX = r'''
(function () {
    function quote(s) { return '"' + String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\r/g, '\\r').replace(/\n/g, '\\n').replace(/\t/g, '\\t').replace(/[\x00-\x1f]/g, function(c) {return '\\u' + ('0000' + c.charCodeAt(0).toString(16)).slice(-4);}) + '"'; }
    function json(v) {
        if (v === null || v === undefined) return 'null';
        if (typeof v === 'string') return quote(v);
        if (typeof v === 'number' || typeof v === 'boolean') return String(v);
        var items = [], k;
        for (k in v) if (v.hasOwnProperty(k)) items.push(quote(k) + ':' + json(v[k]));
        return '{' + items.join(',') + '}';
    }
    function write(path, text) { var f = new File(path); f.encoding = 'UTF-8'; if (!f.open('w')) throw new Error('Cannot write result'); f.write(text); f.close(); }
    var doc = null, previous = null, dialogs = app.displayDialogs, result = {}, originalCount = app.documents.length;
    if (originalCount) previous = app.activeDocument;
    try {
        app.displayDialogs = DialogModes.NO;
        // SELECTEDIMAGE retains the complete same-name sidecar, including modern curves
        // and brush masks. Only output color/depth are specified through open options.
        var rawOptions = new CameraRAWOpenOptions();
        rawOptions.settings = CameraRAWSettingsType.SELECTEDIMAGE;
        rawOptions.bitsPerChannel = BitsPerChannelType.SIXTEEN;
        rawOptions.colorSpace = ColorSpaceType.SRGB;
        doc = app.open(new File(RAW_STUDIO.raw), rawOptions);
        if (!doc || app.documents.length !== originalCount + 1) throw new Error('RAW did not open as a new document');
        var metadata = doc.xmpMetadata.rawData;
        write(RAW_STUDIO.metadata, metadata);
        var width = doc.width.as('px'), height = doc.height.as('px'), inputDepth = String(doc.bitsPerChannel);
        if (doc.bitsPerChannel !== BitsPerChannelType.SIXTEEN) throw new Error('Camera Raw did not open the image in 16-bit mode');
        if (doc.mode !== DocumentMode.RGB) doc.changeMode(ChangeMode.RGB);
        doc.convertProfile('sRGB IEC61966-2.1', Intent.RELATIVECOLORIMETRIC, true, false);
        doc.bitsPerChannel = BitsPerChannelType.SIXTEEN;
        doc.flatten();
        var options = new TiffSaveOptions();
        options.embedColorProfile = true; options.layers = false;
        options.imageCompression = TIFFEncoding.TIFFLZW;
        doc.saveAs(new File(RAW_STUDIO.output), options, true, Extension.LOWERCASE);
        var plugin = /Camera Raw[^\r\n]*/i.exec(app.systemInformation);
        result = {ok:true, photoshop_version:app.version, width:width, height:height, document_profile:doc.colorProfileName, input_depth:inputDepth, camera_raw_plugin:plugin ? plugin[0] : ''};
    } catch (error) {
        result = {ok:false, error:String(error.message || error), number:error.number || 0};
    } finally {
        if (doc) {try {doc.close(SaveOptions.DONOTSAVECHANGES);} catch (closeError) {result = {ok:false,error:'Could not close the temporary RAW document'};}}
        if (previous) {try {app.activeDocument = previous;} catch (ignore) {}}
        app.displayDialogs = dialogs;
    }
    write(RAW_STUDIO.result, json(result));
    return json(result);
}());
'''


POWERSHELL = r'''
$ErrorActionPreference = 'Stop'
$renderMutex = New-Object System.Threading.Mutex($false, 'Local\AI_RAW_Studio_Photoshop_Render')
$ownsMutex = $false
try {
    try { $ownsMutex = $renderMutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) { throw 'Another AI RAW Studio window is using Photoshop. Please wait and retry.' }
    $psApplication = New-Object -ComObject Photoshop.Application
    $jsxSource = [IO.File]::ReadAllText($env:RAW_STUDIO_PS_SCRIPT, [Text.Encoding]::UTF8)
    $null = $psApplication.DoJavaScript($jsxSource)
} catch {
    $failure = @{ok=$false; error=$_.Exception.Message; code='com'} | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($env:RAW_STUDIO_PS_RESULT, $failure, (New-Object Text.UTF8Encoding($false)))
    exit 1
} finally {
    if ($null -ne $psApplication) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($psApplication) }
    if ($ownsMutex) { $renderMutex.ReleaseMutex() }
    $renderMutex.Dispose()
}
'''


def invoke(root):
    adobe = root / 'adobe'
    jsx = adobe / 'render.jsx'
    jsx.write_text(script(root), encoding='utf-8')
    encoded = base64.b64encode(POWERSHELL.encode('utf-16-le')).decode('ascii')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        env = {key: value for key, value in os.environ.items() if not any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'SECRET'))}
        env.update(RAW_STUDIO_PS_SCRIPT=str(jsx), RAW_STUDIO_PS_RESULT=str(adobe / 'result.json'))
        child = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-STA', '-EncodedCommand', encoded],
                               env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=TIMEOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise ValueError('Photoshop 响应超时。请检查它是否停在登录或其他对话框；临时文档可能仍在处理，请待 Photoshop 空闲后重试。') from None
    result_path = adobe / 'result.json'
    if not result_path.is_file():
        raise ValueError('Photoshop 未返回结果，请确认它可以正常启动并打开 RAW。')
    result = json.loads(result_path.read_text('utf-8-sig'))
    if child.returncode or not result.get('ok'):
        raise ValueError('Photoshop 渲染失败，请确认没有打开的对话框、Camera Raw 已安装且支持此原片。详情：' + str(result.get('error', '未返回成片'))[:400])
    return result


def verify(root, result):
    """Read Photoshop's document metadata; reject an ignored/old sidecar before publishing."""
    from defusedxml.ElementTree import parse
    expected = parse(root / 'adobe' / 'ACR-check.xmp').getroot().find(f'.//{{{RDF}}}Description')
    actual_root = parse(root / 'adobe' / 'applied.xmp').getroot()
    actual = {}
    for desc in actual_root.iter(f'{{{RDF}}}Description'):
        actual.update(desc.attrib)
        for child in desc:
            if child.text and not len(child): actual[child.tag] = child.text
    from .parameter_engine import RANGES, CURVE_FIELDS
    checked = []
    inactive = set()
    if float(expected.get(f'{{{CRS}}}GrainAmount', '0')) == 0: inactive.update(('GrainSize', 'GrainFrequency'))
    if float(expected.get(f'{{{CRS}}}PostCropVignetteAmount', '0')) == 0:
        inactive.update(name for name in RANGES if name.startswith('PostCropVignette') and name != 'PostCropVignetteAmount')
    for name in [*RANGES, 'WhiteBalance', 'CameraProfile', 'ProcessVersion']:
        key = f'{{{CRS}}}{name}'
        value = expected.get(key)
        if value is None: continue
        found = actual.get(key)
        if name in inactive and found is None: continue
        if found is None:
            raise ValueError(f'Photoshop 未回传 {name} 设置，无法确认 ACR 已读取当前方案。')
        try: matches = abs(float(found) - float(value)) < .001
        except ValueError: matches = found == value
        if not matches:
            raise ValueError(f'ACR 读取的 {name} 与当前方案不同，未将此结果用于对照。')
        checked.append(name)
    def points(tree, name):
        element = tree.find(f'.//{{{CRS}}}{name}/{{{RDF}}}Seq')
        return [tuple(float(n) for n in item.text.split(',')) for item in element] if element is not None else None
    for name in CURVE_FIELDS.values():
        target = points(expected, name)
        if target is not None:
            if target != points(actual_root, name): raise ValueError(f'ACR 读取的 {name} 曲线与当前方案不同。')
            checked.append(name)
    def properties(node):
        fields = dict(node.attrib)
        for child in node:
            if child.text and not len(child): fields[child.tag] = child.text.strip()
        return {key.removeprefix('{' + CRS + '}'): value for key, value in fields.items() if key.startswith('{' + CRS + '}')}
    def masks(tree):
        group = tree.find(f'.//{{{CRS}}}MaskGroupBasedCorrections')
        result = {}
        if group is not None:
            for node in group.iter():
                fields = properties(node)
                identifier = fields.get('CorrectionSyncID') or fields.get('MaskSyncID')
                if identifier: result[identifier] = (node, fields)
        return result
    expected_masks, actual_masks = masks(expected), masks(actual_root)
    for identifier, (node, fields) in expected_masks.items():
        if identifier not in actual_masks: raise ValueError('ACR 未回传当前局部蒙版，未将此结果用于对照。')
        actual_node, applied = actual_masks[identifier]
        for name, value in fields.items():
            if not (name == 'What' or name in {'Radius', 'Flow', 'CenterWeight'} or (name.startswith('Local') and float(value) != 0)):
                continue
            found = applied.get(name)
            try: matches = found is not None and abs(float(found) - float(value)) < .000002
            except ValueError: matches = found == value
            if not matches: raise ValueError(f'ACR 回读的局部设置 {name} 与当前方案不同。')
        target_blue = points(node, 'BlueCurve')
        if target_blue is not None and target_blue != points(actual_node, 'BlueCurve'):
            raise ValueError('ACR 回读的局部蓝色曲线与当前方案不同。')
        def dabs(element):
            seq = element.find(f'{{{CRS}}}Dabs/{{{RDF}}}Seq')
            return [tuple(float(v) for v in item.text.split()[1:]) for item in seq if item.text.startswith('d ')] if seq is not None else []
        wanted, received = dabs(node), dabs(actual_node)
        if len(wanted) != len(received) or any(len(a) != len(b) or any(abs(x-y) > .000002 for x,y in zip(a,b)) for a,b in zip(wanted,received)):
            raise ValueError('ACR 回读的蒙版笔刷位置与当前方案不同。')
    snapshot = json.loads((root / 'snapshot.json').read_text('utf-8'))
    width, height = snapshot['reference_size']
    if result['width'] < width or result['height'] < height or abs((result['width']/result['height'])/(width/height)-1) > .005:
        raise ValueError('Photoshop 输出画幅或尺寸不符，请在 Camera Raw 工作流程中恢复原始尺寸并关闭裁切。')
    plugin_version = re.search(r'Camera Raw\s+(\d+(?:\.\d+)+)', result.get('camera_raw_plugin', ''))
    return {'acr_version': plugin_version.group(1) if plugin_version else '',
            'settings_version': actual.get(f'{{{CRS}}}Version', ''),
            'camera_profile': actual.get(f'{{{CRS}}}CameraProfile', ''), 'verified_fields': checked,
            'verified_mask_nodes': len(expected_masks)}


def start(job_id, record):
    global _active
    with _lock:
        if _active:
            raise RuntimeError('Photoshop 正在生成另一份预览，请等待完成后重试。')
        conf = catalog()
        if not conf['available']: raise ValueError(conf['message'])
        root = JOBS_DIR / job_id / 'validation' / record['id']
        initial = {'status': 'running', 'bridge_version': 1, 'stage': '正在启动 Photoshop 并读取当前方案…',
                   'snapshot_id': record['id'], 'started_at': datetime.now(timezone.utc).isoformat()}
        _write(root / 'photoshop.json', initial)
        _active = (job_id, record['id'])
        _executor.submit(_run, job_id, root, initial)
        return initial


def _run(job_id, root, initial):
    global _active
    try:
        adobe = root / 'adobe'; adobe.mkdir()
        shutil.copy2(JOBS_DIR / job_id / 'source.NEF', adobe / 'ACR-check.NEF')
        sidecar(root / 'ACR-check.xmp', adobe / 'ACR-check.xmp')
        result = invoke(root)
        metadata = verify(root, result)
        _write(root / 'photoshop.json', {**initial, 'stage': '正在读取 ACR 成片并计算差异…'})
        report = acr_validation.compare(root, (adobe / 'rendered.tif').read_bytes(),
                                        acr_version=metadata['acr_version'], camera_profile=metadata['camera_profile'],
                                        max_bytes=512*1024*1024)
        report['automation'] = {**result, **metadata, 'engine': 'local-photoshop-camera-raw',
                                'settings_source': 'private-raw-sidecar', 'output': 'sRGB TIFF',
                                'white_balance_baseline': '拍摄设置（保持当前模式使用原片副本的拍摄白平衡）'}
        report['limits'] = '由本机 Photoshop 渲染同一原片副本，已回读核对参数、曲线及已导出的局部蒙版。差异还包含两套引擎的相机色彩、基础曲线、解码与缩放差异；数值不代表审美评分。正偏差代表 ACR 更亮／该通道更多。'
        _write(root / 'report.json', report)
        (adobe / 'rendered.tif').unlink()
        _write(root / 'photoshop.json', {**initial, 'status': 'complete', 'stage': 'ACR 实际预览已完成',
                                       'finished_at': datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        _write(root / 'photoshop.json', {**initial, 'status': 'failed', 'stage': 'ACR 预览未完成',
                                       'error': str(exc)[:600], 'finished_at': datetime.now(timezone.utc).isoformat()})
    finally:
        with _lock: _active = None


def recover():
    for path in JOBS_DIR.glob('*/validation/*/photoshop.json'):
        previous = state(path.parent)
        if previous and previous['status'] == 'running':
            _write(path, {**previous, 'status': 'failed', 'stage': '上次任务中断',
                          'error': '软件上次运行被中断。请确认 Photoshop 已空闲，再重新生成 ACR 预览。'})
