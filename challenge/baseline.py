"""Synthetic color-edit baseline, also the standardized inference entry point example."""
import argparse
import base64
import io
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .client import Client
from .store import image_bytes


def edit(image, source_prompt, target_prompt):
    if 'red rectangle' not in source_prompt.lower() or 'blue' not in target_prompt.lower():
        raise ValueError('Demo baseline only supports red-rectangle-to-blue tasks')
    start = time.perf_counter()
    pixels = np.asarray(image)
    mask = (pixels[:, :, 0] > 170) & (pixels[:, :, 1] < 85) & (pixels[:, :, 2] < 95)
    localization_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    output = pixels.copy()
    output[mask] = [40, 90, 220]
    edited = Image.fromarray(output)
    predicted = Image.fromarray(mask.astype('uint8') * 255)
    return edited, predicted, {'localization_time_ms': localization_ms,
                              'editing_time_ms': (time.perf_counter() - start) * 1000,
                              'model_name': 'synthetic_color_baseline', 'seed': 0}


def infer(input_file, output_dir):
    input_file = Path(input_file)
    task = json.loads(input_file.read_text())
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(input_file.parent / task['source_image']) as image:
        edited, mask, metadata = edit(image.convert('RGB'), task['source_prompt'], task['target_prompt'])
    edited.save(output / 'edited.png')
    mask.save(output / 'mask.png')
    (output / 'metadata.json').write_text(json.dumps(metadata))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    inference = sub.add_parser('infer')
    inference.add_argument('--input', required=True)
    inference.add_argument('--output', required=True)
    submit = sub.add_parser('submit')
    submit.add_argument('--server', default='http://127.0.0.1:8000')
    submit.add_argument('--split', choices=['train', 'validation', 'test'], default='validation')
    submit.add_argument('--run', default='baseline_001')
    args = parser.parse_args()
    if args.action == 'infer':
        infer(args.input, args.output)
        return
    client = Client(args.server)
    identity = client.request('/api/config')
    if identity['admin']:
        raise ValueError('Use a team token for baseline uploads')
    client.request('/api/runs', {'run_id': args.run, 'split': args.split})
    for task in client.request('/api/tasks?split=' + args.split):
        with Image.open(io.BytesIO(client.request(task['image_url'], binary=True))) as image:
            edited, mask, metadata = edit(image.convert('RGB'), task['source_prompt'], task['target_prompt'])
        metadata['run_id'] = args.run
        result = client.request('/api/submissions', {'task_id': task['task_id'], 'student_id': identity['identity'],
            'edited_image': base64.b64encode(image_bytes(edited)).decode(),
            'predicted_mask': base64.b64encode(image_bytes(mask)).decode(), 'metadata': metadata})
        print(json.dumps(result))
    client.request('/api/select-run', {'split': args.split, 'run_id': args.run})


if __name__ == '__main__':
    main()
