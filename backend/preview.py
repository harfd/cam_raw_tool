import colorsys
import io
import cv2
import numpy as np
from PIL import Image

def local_adjust(rgb, p):
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    lum = linear @ np.array([.2126, .7152, .0722], dtype=np.float32)
    linear *= 2 ** p.get('exposure', 0)
    linear += ((1 - lum) ** 3 * (p.get('shadows', 0) / 100 * .12 + p.get('blacks', 0) / 100 * .04)
               + lum ** 2 * (p.get('highlights', 0) / 100 * .22 + p.get('whites', 0) / 100 * .07))[..., None]
    result = np.where(linear <= .0031308, 12.92 * linear, 1.055 * np.maximum(linear, 0) ** (1 / 2.4) - .055)
    result = (result - .5) * (1 + p.get('contrast', 0) / 130) + .5
    temperature = p.get('temperature', 0) / 100
    tint = p.get('tint', 0) / 100
    result *= np.array([1 + temperature * .18 + tint * .05, 1 - tint * .10, 1 - temperature * .18 + tint * .05])
    gray = result @ np.array([.2126, .7152, .0722])
    result = gray[..., None] + (result - gray[..., None]) * (1 + p.get('saturation', 0) / 100)
    if p.get('blue', 0):
        result[..., 2] = np.interp(result[..., 2], [0,128/255,1], [0,(128+p['blue'])/255,1])
    detail = (p.get('clarity', 0) + p.get('texture', 0) * .5 + p.get('dehaze', 0) * .5) / 100
    if detail:
        result += (result - cv2.GaussianBlur(result, (0,0), 3)) * detail
    return np.clip(result, 0, 1).astype(np.float32)

def calibration_preview(rgb, p):
    # A display-space approximation. Adobe's profile-dependent calibration is proprietary.
    matrix = np.eye(3, dtype=np.float32)
    for channel,name in enumerate(['Red','Green','Blue']):
        sat = p.get(name+'Saturation', 0) / 100 * .35
        matrix[:,channel] += (np.eye(3)[channel] - 1/3) * sat
        hue = p.get(name+'Hue', 0) / 100 * .18
        matrix[(channel+1)%3,channel] += hue
        matrix[(channel+2)%3,channel] -= hue
    result = rgb @ matrix.T
    lum = np.clip(rgb @ np.array([.2126,.7152,.0722]),0,1)
    result += (1-lum)[...,None]**3 * p.get('ShadowTint',0)/100 * np.array([.045,-.09,.045])
    return np.clip(result,0,1).astype(np.float32)

def parametric_preview(rgb, p):
    # Smooth regional bumps reproduce the controls' direction, not Adobe's exact spline.
    knots = [0,p.get('ParametricShadowSplit',25)/100,p.get('ParametricMidtoneSplit',50)/100,p.get('ParametricHighlightSplit',75)/100,1]
    luma = np.clip(rgb @ np.array([.2126,.7152,.0722]),0,1)
    delta = np.zeros_like(luma)
    for index,name in enumerate(['Shadows','Darks','Lights','Highlights']):
        start,end=knots[index:index+2]
        center=(start+end)/2
        width=max((end-start)*1.1,.05)
        weight=np.maximum(0,1-np.abs(luma-center)/width)**2
        delta+=weight*p.get('Parametric'+name,0)/100*.18
    return np.clip(rgb+delta[...,None],0,1).astype(np.float32)

def render(path, p, curve=None, regions=None, directory=None, curves=None, return_array=False,max_dimension=None,source_image=None,region_masks=None):
    image=source_image.copy() if source_image is not None else Image.open(path).convert('RGB')
    if max_dimension:image.thumbnail((max_dimension,max_dimension),Image.Resampling.LANCZOS)
    rgb = np.asarray(image).astype(np.float32) / 255
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    linear *= 2 ** p.get('Exposure2012', 0)
    lum = np.clip(linear @ np.array([.2126, .7152, .0722], dtype=np.float32), 0, 1)
    shadow = (1 - lum) ** 3
    highlight = lum ** 2
    linear += (p.get('Shadows2012', 0) / 100 * .12 * shadow + p.get('Blacks2012', 0) / 100 * .04 * shadow)[..., None]
    linear += (p.get('Highlights2012', 0) / 100 * .22 * highlight + p.get('Whites2012', 0) / 100 * .07 * highlight)[..., None]
    rgb = np.where(linear <= .0031308, 12.92 * linear, 1.055 * np.maximum(linear, 0) ** (1 / 2.4) - .055)
    rgb = (rgb - .5) * (1 + p.get('Contrast2012', 0) / 130) + .5
    rgb = calibration_preview(rgb,p)
    hsv = cv2.cvtColor(np.clip(rgb, 0, 1), cv2.COLOR_RGB2HSV)
    hsv[:, :, 1] *= 1 + p.get('Saturation', 0) / 100 + p.get('Vibrance', 0) / 100 * (1 - hsv[:, :, 1])
    # All color weights use the input hue, avoiding cascading shifts into adjacent colors.
    input_hue=hsv[:,:,0].copy()
    for name, center in [('Red', 0), ('Orange', 30), ('Yellow', 60), ('Green', 120), ('Aqua', 180), ('Blue', 240), ('Purple', 275), ('Magenta', 310)]:
        dist = np.abs((input_hue - center + 180) % 360 - 180)
        weight = np.maximum(0, 1 - dist / 40)
        hsv[:, :, 0] += weight * p.get('HueAdjustment' + name, 0) * .25
        hsv[:, :, 1] *= 1 + weight * p.get('SaturationAdjustment' + name, 0) / 100
        hsv[:, :, 2] += weight * p.get('LuminanceAdjustment' + name, 0) / 100 * .15
    hsv[:, :, 0] %= 360
    hsv[:, :, 1:] = np.clip(hsv[:, :, 1:], 0, 1)
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    rgb=parametric_preview(rgb,p)
    all_curves=dict(curves or {})
    if curve and 'rgb' not in all_curves: all_curves['rgb']=curve
    if all_curves.get('rgb'):
        points=all_curves['rgb']
        rgb=np.interp(rgb,[x/255 for x,y in points],[y/255 for x,y in points]).astype(np.float32)
    for index,channel in enumerate(['red','green','blue']):
        if all_curves.get(channel):
            points=all_curves[channel]
            rgb[...,index]=np.interp(rgb[...,index],[x/255 for x,y in points],[y/255 for x,y in points])
    for band, weight in [('Shadow', shadow), ('Highlight', highlight)]:
        color = np.array(colorsys.hsv_to_rgb(p.get(f'SplitToning{band}Hue', 0) / 360, 1, 1)) - .5
        rgb += weight[..., None] * color * p.get(f'SplitToning{band}Saturation', 0) / 100 * .25
    if p.get('ColorGradeGlobalSat', 0):
        color = np.array(colorsys.hsv_to_rgb(p.get('ColorGradeGlobalHue', 0) / 360, 1, 1)) - .5
        rgb += color * p['ColorGradeGlobalSat'] / 100 * .2
    detail = (p.get('Clarity2012', 0) + p.get('Texture', 0) * .5) / 100
    if detail:
        rgb += (rgb - cv2.GaussianBlur(rgb, (0, 0), 2)) * detail
    grain = p.get('GrainAmount', 0)
    if grain:
        rgb += np.random.default_rng(42).normal(0, grain / 100 * .025, rgb.shape[:2])[..., None]
    if regions:
        from .segmentation import load_mask
        rgb = np.clip(rgb, 0, 1)
        for region in regions:
            mask=region_masks[region['id']] if region_masks is not None else load_mask(directory, region)
            if mask.shape!=rgb.shape[:2]:mask=cv2.resize(mask,(rgb.shape[1],rgb.shape[0]),interpolation=cv2.INTER_AREA)
            weight = mask[..., None]
            corrected = local_adjust(rgb, region['adjustments'])
            rgb = rgb * (1 - weight) + corrected * weight
    if return_array:
        return np.clip(rgb,0,1).astype(np.float32)
    output = io.BytesIO()
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(output, format='JPEG', quality=92)
    return output.getvalue()
