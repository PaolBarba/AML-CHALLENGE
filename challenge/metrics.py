"""Deterministic image metrics and organizer-owned edit evaluators."""
import importlib
import math

import numpy as np
from PIL import ImageFilter


def boundary(mask):
    padded = np.pad(mask, 1, constant_values=False)
    interior = mask.copy()
    for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
        interior &= padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return mask & ~interior


def dilate(mask, tolerance):
    from PIL import Image
    return np.asarray(Image.fromarray(mask.astype('uint8') * 255).filter(
        ImageFilter.MaxFilter(2 * tolerance + 1))) > 0


def localization(predicted, truth, tolerance=2):
    p, g = np.asarray(predicted) >= 128, np.asarray(truth) >= 128
    if not g.any():
        raise ValueError('Reference target mask is empty')
    intersection = int((p & g).sum())
    iou = intersection / int((p | g).sum())
    precision = intersection / int(p.sum()) if p.any() else 0.0
    recall = intersection / int(g.sum())
    pb, gb = boundary(p), boundary(g)
    bp = float((pb & dilate(gb, tolerance)).sum() / pb.sum()) if pb.any() else 0.0
    br = float((gb & dilate(pb, tolerance)).sum() / gb.sum())
    return dict(iou=iou, dice=2 * intersection / int(p.sum() + g.sum()),
                precision=precision, recall=recall,
                boundary_f1=2 * bp * br / (bp + br) if bp + br else 0.0,
                success_025=int(iou >= .25), success_050=int(iou >= .50),
                success_075=int(iou >= .75))


def evaluate(source, edited, predicted, truth, allowed, task, config):
    result = localization(predicted, truth, config.get('boundary_tolerance', 2))
    background = np.asarray(allowed) < 128
    if not background.any():
        raise ValueError('Reference allowed edit region has no background')
    a, b = np.asarray(source, dtype=np.float32) / 255, np.asarray(edited, dtype=np.float32) / 255
    result['background_mae'] = float(np.abs(a - b)[background].mean())
    result['preservation'] = 1 - result['background_mae']
    rubric = task.get('edit_rubric', {})
    if rubric.get('kind') == 'target_color':
        target = np.array(rubric['rgb'], dtype=np.float32) / 255
        region = np.asarray(truth) >= 128
        before = float(np.abs(a[region] - target).mean())
        after = float(np.abs(b[region] - target).mean())
        # Color rubrics are for annotated color edits, not general object replacement.
        result['editing'] = max(0.0, min(1.0, 1 - after / before)) if before > 1e-6 else 0.0
        result['editing_evaluator'] = 'annotated_color_improvement'
    elif config.get('edit_evaluator'):
        module, function = config['edit_evaluator'].split(':')
        value = getattr(importlib.import_module(module), function)(source, edited, truth, task)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Organizer edit evaluator must return a finite score in [0, 1]')
        result['editing'] = float(value)
        result['editing_evaluator'] = config['edit_evaluator']
    else:
        result['editing'] = None
        result['editing_evaluator'] = 'unconfigured'
    return result


def score(metrics, config, measured_ms=None):
    weights = config['weights']
    if metrics['editing'] is None:
        return None
    parts = {'localization': metrics['iou'], 'editing': metrics['editing'],
             'preservation': metrics['preservation']}
    if measured_ms is not None:
        parts['efficiency'] = min(1.0, config['reference_time_ms'] / measured_ms)
    denominator = sum(weights[k] for k in parts)
    return sum(weights[k] * v for k, v in parts.items()) / denominator
