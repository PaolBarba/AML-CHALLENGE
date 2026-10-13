import base64
import binascii
import hmac
import hashlib
import io
import json
import logging
import math
import re
import sqlite3
import tempfile
import threading
import time
import warnings
import uuid
from pathlib import Path

from PIL import Image

from .metrics import evaluate, score

ID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')
Image.MAX_IMAGE_PIXELS = 16_000_000


class Invalid(ValueError):
    pass


def image_bytes(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def decode_image(encoded, mode, size=None, formats=('PNG',)):
    if not isinstance(encoded, str) or len(encoded) > 24_000_000:
        raise Invalid('Image must be a bounded base64-encoded image')
    try:
        raw = base64.b64decode(encoded, validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in formats or (size is not None and image.size != size) or image.mode != mode:
                    raise Invalid(f'Expected a {mode} image in {formats}' + (f' of dimensions {size}' if size else ''))
                if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                    raise Invalid('Image exceeds pixel limit')
                if getattr(image, 'n_frames', 1) != 1:
                    raise Invalid('Animated PNGs are not accepted')
                image.load()
                return image.copy()
    except (binascii.Error, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise Invalid(f'Invalid image: {exc}') from exc


class Store:
    def __init__(self, root, reference_only=False):
        self.root = Path(root).resolve()
        if not (self.root / 'config.json').is_file():
            raise Invalid(f'Missing configuration: {self.root / "config.json"}. Restore the dataset or initialize a new directory with python -m challenge.reference_demo --data NEW_DIRECTORY, then set CHALLENGE_DATA to it.')
        if reference_only and not (self.root / 'results.sqlite3').is_file():
            raise Invalid('No existing API results database in this data directory')
        self.config = json.loads((self.root / 'config.json').read_text())
        self.tasks = {}
        weights = self.config.get('weights', {})
        if set(weights) != {'localization', 'editing', 'preservation', 'efficiency'}:
            raise Invalid('Configure all four scoring weights')
        if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
            raise Invalid('Weights must be finite, nonnegative, and have a positive sum')
        if sum(weights[k] for k in ('localization', 'editing', 'preservation')) <= 0:
            raise Invalid('Quality weights must have a positive sum')
        reference = self.config.get('reference_time_ms')
        if isinstance(reference, bool) or not isinstance(reference, (int, float)) or not math.isfinite(reference) or reference <= 0:
            raise Invalid('Reference time must be positive and finite')
        tolerance = self.config.get('boundary_tolerance', 2)
        if isinstance(tolerance, bool) or not isinstance(tolerance, int) or not 0 <= tolerance <= 20:
            raise Invalid('Boundary tolerance must be an integer from 0 to 20')
        tokens = [self.config.get('admin_token', '')] + list(self.config.get('teams', {}).values())
        if any(not isinstance(t, str) or len(t) < 24 for t in tokens) or len(set(tokens)) != len(tokens):
            raise Invalid('Use distinct authentication tokens of at least 24 characters')
        if any(not ID.fullmatch(t) for t in self.config.get('teams', {})):
            raise Invalid('Invalid team identifier')
        image_splits = {}
        for task in json.loads((self.root / 'tasks.json').read_text()):
            task_id = task.get('task_id', '')
            if not ID.fullmatch(task_id) or task_id in self.tasks:
                raise Invalid('Task IDs must be unique safe identifiers')
            if task.get('split') not in ('train', 'validation', 'test'):
                raise Invalid('Unknown dataset split')
            for field in ('image_id', 'source_prompt', 'target_prompt', 'task_type', 'difficulty'):
                if not isinstance(task.get(field), str) or not task[field]:
                    raise Invalid(f'Missing {field} for {task_id}')
            image_key = str(self.path(task['source_image']))
            for key in (image_key, task['image_id']):
                if key in image_splits and image_splits[key] != task['split']:
                    raise Invalid('Source images cannot span dataset splits')
                image_splits[key] = task['split']
            if not reference_only:
                source = self.load(task, 'source_image', 'RGB')
                if source.width * source.height > Image.MAX_IMAGE_PIXELS:
                    raise Invalid('Source image exceeds pixel limit')
                if task.get('metadata', {}).get('image_width') != source.width or task.get('metadata', {}).get('image_height') != source.height:
                    raise Invalid(f'Incorrect image metadata for {task_id}')
                if task_id != self.config.get('reference_task') or task.get('ground_truth_mask'):
                    truth = self.load(task, 'ground_truth_mask', 'L')
                    allowed = self.load(task, 'allowed_edit_mask', 'L') if task.get('allowed_edit_mask') else truth
                    import numpy as np
                    g, a = np.asarray(truth), np.asarray(allowed)
                    if truth.size != source.size or allowed.size != source.size or not np.isin(g, [0, 255]).all() or not np.isin(a, [0, 255]).all():
                        raise Invalid('Reference masks must be binary and match source dimensions')
                    if not (g > 0).any() or not (a == 0).any() or ((g > 0) & (a == 0)).any():
                        raise Invalid('Masks require a target, a background, and an allowed region containing the target')
            rubric = task.get('edit_rubric', {})
            if rubric.get('kind') == 'target_color':
                rgb = rubric.get('rgb')
                if not isinstance(rgb, list) or len(rgb) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in rgb):
                    raise Invalid('Target color must contain three integer RGB channels')
            self.tasks[task_id] = task
        if self.config.get('edit_evaluator') and not self.config.get('evaluator_version'):
            raise Invalid('Custom edit evaluators require an evaluator_version')
        if not self.tasks:
            raise Invalid('Dataset is empty')
        self.reference_task = self.tasks.get(self.config.get('reference_task'))
        if self.config.get('reference_task') and self.reference_task is None:
            raise Invalid('Unknown configured reference_task')
        self.representations = None
        if self.config.get('representation_metrics') and not reference_only:
            from .representations import RepresentationMetrics
            self.representations = RepresentationMetrics(self.config['representation_metrics'])
        self.evaluation_lock = threading.Lock()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'results.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        # Rollback journals support the shared filesystem used by Slurm jobs.
        self.db.executescript('''
          PRAGMA journal_mode=DELETE;
          CREATE TABLE IF NOT EXISTS reference_access (
            team TEXT PRIMARY KEY, started REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS reference_batches (
            id TEXT PRIMARY KEY, team TEXT NOT NULL, window_end REAL NOT NULL,
            source_hash TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            created REAL NOT NULL, received REAL, edited BLOB,
            UNIQUE(team, window_end, source_hash));
          CREATE TABLE IF NOT EXISTS shared_images (
            id TEXT PRIMARY KEY, filename TEXT NOT NULL, created REAL NOT NULL,
            expires REAL NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            image BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS benchmark (fingerprint TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY, team TEXT NOT NULL, run TEXT NOT NULL,
            task TEXT NOT NULL, created REAL NOT NULL, metadata TEXT NOT NULL,
            metrics TEXT NOT NULL, edited BLOB NOT NULL, mask BLOB NOT NULL,
            measured_ms REAL, profile TEXT,
            UNIQUE(team, run, task));
          CREATE TABLE IF NOT EXISTS runs (
            team TEXT NOT NULL, run TEXT NOT NULL, split TEXT NOT NULL,
            mode TEXT NOT NULL, created REAL NOT NULL,
            PRIMARY KEY(team,run,split));
          CREATE TABLE IF NOT EXISTS selections (
            team TEXT NOT NULL, split TEXT NOT NULL, run TEXT NOT NULL,
            PRIMARY KEY(team, split));
        ''')
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(reference_batches)')}
        for column in ('metrics', 'mask', 'source'):
            if column not in columns:
                self.db.execute(f'ALTER TABLE reference_batches ADD COLUMN {column} ' + ('TEXT' if column == 'metrics' else 'BLOB'))
        if not reference_only:
            fingerprint = hashlib.sha256()
            benchmark_config = {k: self.config.get(k) for k in ('weights', 'reference_time_ms', 'hardware_profile', 'boundary_tolerance', 'dataset_version', 'edit_evaluator', 'evaluator_version', 'representation_metrics')}
            if self.reference_task:
                benchmark_config['reference_task'] = self.reference_task['task_id']
            if self.config.get('reference_evaluation'):
                from .reference_metrics import PROTOCOL
                benchmark_config['reference_evaluation'] = self.config['reference_evaluation']
                benchmark_config['reference_evaluation_protocol'] = PROTOCOL
            fingerprint.update(json.dumps(benchmark_config, sort_keys=True).encode())
            fingerprint.update(json.dumps(list(self.tasks.values()), sort_keys=True).encode())
            for task in self.tasks.values():
                for field in ('source_image', 'ground_truth_mask', 'allowed_edit_mask'):
                    if task.get(field):
                        fingerprint.update(self.path(task[field]).read_bytes())
            existing = self.db.execute('SELECT fingerprint FROM benchmark').fetchone()
            if existing and existing[0] != fingerprint.hexdigest():
                self.db.close()
                raise Invalid('Benchmark changed; use a new data directory and results database')
            if not existing:
                self.db.execute('INSERT INTO benchmark VALUES(?)', (fingerprint.hexdigest(),))
        self.db.commit()
        self.refresh_excel()

    def export_excel(self):
        from .excel import workbook_bytes
        # shortcut: one local server owns the workbook; use a single export worker if scaling to multiple processes.
        with self.lock:
            raw = workbook_bytes(self)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.root, suffix='.xlsx', delete=False) as output:
                    temporary = Path(output.name)
                    output.write(raw)
                temporary.replace(self.root / 'results.xlsx')
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return raw

    def refresh_excel(self):
        try:
            self.export_excel()
            return True
        except Exception:
            # The submission is already committed; an export failure must not invite duplicate retries.
            logging.exception('Excel refresh failed; records are safe in SQLite. Retry the organizer export.')
            return False

    def path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise Invalid('Dataset path escapes data directory')
        return path

    def reference_window(self, team):
        now = time.time()
        with self.lock, self.db:
            self.db.execute('INSERT OR IGNORE INTO reference_access VALUES(?,?)', (team, now))
            started = self.db.execute('SELECT started FROM reference_access WHERE team=?', (team,)).fetchone()[0]
        elapsed = max(0, now - started)
        phase = elapsed % 60
        available = phase >= 30
        remaining = (60 if available else 30) - phase
        return dict(available=available, server_time=now, seconds_remaining=remaining,
                    next_change_at=now + remaining, wait_seconds=30, available_seconds=30,
                    image_url='/api/reference/image')

    def load(self, task, field, mode):
        with Image.open(self.path(task[field])) as image:
            if image.mode != mode:
                raise Invalid(f'{field} must have mode {mode}')
            return image.copy()

    def issue_reference_batch(self, team, raw, width, height, window_end):
        digest = hashlib.sha256(raw).hexdigest()
        with self.lock, self.db:
            existing = self.db.execute('SELECT id FROM reference_batches WHERE team=? AND window_end=? AND source_hash=?',
                                       (team, window_end, digest)).fetchone()
            if existing:
                return existing['id']
            count = self.db.execute('SELECT COUNT(*) FROM reference_batches WHERE team=?', (team,)).fetchone()[0]
            if count >= self.config.get('max_team_submissions', 1000):
                raise Invalid('Reference batch limit reached')
            batch_id = uuid.uuid4().hex
            self.db.execute('INSERT INTO reference_batches (id,team,window_end,source_hash,width,height,created,source) VALUES(?,?,?,?,?,?,?,?)',
                            (batch_id, team, window_end, digest, width, height, time.time(), raw))
        return batch_id

    def submit_reference(self, payload, team, admin=False):
        if admin or team not in self.config['teams']:
            raise PermissionError('Use a team token to submit a reference edit')
        batch_id = payload.get('batch_id')
        if not isinstance(batch_id, str) or not ID.fullmatch(batch_id):
            raise Invalid('Provide the batch_id from GET /api/reference/json')
        with self.lock:
            batch = self.db.execute('SELECT * FROM reference_batches WHERE id=? AND team=?', (batch_id, team)).fetchone()
        if batch is None:
            raise PermissionError('Batch was not issued to this team in this dataset. Download a fresh reference from this API using the same team token, then upload with its reference.json.')
        edited_image = decode_image(payload.get('edited_image'), 'RGB', (batch['width'], batch['height']))
        with self.lock, self.db:
            cursor = self.db.execute('UPDATE reference_batches SET received=?, edited=?, metrics=? WHERE id=? AND received IS NULL',
                                     (time.time(), image_bytes(edited_image), None, batch_id))
            if cursor.rowcount != 1:
                raise Invalid('An edit was already accepted for this batch')
        return dict(status='accepted', batch_id=batch_id, reference_id='backpack_reference',
                    scoring_status='pending',
                    metrics=None, excel_updated=self.refresh_excel())

    def reference_image_path(self):
        if self.reference_task:
            return self.path(self.reference_task['source_image'])
        return Path(__file__).resolve().parent.parent / 'data' / 'image.png'

    def reference_instructions(self):
        if not self.reference_task:
            return {}
        return {key: self.reference_task[key] for key in ('task_id', 'source_prompt', 'target_prompt')}

    def reference_leaderboard(self):
        from .reference_metrics import PROTOCOL, ranking_key
        with self.lock:
            rows = self.db.execute('SELECT id,team,received,metrics FROM reference_batches WHERE metrics IS NOT NULL').fetchall()
        best = {}
        for row in rows:
            metrics = json.loads(row['metrics'])
            if metrics.get('evaluation_protocol') != PROTOCOL or metrics.get('clip_similarity') is None:
                continue
            item = dict(team=row['team'], batch_id=row['id'], received=row['received'], metrics=metrics, score=metrics['score'])
            previous = best.get(row['team'])
            if previous is None or (ranking_key(item['metrics']), item['received'], item['batch_id']) < (ranking_key(previous['metrics']), previous['received'], previous['batch_id']):
                best[row['team']] = item
        return sorted(best.values(), key=lambda item: (ranking_key(item['metrics']), item['received'], item['team']))

    def authenticate(self, token):
        if hmac.compare_digest(token, self.config['admin_token']):
            return 'admin', True
        for team, expected in self.config['teams'].items():
            if hmac.compare_digest(token, expected):
                return team, False
        return None, False

    def upload_image(self, payload, admin=False):
        if not admin:
            raise PermissionError('Only organizers can upload source images')
        filename = payload.get('filename', 'source.png')
        if not isinstance(filename, str) or not 1 <= len(filename) <= 200 or '/' in filename or '\\' in filename or any(ord(c) < 32 for c in filename):
            raise Invalid('filename must be a plain name of at most 200 characters')
        image = decode_image(payload.get('image'), 'RGB', formats=('PNG', 'JPEG'))
        raw = image_bytes(image)
        now = time.time()
        image_id = uuid.uuid4().hex
        with self.lock, self.db:
            self.db.execute('DELETE FROM shared_images WHERE expires<=?', (now,))
            count, size = self.db.execute('SELECT COUNT(*), COALESCE(SUM(LENGTH(image)),0) FROM shared_images').fetchone()
            if count >= 100 or size + len(raw) > 256 * 1024 * 1024:
                raise Invalid('Temporary image storage limit reached')
            self.db.execute('INSERT INTO shared_images VALUES(?,?,?,?,?,?,?)',
                            (image_id, filename, now, now + 300, image.width, image.height, raw))
        return dict(image_id=image_id, filename=filename, created_at=now, expires_at=now + 300,
                    image_width=image.width, image_height=image.height,
                    image_url=f'/api/images/{image_id}', duration_seconds=300)

    def shared_images(self):
        now = time.time()
        with self.lock, self.db:
            self.db.execute('DELETE FROM shared_images WHERE expires<=?', (now,))
            rows = self.db.execute('SELECT id,filename,created,expires,width,height FROM shared_images ORDER BY created DESC').fetchall()
        return [dict(image_id=r['id'], filename=r['filename'], created_at=r['created'],
                     expires_at=r['expires'], image_width=r['width'], image_height=r['height'],
                     image_url=f'/api/images/{r["id"]}', duration_seconds=300) for r in rows]

    def shared_image(self, image_id):
        with self.lock, self.db:
            self.db.execute('DELETE FROM shared_images WHERE expires<=?', (time.time(),))
            row = self.db.execute('SELECT image FROM shared_images WHERE id=?', (image_id,)).fetchone()
        if row is None:
            raise KeyError('Image not found or expired')
        return row['image']

    def public_task(self, task):
        return {key: task[key] for key in ('task_id', 'image_id', 'source_prompt', 'target_prompt', 'task_type', 'difficulty', 'split', 'metadata')} | {
            'image_url': f'/api/tasks/{task["task_id"]}/image',
            **({'mask_url': f'/api/tasks/{task["task_id"]}/mask'} if task['split'] != 'test' and task is not self.reference_task else {})}

    def submit(self, payload, team, admin=False, measured=False):
        if not isinstance(payload, dict):
            raise Invalid('Submission must be an object')
        if measured and not admin:
            raise PermissionError('Only organizers can attest measured execution')
        if admin:
            team = payload.get('student_id')
        if team not in self.config['teams'] or payload.get('student_id', team) != team:
            raise PermissionError('Submission team does not match authenticated identity')
        task = self.tasks.get(payload.get('task_id'))
        if task is None:
            raise Invalid('Unknown task')
        if task is self.reference_task:
            raise Invalid('Submit reference edits through /api/reference/submissions')
        metadata = payload.get('metadata', {})
        if not isinstance(metadata, dict) or len(json.dumps(metadata)) > 16_384:
            raise Invalid('Metadata must be an object of at most 16 KB')
        run = metadata.get('run_id')
        if not isinstance(run, str) or not ID.fullmatch(run):
            raise Invalid('metadata.run_id must be a safe identifier')
        for field in ('localization_time_ms', 'editing_time_ms', 'peak_gpu_memory_mb'):
            value = metadata.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise Invalid(f'{field} must be finite and nonnegative')
        measured_ms = None
        if measured:
            measured_ms = payload.get('measured_total_time_ms')
            if isinstance(measured_ms, bool) or not isinstance(measured_ms, (int, float)) or not math.isfinite(measured_ms) or measured_ms <= 0:
                raise Invalid('Measured runtime must be positive and finite')
            if payload.get('hardware_profile') != self.config['hardware_profile']:
                raise Invalid('Measured execution must match configured hardware profile')
        elif any(key in payload for key in ('measured_total_time_ms', 'hardware_profile')):
            raise Invalid('Use the organizer-only measured submission endpoint')
        source = self.load(task, 'source_image', 'RGB')
        edited = decode_image(payload.get('edited_image'), 'RGB', source.size)
        predicted = decode_image(payload.get('predicted_mask'), 'L', source.size)
        truth = self.load(task, 'ground_truth_mask', 'L')
        allowed = self.load(task, 'allowed_edit_mask', 'L') if task.get('allowed_edit_mask') else truth
        self.register_run(team, task['split'], run, measured)
        with self.evaluation_lock:
            metrics = evaluate(source, edited, predicted, truth, allowed, task, self.config)
            if self.representations:
                metrics.update(self.representations.evaluate(source, edited, allowed, task))
        metrics['efficiency'] = min(1., self.config['reference_time_ms'] / measured_ms) if measured_ms else None
        metrics['score'] = score(metrics, self.config, measured_ms)
        with self.lock, self.db:
            team_count = self.db.execute('SELECT COUNT(*) FROM submissions WHERE team=?', (team,)).fetchone()[0]
            if team_count >= self.config.get('max_team_submissions', 1000):
                raise Invalid('Team submission limit reached')
            count = self.db.execute('SELECT COUNT(*) FROM submissions WHERE team=? AND run=?', (team, run)).fetchone()[0]
            if count >= self.config.get('max_submissions_per_run', 100):
                raise Invalid('Run submission limit reached')
            try:
                cursor = self.db.execute('''INSERT INTO submissions
                    (team,run,task,created,metadata,metrics,edited,mask,measured_ms,profile)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (team, run, task['task_id'], time.time(), json.dumps(metadata, allow_nan=False),
                     json.dumps(metrics, allow_nan=False), image_bytes(edited), image_bytes(predicted),
                     measured_ms, self.config['hardware_profile'] if measured else None))
            except sqlite3.IntegrityError as exc:
                raise Invalid('This task already exists in the run; use a new run_id') from exc
        result = {'submission_id': cursor.lastrowid, 'status': 'accepted',
                  'ranking_mode': 'measured' if measured else 'quality_only',
                  'excel_updated': self.refresh_excel()}
        if task['split'] != 'test' or admin:
            result['metrics'] = metrics
        return result

    def submissions(self, team, admin=False):
        with self.lock:
            rows = self.db.execute('SELECT id,team,run,task,created,metadata,metrics,measured_ms FROM submissions' +
                                   ('' if admin else ' WHERE team=?') + ' ORDER BY id DESC', () if admin else (team,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            task = self.tasks[item['task']]
            item['metadata'] = json.loads(item['metadata'])
            item['split'] = task['split']
            if task['split'] == 'test' and not admin:
                item.pop('metrics')
            else:
                item['metrics'] = json.loads(item['metrics'])
            result.append(item)
        return result

    def artifact(self, submission_id, kind, team, admin):
        with self.lock:
            row = self.db.execute('SELECT * FROM submissions WHERE id=?', (submission_id,)).fetchone()
        if row is None:
            raise KeyError('Submission not found')
        if row['team'] != team and not admin:
            raise PermissionError('Submission belongs to another team')
        if kind not in ('edited', 'mask'):
            raise KeyError('Artifact not found')
        return row[kind]

    def register_run(self, team, split, run, measured=False):
        if team not in self.config['teams'] or split not in ('train', 'validation', 'test') or not isinstance(run, str) or not ID.fullmatch(run):
            raise Invalid('Invalid team, split, or run')
        with self.lock, self.db:
            existing = self.db.execute('SELECT mode FROM runs WHERE team=? AND run=? AND split=?', (team, run, split)).fetchone()
            if existing:
                if measured:
                    self.db.execute("UPDATE runs SET mode='measured' WHERE team=? AND run=? AND split=?", (team, run, split))
                else:
                    return
            else:
                count = self.db.execute('SELECT COUNT(*) FROM runs WHERE team=?', (team,)).fetchone()[0]
                if count >= self.config.get('max_runs_per_team', 100):
                    raise Invalid('Team run limit reached')
                self.db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (team, run, split, 'measured' if measured else 'quality', time.time()))
        self.refresh_excel()

    def select(self, team, split, run):
        if split not in ('train', 'validation', 'test') or not isinstance(run, str) or not ID.fullmatch(run):
            raise Invalid('Invalid split or run')
        with self.lock, self.db:
            if not self.db.execute('SELECT 1 FROM runs WHERE team=? AND split=? AND run=?', (team, split, run)).fetchone():
                raise Invalid('Unknown run in this split')
            self.db.execute('INSERT OR REPLACE INTO selections VALUES(?,?,?)', (team, split, run))
        self.refresh_excel()

    def leaderboard(self, split, measured=False):
        tasks = {k: t for k, t in self.tasks.items() if t['split'] == split}
        if not tasks:
            return []
        with self.lock:
            rows = self.db.execute('SELECT team,run,task,metrics,measured_ms,created FROM submissions ORDER BY created').fetchall()
            selections = {(r['team'], r['split']): r['run'] for r in self.db.execute('SELECT * FROM selections')}
            registered = self.db.execute('SELECT team,run,mode FROM runs WHERE split=? ORDER BY created', (split,)).fetchall()
        runs = {(r['team'], r['run']): {} for r in registered}
        run_modes = {(r['team'], r['run']): r['mode'] for r in registered}
        for row in rows:
            if row['task'] not in tasks:
                continue
            key = row['team'], row['run']
            runs.setdefault(key, {})[row['task']] = row
        latest = {}
        for team, run in runs:
            latest[team] = run
        groups = {}
        for task_id, task in tasks.items():
            groups.setdefault(task['task_type'], []).append(task_id)
        results = []
        for (team, run), records in runs.items():
            if selections.get((team, split), latest[team]) != run:
                continue
            valid_records = {k: v for k, v in records.items() if not measured or v['measured_ms'] is not None}
            unscored = any(json.loads(r['metrics'])['editing'] is None for r in valid_records.values())
            parts = ('iou', 'editing', 'preservation') + (('efficiency',) if measured else ())
            means = {}
            breakdown = {}
            for group, ids in groups.items():
                breakdown[group] = {}
                for part in parts:
                    values = [json.loads(valid_records[k]['metrics'])[part] or 0 if k in valid_records else 0 for k in ids]
                    breakdown[group][part] = sum(values) / len(ids)
            for part in parts:
                means[part] = sum(g[part] for g in breakdown.values()) / len(groups)
            synthetic = dict(means, editing=None if unscored else means['editing'])
            # Recompute quality score for every row; measured and upload scores never mix.
            total = score(synthetic, self.config)
            if measured and not unscored:
                w = self.config['weights']
                total = (w['localization'] * means['iou'] + w['editing'] * means['editing'] +
                         w['preservation'] * means['preservation'] + w['efficiency'] * means['efficiency']) / sum(w.values())
            difficulties = {}
            for difficulty in {t['difficulty'] for t in tasks.values()}:
                ids = [k for k, t in tasks.items() if t['difficulty'] == difficulty]
                values = [score(json.loads(valid_records[k]['metrics']), self.config,
                                valid_records[k]['measured_ms'] if measured else None) if k in valid_records else 0 for k in ids]
                difficulties[difficulty] = None if any(v is None for v in values) else sum(values) / len(ids)
            results.append(dict(team=team, run=run, score=None if unscored or (measured and not valid_records and run_modes.get((team, run)) != 'measured') else total,
                                completed=len(valid_records), total=len(tasks), metrics=means,
                                task_types=breakdown, difficulties=difficulties,
                                measured_total_time_ms=sum(r['measured_ms'] or 0 for r in valid_records.values()) if measured else None))
        return sorted(results, key=lambda r: (r['score'] is None, -(r['score'] or 0),
                      -r['metrics']['editing'], -r['metrics']['preservation'], r['measured_total_time_ms'] or 0, r['team']))
