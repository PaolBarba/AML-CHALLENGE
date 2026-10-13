# Semantic Image Editing Lab

A local challenge platform for the [Advanced Machine Learning challenge](CHALLENGE.md): authenticated tasks and submissions, SQLite experiment tracking, localization and preservation metrics, configurable edit evaluation, run selection, leaderboards, and image comparisons.

## Run it

Python 3.11 or newer is required. This workspace already has `.venv` with the core dependencies installed.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m challenge.server init-demo
.venv/bin/python -m challenge.server serve
```

Open **http://127.0.0.1:8000**. Enter the `team_demo` token from `.challenge/config.json`. The organizer token grants access to private test masks and all teams' experiments. Credentials are generated locally, never embedded in the frontend, and kept in the browser's memory rather than persistent browser storage.

`init-demo` refuses to overwrite an existing configuration. If the demo is already initialized, run only `serve`. Use `--data /path/to/dataset` before the subcommand for another dataset.

The bundled dataset has six synthetic color-edit tasks across training, validation, and test. It exercises the complete submission workflow; it is not a realistic image-editing benchmark or a trained DINOv2 editor.

## Complete a student run

With the server running, load the demo team's token without printing it:

```bash
export CHALLENGE_TOKEN="$(.venv/bin/python -c 'import json; print(json.load(open(".challenge/config.json"))["teams"]["team_demo"])')"
.venv/bin/python -m challenge.baseline submit --split validation --run baseline_001
```

This downloads each validation image, localizes the red rectangle, changes it to blue, submits the original-resolution grayscale mask and RGB edit, and selects the run for the leaderboard. The baseline is deliberately limited to the synthetic fixture. Students replace it with their own grounding and editing system.

For a manual submission, open **Challenge tasks**, choose a task, upload the two PNGs, and supply a run ID. **Your experiments** shows history, run selection, source/edit comparisons, predicted mask overlays, reference masks for public splits, and pixel difference maps.

## Inference entry point

Participant code receives an input directory containing `task.json` and `source.png`:

```json
{
  "task_id": "validation_001",
  "source_image": "source.png",
  "source_prompt": "The red rectangle on the left.",
  "target_prompt": "Change the red rectangle to blue."
}
```

An entry point accepts `--input /input/task.json --output /output` and writes:

- `edited.png`: single-frame RGB PNG at source resolution.
- `mask.png`: single-frame grayscale PNG at source resolution; confidences are quantized to 0–255.
- `metadata.json`: an object containing model identity and optional reported localization/editing timings, seed, and GPU-memory measurements.

The runnable example is `python -m challenge.baseline infer --input TASK_JSON --output OUTPUT_DIRECTORY`.

## Organizer-measured runs

The upload API cannot measure student inference. Upload scores omit efficiency and renormalize the other weights; reported timings are stored but never treated as verified. Measured results have their own leaderboard.

Build a container with a preinstalled model and inference entry point:

```bash
docker build -f Dockerfile.baseline -t semantic-baseline .
export CHALLENGE_TOKEN="$(.venv/bin/python -c 'import json; print(json.load(open(".challenge/config.json"))["admin_token"])')"
.venv/bin/python -m challenge.runner --team team_demo --run measured_001 \
  --profile organizer-cpu --image semantic-baseline
```

The runner gives each task a separate container with network disabled, a read-only root filesystem, dropped capabilities, a non-root user, a process limit, a timeout, and CPU/memory limits. Only the public task input is mounted read-only; output has a separate writable mount. Preload all model weights into the image. The organizer token and test annotations are not passed to the container.

Options include `--timeout`, `--memory`, `--cpus`, and `--gpus device=0`. Use a hardware profile that matches `config.json`. Profiles are organizer attestations; benchmark the reference time on the same physical hardware and resource settings. Runtime includes process/model initialization and container startup, but excludes input download, output collection, container cleanup, upload, and evaluation. Failed or missing tasks score zero. A fully failed registered run remains visible.

For organizer-owned code only, verify the pipeline without Docker:

```bash
.venv/bin/python -m challenge.runner --team team_demo --run measured_local_001 \
  --profile organizer-cpu --trusted-local -- \
  .venv/bin/python -m challenge.baseline infer --input '{input}' --output '{output}'
```

Trusted-local execution has no isolation or memory limit. Do not use it for untrusted submissions. Docker supplies execution isolation but is not a replacement for dedicated worker machines when running hostile code.

GPU peak memory and utilization are not independently measured by this runner. Optional participant-reported `peak_gpu_memory_mb` stays in metadata and is unverified. The core measured efficiency score uses organizer-measured total time only.

## Dataset and configuration

Create a private dataset directory with `config.json`, `tasks.json`, source images, and masks. Use the manifest format in `CHALLENGE.md`. Add datasets by selecting another directory; add tasks by editing the manifest before the benchmark starts. The loader validates unique IDs, paths contained in the data directory, image dimensions, RGB sources, binary reference masks, and source image IDs/paths separated across splits. Near-duplicate detection and image licensing remain organizer responsibilities.

An optional `allowed_edit_mask` identifies pixels permitted to change, including necessary shadows or replacement boundaries. It must contain the localization target. Localization uses `ground_truth_mask`; preservation uses `allowed_edit_mask` if supplied. Reference masks must contain a target and leave a background for preservation scoring.

Copy the demo configuration and change:

| Setting | Purpose |
| --- | --- |
| `name`, `dataset_version` | Public challenge identity |
| `admin_token` | Private organizer credential, at least 24 characters |
| `teams` | Map of team IDs to distinct, private tokens |
| `weights` | Nonnegative localization/editing/preservation/efficiency weights |
| `reference_time_ms` | Positive reference runtime for the configured hardware |
| `hardware_profile` | Organizer-controlled hardware configuration name |
| `boundary_tolerance` | Boundary matching radius, 0–20 pixels; uses a square neighborhood |
| `max_submissions_per_run` | Accepted task submissions per run; default 100 |
| `max_team_submissions` | Accepted submissions across all runs; default 1000 |
| `max_runs_per_team` | Registered runs per team; default 100 |

A task can be accepted only once per team/run. Use another run ID for a revised experiment. Existing results are preserved on validation or evaluation failures. SQLite transactions protect accepted records. The benchmark manifest, image/mask content, and scoring configuration are fingerprinted: changed benchmarks require a fresh data directory/database, preventing old and new scores from mixing. Keep custom evaluator code and optional model directories immutable for a benchmark version.

The leaderboard uses one selected run per team/split, or the latest registered run if none is selected. It averages tasks within each task type, then task types equally. Missing tasks contribute zero. Ties are resolved by editing, preservation, and verified total runtime. Difficulty and task-type breakdowns are available in the dashboard. Train, validation, and test rankings are separate.

## Semantic editing evaluation

The demo uses an annotated target-color rubric. It measures improvement toward the requested RGB color inside the reference target, assigns an unchanged region zero edit credit, and cannot evaluate object replacement or removal.

For real tasks, provide an organizer-owned callable:

```json
{
  "edit_evaluator": "my_evaluator:score_edit",
  "evaluator_version": "rubric-v1"
}
```

```python
def score_edit(source_image, edited_image, reference_mask, task):
    # Apply your frozen, calibrated task-specific evaluator.
    # Return a finite number in [0, 1].
    ...
```

The callable receives Pillow images and the private task record. It must check actual edit success, use fixed model/prompts/settings, and be validated against human ratings. Load the module on the server's Python import path. This is trusted organizer code; students cannot select evaluation modules through submissions. Color rubrics take precedence for tasks that explicitly carry them. A task without either a color rubric or configured evaluator receives localization/preservation diagnostics but no composite ranking score.

### Optional CLIP and DINOv2 diagnostics

Install the optional dependencies using CPU or CUDA wheels suitable for the worker:

```bash
.venv/bin/pip install torch==2.9.0 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install transformers==4.57.1
```

`requirements-ml.txt` records the optional versions. Provision frozen local model directories before startup, then configure:

```json
{
  "representation_metrics": {
    "clip_directory": "/absolute/path/to/frozen-clip-model",
    "dinov2_directory": "/absolute/path/to/frozen-dinov2-model",
    "device": "cpu"
  }
}
```

Use a standard DINOv2 backbone without register tokens. Model loading is local-only. CLIP diagnostics require `source_description` and `target_description` in each task: comparable before/after descriptions rather than bare editing instructions. They report normalized directional similarity and target alignment. Zero image/text deltas receive directional similarity zero.

DINOv2 diagnostics compare corresponding patch embeddings entirely outside the allowed edit region. The complete image is resized to 224×224 without center cropping; patch-level similarity is therefore a coarse preservation diagnostic. If no complete background patch remains, the value is null. These diagnostics do not change the edit-success score or substitute for text grounding. Implementation follows the [official DINOv2 patch-feature documentation](https://huggingface.co/docs/transformers/model_doc/dinov2) and [CLIP documentation](https://huggingface.co/docs/transformers/model_doc/clip).

## Temporary source-image uploads

Organizers can upload images for students to download without modifying the scored dataset:

- `POST /api/images`: organizer token required; JSON contains `image` (base64-encoded RGB PNG or JPEG) and optional `filename`.
- `GET /api/images`: authenticated students and organizers receive the list of currently available images, their dimensions, expiry times, and download URLs.
- `GET /api/images/{image_id}`: authenticated users download the normalized RGB PNG. Unknown or expired IDs return HTTP 404.

The server allows **60 seconds to receive the entire upload body**, measured from when body reception begins. A timeout returns HTTP 408. A successfully accepted image is downloadable for **300 seconds (5 minutes)** after storage. Repeated downloads and server restarts do not extend this deadline. The deadline controls server access; it cannot revoke a copy a student already downloaded.

These are temporary assets, not scored tasks, and the five-minute window is not an editing/submission deadline. To create an evaluated task, use the dataset manifest with prompts and a private reference mask as described above. The original task-image routes retain their existing availability.

Example upload with `CHALLENGE_TOKEN` set to the organizer token:

```python
import base64
from pathlib import Path
from challenge.client import Client

client = Client('http://127.0.0.1:8000')
result = client.request('/api/images', {
    'filename': 'source.png',
    'image': base64.b64encode(Path('source.png').read_bytes()).decode(),
})
print(result['image_url'], result['expires_at'])
```

Student download with `CHALLENGE_TOKEN` set to a team token:

```python
from pathlib import Path
from challenge.client import Client

client = Client('http://127.0.0.1:8000')
for image in client.request('/api/images'):
    Path(image['image_id'] + '.png').write_bytes(
        client.request(image['image_url'], binary=True)
    )
```

Images and expiry timestamps persist in SQLite. Expired rows are removed when the image API is used. Active temporary storage is limited to 100 images and 256 MiB; decoded images retain the existing 16-million-pixel limit. Source uploads accept single-frame RGB PNG/JPEG, while predicted masks and edited submissions still require PNG. No new dependencies are needed.

## API

All `/api/` routes require `Authorization: Bearer TOKEN`. The dashboard shell is public. POST requests require `Content-Type: application/json`; request bodies are bounded to 32 MB, decoded source/output images to 16 million pixels, and metadata to 16 KB. PNG dimensions and modes must match exactly. Non-finite timing values are rejected.

| Method | Route | Behavior |
| --- | --- | --- |
| POST | `/api/images` | Organizer source upload; 60-second receive deadline |
| GET | `/api/images` | List unexpired temporary images |
| GET | `/api/images/{image_id}` | Download within the five-minute availability window |
| GET | `/api/config` | Public configuration and authenticated identity |
| GET | `/api/tasks?split=validation` | Public task records; no private rubric or annotation paths |
| GET | `/api/tasks/{task_id}/image` | Source PNG |
| GET | `/api/tasks/{task_id}/mask` | Public reference mask; test requires organizer token |
| POST | `/api/runs` | Register a run; organizer-only `mode: measured` |
| POST | `/api/submissions` | Accept/evaluate an uploaded result |
| POST | `/api/measured-submissions` | Organizer-only result with measured runtime/profile |
| GET | `/api/submissions` | Own experiments, or all for organizers |
| GET | `/api/submissions/{id}/edited` | Authorized edited artifact |
| GET | `/api/submissions/{id}/mask` | Authorized predicted-mask artifact |
| POST | `/api/select-run` | Select a run using `run_id` and `split` |
| GET | `/api/leaderboard?split=validation&mode=quality` | Selected-run quality leaderboard |
| GET | `/api/leaderboard?split=validation&mode=measured` | Organizer-measured leaderboard |

Test submission responses and student experiment history omit per-task metrics. Test masks are organizer-only. Aggregate test leaderboards remain visible to authenticated participants. Artifact access is restricted to the owning team and organizers. Test masks are not exposed through static serving or arbitrary file routes.

The HTTP server binds to loopback by default and is intended for local/course deployment behind a configured HTTPS reverse proxy. Set submission limits appropriately before final testing; leaderboard feedback on a small test set can reveal information through repeated queries. Add an institutional authentication layer, operational backups, and a final submission deadline when deploying for a course. No service is published externally by this project.

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
```

Tests cover perfect and unchanged edits, localization edges, context preservation, invalid uploads, ownership, private test annotations, persistence, frozen benchmark configuration, missing-task penalties, measured-vs-upload ranking, the HTTP workflow, and the inference contract. When optional ML dependencies are installed, tiny randomly initialized local CLIP and DINOv2 models test the real adapter APIs, patch layout, zero-direction policy, and background aggregation without downloading pretrained weights. These checks verify implementation contracts, not semantic metric quality.
