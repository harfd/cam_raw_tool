from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET
from defusedxml.ElementTree import parse
from .parameter_engine import validate_parameters, PHOTO_ONLY, CURVE_FIELDS
from .models import RenderRequest

CRS = 'http://ns.adobe.com/camera-raw-settings/1.0/'
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
X = 'adobe:ns:meta/'
ET.register_namespace('x', X)
ET.register_namespace('rdf', RDF)
ET.register_namespace('crs', CRS)

def template_info(path: Path):
    root = parse(path).getroot()
    desc = root.find(f'{{{RDF}}}RDF/{{{RDF}}}Description')
    if desc is None or not desc.get(f'{{{CRS}}}ProcessVersion'):
        raise ValueError('XMP 不包含 Camera Raw 处理版本。')
    return {'version': desc.get(f'{{{CRS}}}Version', '17.3'),
            'process_version': desc.get(f'{{{CRS}}}ProcessVersion'),
            'kind': 'preset' if desc.get(f'{{{CRS}}}PresetType') else 'sidecar'}

def build_xmp(params, name, mode, template, curve=None, regions=None, directory=None, curves=None):
    validate_parameters(params)
    if mode == 'style' and PHOTO_ONLY.intersection(params):
        raise ValueError('通用预设中出现照片专属参数。')
    if mode == 'style' and regions:
        raise ValueError('固定坐标选区只能用于照片专属预设。')
    root = ET.Element(f'{{{X}}}xmpmeta')
    rdf = ET.SubElement(root, f'{{{RDF}}}RDF')
    desc = ET.SubElement(rdf, f'{{{RDF}}}Description', {f'{{{RDF}}}about': ''})
    attrs = {'PresetType': 'Normal', 'UUID': uuid4().hex.upper(), 'SupportsAmount': 'False',
             'SupportsColor': 'True', 'SupportsMonochrome': 'False', 'SupportsHighDynamicRange': 'False',
             'SupportsNormalDynamicRange': 'True', 'SupportsSceneReferred': 'True',
             'SupportsOutputReferred': 'False', 'CameraModelRestriction': '',
             'Version': template['version'], 'ProcessVersion': template['process_version'], 'HasSettings': 'True'}
    attrs.update({k: str(v) for k, v in params.items()})
    for key, value in attrs.items():
        desc.set(f'{{{CRS}}}{key}', value)
    all_curves = dict(curves or {})
    if curve and 'rgb' not in all_curves:
        all_curves['rgb'] = curve
    if all_curves:
        RenderRequest(curve_overrides={k:[{'x':x,'y':y} for x,y in points] for k,points in all_curves.items()})
        desc.set(f'{{{CRS}}}ToneCurveName2012', 'Custom')
        for channel,points in all_curves.items():
            seq = ET.SubElement(ET.SubElement(desc, f'{{{CRS}}}{CURVE_FIELDS[channel]}'), f'{{{RDF}}}Seq')
            for x,y in points:
                ET.SubElement(seq, f'{{{RDF}}}li').text = f'{x}, {y}'
    if regions:
        from .mask_export import append_local_masks
        append_local_masks(desc, regions, directory)
    for key, value in [('Name', name), ('Group', 'AI RAW Studio'), ('Description', '照片专属优化' if mode == 'photo' else '可复用风格预设')]:
        alt = ET.SubElement(ET.SubElement(desc, f'{{{CRS}}}{key}'), f'{{{RDF}}}Alt')
        ET.SubElement(alt, f'{{{RDF}}}li', {'{http://www.w3.org/XML/1998/namespace}lang': 'x-default'}).text = value
    ET.indent(root, space='  ')
    data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    ET.fromstring(data)
    return data
