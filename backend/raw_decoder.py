import cv2
import exifread
import numpy as np
import rawpy
from fractions import Fraction
from PIL import Image

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
                              output_color=rawpy.ColorSpace.sRGB, output_bps=8)
    image = Image.fromarray(rgb)
    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    image.save(out_dir / 'original.jpg', quality=92)
    preview = image.copy()
    preview.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    preview.save(out_dir / 'ai.jpg', quality=85)
    arr = np.asarray(image).astype(np.float32) / 255
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
        'preview_version': 2,
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
