"""Create a separate mask-free red-backpack demo dataset."""
import argparse
import json
from pathlib import Path
import shutil

from PIL import Image

from .demo import initialize
from .store import Store


def initialize_reference(root, evaluation=None):
    root = Path(root)
    source = Path(__file__).resolve().parent.parent / 'data' / 'image.png'
    with Image.open(source) as image:
        width, height = image.size
    config = initialize(root)
    shutil.copyfile(source, root / 'images' / 'backpack.png')
    task = dict(task_id='backpack_red', image_id='backpack_reference', split='validation',
                source_image='images/backpack.png',
                source_prompt='A blue backpack with gray straps on a rock in a mountain landscape.',
                target_prompt='Change the blue backpack fabric to red, preserving the straps and background.',
                task_type='attribute_modification', difficulty='easy',
                metadata={'image_width': width, 'image_height': height, 'num_objects': 1})
    config.update(name='Red Backpack Demo', dataset_version='backpack-mask-free-demo-v1', reference_task='backpack_red')
    config['weights'] = {'localization': 0, 'editing': 1, 'preservation': 1, 'efficiency': 0}
    if evaluation:
        config['reference_evaluation'] = evaluation
    (root / 'tasks.json').write_text(json.dumps([task], indent=2) + '\n')
    (root / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    store = Store(root)
    store.db.close()
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='.challenge-reference-v2')
    parser.add_argument('--evaluation-config', help='JSON file with local evaluator checkpoint settings')
    args = parser.parse_args()
    try:
        root = initialize_reference(args.data, json.loads(Path(args.evaluation_config).read_text()) if args.evaluation_config else None)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Initialization failed: {exc}\n')
    print(f'Created {root}; team tokens are in its private config.json')


if __name__ == '__main__':
    main()
