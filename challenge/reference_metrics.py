"""Mask-free image preservation and prompt alignment metrics."""
import math
from pathlib import Path

import numpy as np
from PIL import Image

PROTOCOL = 'reference-image-metrics-v1'
METRICS = ('psnr', 'lpips', 'mse', 'ssim', 'clip_similarity', 'structure_distance')



def structural_similarity(a, b, window):
    def mean(values):
        integral = np.pad(values, ((1, 0), (1, 0), (0, 0))).cumsum(0).cumsum(1)
        return (integral[window:, window:] - integral[:-window, window:]
                - integral[window:, :-window] + integral[:-window, :-window]) / window ** 2

    ma, mb = mean(a), mean(b)
    correction = window ** 2 / (window ** 2 - 1)
    va, vb = correction * (mean(a * a) - ma * ma), correction * (mean(b * b) - mb * mb)
    covariance = correction * (mean(a * b) - ma * mb)
    # Valid windows avoid padding artifacts; constants use normalized RGB's data range of 1.
    return float((((2 * ma * mb + .01 ** 2) * (2 * covariance + .03 ** 2)) /
                  ((ma * ma + mb * mb + .01 ** 2) * (va + vb + .03 ** 2))).mean())


def pixel_metrics(source, edited):
    if source.mode != 'RGB' or edited.mode != 'RGB' or source.size != edited.size:
        raise ValueError('Compare RGB images with matching dimensions')
    a, b = np.asarray(source, dtype=np.float64) / 255, np.asarray(edited, dtype=np.float64) / 255
    mse = float(np.square(a - b).mean())
    window = min(7, min(source.size))
    if window % 2 == 0:
        window -= 1
    ssim = structural_similarity(a, b, window) if window >= 3 else None
    return dict(psnr=10 * math.log10(1 / mse) if mse else None, psnr_infinite=mse == 0,
                lpips=None, mse=mse, ssim=ssim, clip_similarity=None, structure_distance=None,
                evaluation_protocol=PROTOCOL, evaluation_region='whole_image')


def ranking_key(metrics):
    def value(name, higher=False):
        result = metrics.get(name)
        return (-result if higher else result) if result is not None else math.inf
    return (value('clip_similarity', higher=True), value('ssim', higher=True),
            value('lpips'), value('structure_distance'), value('mse'))


class ReferenceMetrics:
    def __init__(self, config):
        self.representations = self.lpips = None
        learned = any(config.get(key) for key in ('clip_directory', 'dinov2_directory', 'lpips_checkpoint'))
        if learned and not config.get('model_version'):
            raise ValueError('Set reference_evaluation.model_version to the frozen model revisions')
        self.version = config.get('model_version')
        self.device = config.get('device', 'cpu')
        if config.get('clip_directory') or config.get('dinov2_directory'):
            from .representations import RepresentationMetrics
            self.representations = RepresentationMetrics(config)
        if config.get('lpips_checkpoint'):
            checkpoint = Path(config['lpips_checkpoint'])
            if not checkpoint.is_file():
                raise ValueError('lpips_checkpoint must be a complete local pretrained LPIPS state dict')
            import torch
            import lpips
            self.torch = torch
            # All randomly initialized weights are replaced by the complete local checkpoint.
            self.lpips = lpips.LPIPS(net='alex', pnet_rand=True, pretrained=False, verbose=False)
            self.lpips.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True), strict=True)
            self.lpips = self.lpips.to(self.device).eval()

    def evaluate(self, source, edited, task):
        result = pixel_metrics(source, edited)
        if self.representations:
            result.update(self.representations.evaluate_reference(source, edited, task['target_prompt']))
        if self.lpips:
            # shortcut: LPIPS uses the whole frame at a bounded resolution; freeze this protocol before grading.
            width, height = source.size
            scale = min(512 / max(width, height), 1)
            size = (max(64, round(width * scale)), max(64, round(height * scale)))

            def tensor(image):
                pixels = np.array(image.resize(size, Image.Resampling.BICUBIC), dtype=np.float32)
                return self.torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0).to(self.device) / 127.5 - 1

            with self.torch.inference_mode():
                result['lpips'] = float(self.lpips(tensor(source), tensor(edited)).item())
        if any(result[key] is not None and not math.isfinite(result[key]) for key in METRICS):
            raise ValueError('Image evaluator returned a non-finite metric')
        result['evaluator_version'] = self.version
        return result
