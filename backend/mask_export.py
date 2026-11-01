"""Convert image-space selections to ordinary Camera Raw paint strokes.

Fixed selections are photo-specific. They are never exported in reusable mode.
The raster selection is covered with inscribed circles, not replaced by an AI
subject/sky selector. No Adobe binary semantic-mask cache is required.
"""
import cv2
import numpy as np
from xml.etree import ElementTree as ET
from uuid import uuid4
from .segmentation import load_mask

CRS='http://ns.adobe.com/camera-raw-settings/1.0/'
RDF='http://www.w3.org/1999/02/22-rdf-syntax-ns#'

def circle_cover(mask, max_size=1600):
    h,w=mask.shape
    scale=min(1,max_size/max(h,w))
    width,height=max(1,round(w*scale)),max(1,round(h*scale))
    binary=(cv2.resize(mask,(width,height),interpolation=cv2.INTER_AREA)>=.5).astype(np.uint8)
    remaining=binary.copy()
    distance=cv2.distanceTransform(binary,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
    groups={}
    # Select interior discs first. Distances are measured in pixels so the
    # normalized Y coordinate and brush radius retain the image aspect ratio.
    for radius in [48,24,12,6,3,1]:
        ys,xs=np.where((distance>=radius+.25)&(remaining>0))
        order=np.argsort(distance[ys,xs])[::-1]
        for index in order:
            x,y=int(xs[index]),int(ys[index])
            if not remaining[y,x]: continue
            groups.setdefault(radius,[]).append((x/width,y/height))
            cv2.circle(remaining,(x,y),radius,0,-1)
    # The remaining boundary pixels use tiny independent dabs, with no lines
    # joining unrelated components or islands.
    ys,xs=np.where(remaining>0)
    if len(xs): groups[.5]=list(zip((xs+.5)/width,(ys+.5)/height))
    return [(radius/width,points) for radius,points in groups.items()]

def append_local_masks(desc, regions, directory):
    container=ET.SubElement(ET.SubElement(desc,f'{{{CRS}}}MaskGroupBasedCorrections'),f'{{{RDF}}}Seq')
    for region in regions:
        if not any(region['adjustments'].values()): continue
        mask=load_mask(directory,region,False)
        if not np.any(mask>.5): continue
        correction=ET.SubElement(ET.SubElement(container,f'{{{RDF}}}li'),f'{{{RDF}}}Description')
        attrs={'What':'Correction','CorrectionAmount':'1','CorrectionActive':'true','CorrectionName':region['name'],
               'CorrectionSyncID':uuid4().hex.upper(),'LocalExposure':'0','LocalHue':'0','LocalSaturation':'0',
               'LocalContrast':'0','LocalClarity':'0','LocalSharpness':'0','LocalBrightness':'0',
               'LocalToningHue':'0','LocalToningSaturation':'0','LocalCurveRefineSaturation':'100'}
        for name in ['Exposure2012','Contrast2012','Highlights2012','Shadows2012','Whites2012','Blacks2012','Clarity2012','Dehaze','LuminanceNoise','Moire','Defringe','Temperature','Tint','Texture','Grain']:
            attrs['Local'+name]='0'
        mapping={'exposure':('LocalExposure2012',4),'contrast':('LocalContrast2012',100),
                 'highlights':('LocalHighlights2012',100),'shadows':('LocalShadows2012',100),
                 'whites':('LocalWhites2012',100),'blacks':('LocalBlacks2012',100),
                 'temperature':('LocalTemperature',100),'tint':('LocalTint',100),
                 'saturation':('LocalSaturation',100),'clarity':('LocalClarity2012',100),
                 'texture':('LocalTexture',100),'dehaze':('LocalDehaze',100)}
        for key,(field,divisor) in mapping.items(): attrs[field]=f"{region['adjustments'].get(key,0)/divisor:.6f}"
        for key,value in attrs.items(): correction.set(f'{{{CRS}}}{key}',value)
        blue=region['adjustments'].get('blue',0)
        if blue:
            seq=ET.SubElement(ET.SubElement(correction,f'{{{CRS}}}BlueCurve'),f'{{{RDF}}}Seq')
            for x,y in [(0,0),(128,128+round(blue)),(255,255)]: ET.SubElement(seq,f'{{{RDF}}}li').text=f'{x},{y}'
        masks=ET.SubElement(ET.SubElement(correction,f'{{{CRS}}}CorrectionMasks'),f'{{{RDF}}}Seq')
        aggregate=ET.SubElement(ET.SubElement(masks,f'{{{RDF}}}li'),f'{{{RDF}}}Description')
        for key,value in {'What':'Mask/Aggregate','MaskActive':'true','MaskName':region['name'],
                          'MaskBlendMode':'0','MaskInverted':'false','MaskSyncID':uuid4().hex.upper(),
                          'MaskValue':'1'}.items():
            aggregate.set(f'{{{CRS}}}{key}',value)
        strokes=ET.SubElement(ET.SubElement(aggregate,f'{{{CRS}}}Masks'),f'{{{RDF}}}Seq')
        for radius,points in circle_cover(mask):
            # Every dab is independent. Flow=1 and hard centers prevent a
            # large number of overlapping dabs from changing mask density.
            paint=ET.SubElement(ET.SubElement(strokes,f'{{{RDF}}}li'),f'{{{RDF}}}Description')
            feather=region.get('feather',0)/mask.shape[1]
            outer=radius+feather
            for key,value in {'What':'Mask/Paint','MaskActive':'true','MaskBlendMode':'0','MaskInverted':'false',
                              'MaskSyncID':uuid4().hex.upper(),'MaskValue':'1','Radius':f'{outer:.8f}',
                              'Flow':'1','CenterWeight':f'{radius/outer:.6f}'}.items(): paint.set(f'{{{CRS}}}{key}',value)
            dabs=ET.SubElement(ET.SubElement(paint,f'{{{CRS}}}Dabs'),f'{{{RDF}}}Seq')
            ET.SubElement(dabs,f'{{{RDF}}}li').text='f 1.0000'
            for x,y in points: ET.SubElement(dabs,f'{{{RDF}}}li').text=f'd {x:.7f} {y:.7f}'
