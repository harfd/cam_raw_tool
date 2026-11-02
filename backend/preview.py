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

def white_balance_preview(linear,p,white_balance=None):
    if 'Temperature' not in p:return linear
    reference=(white_balance or {}).get('reference',{'temperature':5500,'tint':0})
    shift=1e6/reference['temperature']-1e6/p['Temperature']
    tint=(p.get('Tint',0)-reference.get('tint',0))/150
    gain=np.exp(np.array([shift*.004+tint*.12,-tint*.24,-shift*.004+tint*.12],np.float32))
    return linear*gain

def grading_preview(rgb,p):
    lum=np.clip(rgb@np.array([.2126,.7152,.0722],np.float32),0,1)
    tone=np.clip(lum+p.get('SplitToningBalance',0)/100*.25,0,1)
    sigma=.15+.35*p.get('ColorGradeBlending',50)/100
    weights=np.stack([np.exp(-((tone-center)/sigma)**2/2) for center in [0,.5,1]],axis=-1)
    weights/=np.maximum(weights.sum(axis=-1,keepdims=True),1e-6)
    result=rgb.copy()
    for index,band in enumerate(['Shadow','Midtone','Highlight']):
        hue=p.get('ColorGradeMidtoneHue',0) if band=='Midtone' else p.get(f'SplitToning{band}Hue',0)
        saturation=p.get('ColorGradeMidtoneSat',0) if band=='Midtone' else p.get(f'SplitToning{band}Saturation',0)
        color=np.array(colorsys.hsv_to_rgb(hue/360,1,1),np.float32)-.5
        result+=weights[...,index,None]*(color*saturation/100*.25+p.get('ColorGrade'+band+'Lum',0)/100*.18)
    color=np.array(colorsys.hsv_to_rgb(p.get('ColorGradeGlobalHue',0)/360,1,1),np.float32)-.5
    result+=color*p.get('ColorGradeGlobalSat',0)/100*.2+p.get('ColorGradeGlobalLum',0)/100*.18
    return result

def vignette_preview(rgb,p,frame=None):
    amount=p.get('PostCropVignetteAmount',0)/100
    if not amount:return rgb
    h,w=rgb.shape[:2];y,x=np.mgrid[:h,:w].astype(np.float32)
    if frame is not None:
        fw,fh,ox,oy=frame; x+=ox; y+=oy; w,h=fw,fh
    roundness=p.get('PostCropVignetteRoundness',0)/100
    rx=w/2;ry=h/2
    if roundness>=0:
        circle=min(w,h)/2;rx=rx*(1-roundness)+circle*roundness;ry=ry*(1-roundness)+circle*roundness
    else:rx*=1-roundness*.35;ry*=1+roundness*.35
    radius=np.sqrt(((x-(w-1)/2)/rx)**2+((y-(h-1)/2)/ry)**2)
    start=.15+.65*p.get('PostCropVignetteMidpoint',50)/100
    width=.015+.7*p.get('PostCropVignetteFeather',50)/100
    mask=np.clip((radius-start)/width,0,1);mask=mask*mask*(3-2*mask)
    style=p.get('PostCropVignetteStyle',1)
    if style==3:
        blend=mask[...,None]*abs(amount)*.8
        return rgb*(1-blend)+(1 if amount>0 else 0)*blend
    lum=np.clip(rgb@np.array([.2126,.7152,.0722],np.float32),0,1)
    if amount<0:
        protect=p.get('PostCropVignetteHighlightContrast',0)/100
        gain=2**(amount*(2 if style==1 else 1.5)*mask*(1-protect*lum**2))
        return rgb*gain[...,None]
    return 1-(1-rgb)*2**(-amount*1.4*mask[...,None])

def render(path, p, curve=None, regions=None, directory=None, curves=None, return_array=False,max_dimension=None,source_image=None,region_masks=None,white_balance=None,frame=None):
    rgb = load_source(path,max_dimension) if source_image is None else as_float(source_image,max_dimension)
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    linear=white_balance_preview(linear,p,white_balance)
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
    rgb=grading_preview(rgb,p)
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
    rgb=vignette_preview(rgb,p,frame)
    if return_array:
        return np.clip(rgb,0,1).astype(np.float32)
    output = io.BytesIO()
    from .raw_decoder import SRGB_ICC
    Image.fromarray(np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(output, format='PNG',icc_profile=SRGB_ICC)
    return output.getvalue()


def as_float(image,max_dimension=None):
    arr=np.asarray(image)
    if np.issubdtype(arr.dtype,np.integer):
        arr=arr.astype(np.float32)/np.iinfo(arr.dtype).max
    else:arr=arr.astype(np.float32,copy=True)
    h,w=arr.shape[:2]
    if max_dimension and max(h,w)>max_dimension:
        scale=max_dimension/max(h,w)
        arr=cv2.resize(arr,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA)
    return arr


def load_source(path,max_dimension=None):
    from pathlib import Path
    path=Path(path);cache=path.parent/'preview-srgb-v2.npy'
    if path.name=='original.jpg' and cache.exists():
        return as_float(np.load(cache,allow_pickle=False,mmap_mode='r'),max_dimension)
    with Image.open(path) as image:return as_float(image.convert('RGB'),max_dimension)


def detail(directory,recipe,regions,x,y,size=640):
    from .raw_decoder import ensure_precision
    from .segmentation import load_mask
    full=np.load(ensure_precision(directory,full=True),mmap_mode='r',allow_pickle=False)
    h,w=full.shape[:2];size=min(size,w,h)
    left=max(0,min(w-size,round(x*w-size/2)));top=max(0,min(h-size,round(y*h-size/2)))
    # Halo for local contrast filters; vignette keeps original image coordinates.
    l=max(0,left-64);t=max(0,top-64);r=min(w,left+size+64);b=min(h,top+size+64)
    masks={}
    for region in regions:
        mask=load_mask(directory,region)
        # Remap only the requested patch rather than allocate a full-resolution mask.
        yy,xx=np.mgrid[t:b,l:r].astype(np.float32)
        masks[region['id']]=cv2.remap(mask,(xx+.5)*mask.shape[1]/w-.5,(yy+.5)*mask.shape[0]/h-.5,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
    rgb=render(directory/'original.jpg',recipe['parameters'],recipe['curve'],regions,directory,
               curves=recipe['curves'],white_balance=recipe['white_balance'],source_image=full[t:b,l:r],
               region_masks=masks,return_array=True,frame=(w,h,l,t))
    rgb=rgb[top-t:top-t+size,left-l:left-l+size]
    output=io.BytesIO()
    from .raw_decoder import SRGB_ICC
    Image.fromarray(np.rint(rgb*255).astype(np.uint8)).save(output,format='PNG',icc_profile=SRGB_ICC)
    return output.getvalue()
