"""Evaluate every accepted reference batch and refresh Excel and rankings."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path

from PIL import Image

if __package__:
    from .reference_metrics import ReferenceMetrics
    from .store import Store
else:
    # Direct execution needs the repository root for the Store's package imports.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from challenge.reference_metrics import ReferenceMetrics
    from challenge.store import Store


def evaluate_batches(store, evaluator, target_prompt=None):
    task = dict(store.reference_task or {})
    if target_prompt is not None:
        task['target_prompt'] = target_prompt
    if not isinstance(task.get('target_prompt'), str) or not task['target_prompt'].strip():
        raise ValueError('Provide --target-prompt: the API dataset has no reference editing prompt')
    with store.lock:
        batches = store.db.execute('SELECT id FROM reference_batches WHERE received IS NOT NULL ORDER BY received,id').fetchall()
    updates = []
    for batch in batches:
        with store.lock:
            row = store.db.execute('SELECT * FROM reference_batches WHERE id=?', (batch['id'],)).fetchone()
        raw = row['source']
        if raw is None:
            raw = store.reference_image_path().read_bytes()
        if hashlib.sha256(raw).hexdigest() != row['source_hash']:
            raise ValueError(f'Original image unavailable or changed for batch {row["id"]}')
        with Image.open(io.BytesIO(raw)) as image:
            source = image.copy()
        with Image.open(io.BytesIO(row['edited'])) as image:
            edited = image.copy()
        with store.evaluation_lock:
            metrics = evaluator.evaluate(source, edited, task)
        if metrics.get('clip_similarity') is None:
            raise ValueError('A local CLIP model is required for semantic prompt evaluation')
        metrics['score'] = metrics['clip_similarity']
        metrics['evaluation_status'] = 'scored' if all(metrics.get(key) is not None for key in
                                                      ('lpips', 'ssim', 'structure_distance')) else 'partial'
        updates.append((json.dumps(metrics, allow_nan=False), row['id']))
    # Commit all scores together so a failed evaluation cannot leave mixed model versions.
    with store.lock, store.db:
        store.db.executemany('UPDATE reference_batches SET metrics=? WHERE id=?', updates)
    return len(updates), store.refresh_excel()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default=os.environ.get('CHALLENGE_DATA', '.challenge'), help='API dataset (defaults to CHALLENGE_DATA or .challenge)')
    parser.add_argument('--target-prompt', help='Editing instruction if the API dataset has no reference task')
    parser.add_argument('--evaluation-config', default='reference-evaluation.clip.json')
    args = parser.parse_args()
    store = None
    try:
        config = json.loads(Path(args.evaluation_config).read_text())
        store = Store(args.data, reference_only=True)
        configured = store.config.get('reference_evaluation')
        if configured and configured != config:
            raise ValueError('Use the same evaluator configuration as the API to keep scores comparable')
        if not store.db.execute('SELECT 1 FROM reference_batches WHERE received IS NOT NULL LIMIT 1').fetchone():
            print(f'No accepted reference uploads in {store.root}. Use --data to select the API dataset.')
            return
        evaluator = ReferenceMetrics(config)
        count, excel_updated = evaluate_batches(store, evaluator, args.target_prompt)
        print(f'Evaluated {count} accepted batches; metrics and reference leaderboard saved in SQLite.')
        if excel_updated:
            print(f'Excel updated: {store.root / "results.xlsx"}')
        else:
            parser.exit(1, 'Scores saved, but Excel refresh failed. Close the workbook and rerun the command.\n')
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        parser.exit(1, f'Evaluation failed: {exc}\n')
    finally:
        if store is not None:
            store.db.close()


if __name__ == '__main__':
    main()
