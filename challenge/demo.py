"""Generate a small, reproducible fixture; this is not a research dataset."""
import json
import secrets
from pathlib import Path

from PIL import Image, ImageDraw


def initialize(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (root / 'config.json').exists():
        raise ValueError('Configuration already exists; refusing to overwrite')
    (root / 'images').mkdir(exist_ok=True)
    (root / 'masks').mkdir(exist_ok=True)
    tasks = []
    for split in ('train', 'validation', 'test'):
        for index in range(2):
            task_id = f'{split}_{index + 1:03d}'
            image = Image.new('RGB', (256, 192), (231, 236, 240))
            draw = ImageDraw.Draw(image)
            x = 32 + index * 16
            draw.rectangle((x, 55, x + 65, 125), fill=(210, 45, 55))
            draw.ellipse((155, 65, 218, 128), fill=(45, 160, 95))
            draw.rectangle((0, 155, 255, 191), fill=(173, 183, 194))
            mask = Image.new('L', image.size)
            ImageDraw.Draw(mask).rectangle((x, 55, x + 65, 125), fill=255)
            image.save(root / 'images' / f'{task_id}.png')
            mask.save(root / 'masks' / f'{task_id}.png')
            tasks.append(dict(task_id=task_id, image_id=task_id,
                              source_image=f'images/{task_id}.png',
                              ground_truth_mask=f'masks/{task_id}.png', split=split,
                              source_prompt='The red rectangle on the left.',
                              target_prompt='Change the red rectangle to blue.',
                              task_type='attribute_modification', difficulty='easy',
                              edit_rubric={'kind': 'target_color', 'rgb': [40, 90, 220]},
                              metadata={'image_width': 256, 'image_height': 192, 'num_objects': 2}))
    config = {'name': 'Semantic Editing Lab', 'dataset_version': 'synthetic-demo-v1',
              'weights': {'localization': .30, 'editing': .30, 'preservation': .25, 'efficiency': .15},
              'reference_time_ms': 5000, 'hardware_profile': 'organizer-cpu',
              'boundary_tolerance': 2, 'max_submissions_per_run': 100,
              'admin_token': secrets.token_urlsafe(32),
              'teams': {'team_demo': secrets.token_urlsafe(32)},
              'selected_runs': {}}
    (root / 'tasks.json').write_text(json.dumps(tasks, indent=2))
    (root / 'config.json').write_text(json.dumps(config, indent=2))
    (root / 'config.json').chmod(0o600)
    return config
