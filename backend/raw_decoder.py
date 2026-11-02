import cv2
import exifread
import numpy as np
import rawpy
from fractions import Fraction
from PIL import Image, ImageCms
import threading

_preview_lock = threading.RLock()
SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()

def decode_rgb(path, half_size=True):
    with rawpy.imread(str(path)) as raw:
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, auto_bright_thr=.005,
                               half_size=half_size, output_color=rawpy.ColorSpace.sRGB, gamma=(1,1), output_bps=16)
    return encode_srgb16(rgb)


def encode_srgb16(rgb):
    # LibRaw defaults to a BT.709 transfer curve. Encode explicit sRGB before
    # attaching an sRGB ICC or applying sRGB inverse transfer in the renderer.
    linear=rgb.astype(np.float32)/65535
    encoded=np.where(linear<=.0031308,12.92*linear,1.055*np.maximum(linear,0)**(1/2.4)-.055)
    return np.rint(np.clip(encoded,0,1)*65535).astype(np.uint16)


def ensure_precision(directory, full=False):
    """Lazy cache for existing jobs; never changes saved plans or masks."""
    name = "full-srgb-v2.npy" if full else "preview-srgb-v2.npy"
    target = directory / name
    with _preview_lock:
        if not target.exists():
            rgb = decode_rgb(directory / "source.NEF", half_size=not full)
            if not full:
                h,w = rgb.shape[:2]; scale = min(1,1600/max(h,w))
                rgb = cv2.resize(rgb.astype(np.float32)/65535, (round(w*scale),round(h*scale)), interpolation=cv2.INTER_AREA)
            temporary = target.with_suffix(".tmp")
            with temporary.open("wb") as stream: np.save(stream,rgb,allow_pickle=False)
            temporary.replace(target)
    return target


def decode(path, out_dir):
    with open(path, 'rb') as stream:
        tags = exifread.process_file(stream, details=False)
    wanted = {'camera': 'Image Model', 'make': 'Image Make', 'iso': 'EXIF ISOSpeedRatings',
              'shutter': 'EXIF ExposureTime', 'aperture': 'EXIF FNumber', 'focal_length': 'EXIF FocalLength', 'lens': 'EXIF LensModel'}
    metadata = {key: str(tags[tag]) for key, tag in wanted.items() if tag in tags}
    for key in ['aperture', 'focal_length']:
        if key in metadata:
            try:
                metadata[key] = f'{float(Fraction(metadata[key])):g}'
            except (ValueError, ZeroDivisionError):
                pass
    with rawpy.imread(str(path)) as raw:
        sensor = raw.raw_image_visible[::7, ::7].astype(np.float32)
        colors = raw.raw_colors_visible[::7, ::7]
        black = np.array(raw.black_level_per_channel, dtype=np.float32)
        white = np.array(raw.camera_white_level_per_channel or [raw.white_level] * 4, dtype=np.float32)
        white = np.where(white > black, white, raw.white_level)
        normalized = np.clip((sensor - black[colors]) / np.maximum(white[colors] - black[colors], 1), 0, 1)
        sensor_metrics = {
            'saturated_fraction': float(np.mean(normalized >= .995)),
            'near_black_fraction': float(np.mean(normalized <= .002)),
            'black_levels': black.tolist(), 'white_levels': white.tolist(),
            'camera_white_balance': list(raw.camera_whitebalance),
            'channel_saturation': {str(c): float(np.mean(normalized[colors == c] >= .995)) for c in np.unique(colors)},
        }
        metadata.update(width=raw.sizes.width, height=raw.sizes.height)
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, auto_bright_thr=.005, half_size=True,
                              output_color=rawpy.ColorSpace.sRGB, gamma=(1,1), output_bps=16)
    rgb=encode_srgb16(rgb)
    h,w = rgb.shape[:2]; scale = min(1,1600/max(h,w))
    arr = cv2.resize(rgb.astype(np.float32)/65535,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA)
    with (out_dir / 'preview-srgb.tmp').open('wb') as stream: np.save(stream,arr,allow_pickle=False)
    (out_dir / 'preview-srgb.tmp').replace(out_dir / 'preview-srgb-v2.npy')
    image = Image.fromarray(np.rint(np.clip(arr,0,1)*255).astype(np.uint8))
    image.save(out_dir / 'original.jpg', quality=92,icc_profile=SRGB_ICC)
    image.save(out_dir / 'original.png',icc_profile=SRGB_ICC)
    preview = image.copy()
    preview.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    preview.save(out_dir / 'ai.jpg', quality=85)
    linear = np.where(arr <= .04045, arr / 12.92, ((arr + .055) / 1.055) ** 2.4)
    lum = linear @ np.array([.2126, .7152, .0722], dtype=np.float32)
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2HSV)
    edges = cv2.Canny(gray, 70, 160) / 255
    ys, xs = np.mgrid[:edges.shape[0], :edges.shape[1]]
    total = edges.sum()
    balance = [float((xs * edges).sum() / max(total, 1) / edges.shape[1]),
               float((ys * edges).sum() / max(total, 1) / edges.shape[0])]
    metrics = {
        'preview_version': 3,
        'iso': int(str(metadata.get('iso', '0'))) if str(metadata.get('iso', '0')).isdigit() else 0,
        'sensor': sensor_metrics,
        'preview': {
            'median_luminance': float(np.median(lum)),
            'shadow_fraction': float(np.mean(lum < .025)),
            'highlight_fraction': float(np.mean(lum > .9)),
            'luminance_percentiles': np.percentile(lum, [1, 5, 50, 95, 99]).tolist(),
            'mean_saturation': float(hsv[:, :, 1].mean() / 255),
            'edge_centroid': balance,
            'histogram': [np.histogram(np.asarray(image)[:, :, i], bins=64, range=(0, 256))[0].tolist() for i in range(3)],
        },
    }
    warnings = ['预览由 LibRaw 解码，色彩、曲线和局部对比度与 Camera Raw 存在差异。',
                '边缘重心只描述画面结构，不代表主体位置或构图评分。']
    if sensor_metrics['saturated_fraction'] > .001:
        warnings.append('检测到接近传感器白电平的采样点；已饱和的细节可能无法恢复。')
    return metadata, metrics, warnings
