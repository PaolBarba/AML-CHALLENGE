# Semantic Image Editing Lab

A local challenge platform for the [Advanced Machine Learning challenge](CHALLENGE.md): authenticated tasks and submissions, SQLite experiment tracking, localization and preservation metrics, configurable edit evaluation, run selection, leaderboards, and image comparisons.

## Run it

For a hosted deployment, see [DEPLOYMENT.md](DEPLOYMENT.md).

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

## FastAPI reference server

An alternative API entry point for the backpack download/upload workflow is `challenge/api.py`:

```bash
.venv/bin/pip install -r requirements-api.txt
.venv/bin/python -m uvicorn challenge.api:app --host 127.0.0.1 --port 8000
```

Stop the original server before starting this alternative. Use one process per dataset, without multiple workers. It uses the existing `.challenge/config.json` team tokens and SQLite records, preserves timers and batches, and refreshes Excel after uploads. Set `CHALLENGE_DATA=/path/to/dataset` to select another dataset. The dataset must already be initialized.

The FastAPI reference workflow uses **GET `/api/reference/json`** to load the image and its batch ID, and **POST `/api/reference/submissions`** to upload the edited image for that batch. Both use the team token. Authenticated `GET /api/reference/leaderboard` returns the best scored batch per team. The download returns HTTP 423 with the countdown during the wait; retry the same endpoint when it opens. Excel continues to update locally at `.challenge/results.xlsx`.

Open **http://127.0.0.1:8000/docs**, click **Authorize**, enter your team token, and use **Try it out**. Upload JSON contains `batch_id` and the base64 `edited_image`. Existing curl requests for these two endpoints work unchanged. Config, separate timer/image routes, health, and Excel download routes are not exposed by this FastAPI app.

This entry point provides the reference workflow and interactive API docs; use `challenge.server` for the full scored-task dashboard. Do not name a local file `fastapi.py`, because it shadows the installed package. Run its in-process HTTP tests with `.venv/bin/python -m unittest discover -s tests -p test_api.py -v`. The test lifecycle follows the [FastAPI testing documentation](https://fastapi.tiangolo.com/advanced/testing-events/).

## Student reference download

With the API running, open another terminal in the repository root:

```bash
export CHALLENGE_TOKEN='YOUR_TEAM_TOKEN'
python3 -m challenge.download_reference
```

The script waits through HTTP 423 locked windows, then saves `source.png` and
`reference.json` (including the `batch_id` needed for submission) inside
`reference-download/`. Press Ctrl+C to cancel waiting. Existing output folders
are never overwritten. For a remote server or another download:

```bash
python3 -m challenge.download_reference --url https://challenge.example.org --output download-2
```

Only the Python standard library is needed for this download command. Keep your
token private and retain `reference.json` alongside the downloaded image.

## Student edited-image upload

Save your edit as an RGB PNG with the same dimensions as `source.png`, then use
its saved batch and the same team token to submit:

```bash
export CHALLENGE_TOKEN='YOUR_TEAM_TOKEN'
python3 -m challenge.upload_reference edited.png --url http://127.0.0.1:8000
```

For another download folder, add `--reference download-2/reference.json`.
Set `--url` to the same server used for downloading. The upload script defaults
to `http://127.0.0.2:8000`, matching the current download script. Direct execution
also works: `python3 challenge/upload_reference.py edited.png --url http://127.0.0.1:8000`.
The server validates the image and batch ownership; the command prints its JSON
response, including `status: accepted` on success.

## Mask-free reference evaluation

Reference uploads now use PSNR, LPIPS, MSE, SSIM, CLIP similarity, and DINO
structure distance. Students upload only the edited RGB PNG and its batch ID.
No predicted or organizer mask is used for these reference metrics.

Install the API dependencies in your Python 3.11+ environment and create a new
mask-free demo (previous datasets and submissions are retained):

```bash
python3 -m pip install -r requirements-api.txt
python3 -m challenge.reference_demo
CHALLENGE_DATA=.challenge-reference-v2 python3 -m uvicorn challenge.api:app --host 127.0.0.1 --port 8000
```

Stop the old API process first. Retrieve the new team token privately from
`.challenge-reference-v2/config.json`. Download a fresh batch to a new folder,
make your edit, then submit and inspect the leaderboard:

```bash
export CHALLENGE_TOKEN='NEW_TEAM_TOKEN'
python3 -m challenge.download_reference --url http://127.0.0.1:8000 --output backpack-download-v2
python3 -m challenge.upload_reference edited.png --reference backpack-download-v2/reference.json --url http://127.0.0.1:8000
curl -sS http://127.0.0.1:8000/api/reference/leaderboard -H "Authorization: Bearer $CHALLENGE_TOKEN"
```

The download includes the instruction “Change the blue backpack fabric to red,
preserving the straps and background.” Edited images must have the original
image dimensions. SQLite retains the source used for each batch, accepted edit,
and metrics. `.challenge-reference-v2/results.xlsx` refreshes on every acceptance
and contains **Reference uploads** and **Reference leaderboard**.

The API validates and saves uploads without loading reference models or computing
metrics. Accepted uploads return `scoring_status: pending` and `metrics: null`.
Run the separate evaluation command below to write scores, refresh Excel, and
update the leaderboard. Workbook failures return `excel_updated: false` without
losing the upload.

| Field | Definition | Better |
| --- | --- | --- |
| `mse` | Mean squared RGB error with pixel values normalized to [0, 1] | Lower |
| `psnr` | `10 * log10(1 / mse)`, in dB | Higher |
| `ssim` | Mean RGB structural similarity, data range 1, up to 7x7 windows | Higher |
| `lpips` | Pretrained AlexNet LPIPS v0.1 perceptual distance | Lower |
| `clip_similarity` | Cosine of edited-image and target-prompt CLIP embeddings | Higher |
| `structure_distance` | Mean squared difference between DINOv2 patch self-similarity matrices | Lower |

**Preservation is evaluated over the whole image.** Without an edit-region
annotation, the evaluator cannot distinguish intended changes from unintended
changes. It does not report these values as measurements of only unedited
regions. CLIP alignment is a proxy, not proof that every part of an instruction
was satisfied; these metrics do not directly measure aesthetics or naturalness.

Identical images have infinite PSNR: JSON represents it as `psnr: null` with
`psnr_infinite: true`, while Excel displays `Infinity`. SSIM is null for images
smaller than 3 pixels along either axis. LPIPS uses the complete frame resized
so each dimension is between 64 and 512 pixels (aspect ratio is preserved unless
a short dimension needs resizing to 64). DINOv2 uses the existing
224x224 full-frame patch extractor, without center cropping. Define
`S = normalize(patch_features) @ normalize(patch_features).T`; structure distance
is `mean((S_original - S_edited)^2)`.

The leaderboard uses each team's best batch. It sorts by CLIP similarity
(descending), then SSIM (descending), LPIPS, structure distance, and MSE
(ascending), then acceptance time and deterministic identifiers. Missing tie
metrics sort last. The API's `score` field aliases raw CLIP similarity; the six
raw metrics are retained separately, without combining incompatible scales.
The reference leaderboard is separate from the dashboard's task/run leaderboard.

### Missing dataset configuration

If `.challenge/config.json` is missing, restore the original dataset from backup
or initialize a fresh directory. Initialization creates new team tokens; it does
not recover previous uploads. Preserve the remaining files in `.challenge`.

```bash
python3 -m challenge.reference_demo --data .challenge-uploads
CHALLENGE_DATA=.challenge-uploads python3 -m uvicorn challenge.api:app --host 127.0.0.1 --port 8000
```

Use the token from `.challenge-uploads/config.json` and download a new batch.
Then evaluate with `--data .challenge-uploads`, matching the API data directory.
`CHALLENGE_EVALUATION_CONFIG` is no longer used by the API.

### Evaluate with Slurm

Stop the API before submitting (SQLite uses rollback journals for shared-filesystem
access across Slurm nodes), activate your Python 3.11+ environment containing the dependencies
in `requirements-ml.txt`, and submit from the project directory:

```bash
sbatch evaluate_reference.sbatch
```

The job uses the `lrd_all_serial` CPU partition, matching `device: cpu` in the
CLIP configuration. It evaluates `.challenge-uploads` and writes its progress to
`reference-evaluation-JOBID.log`. Scores, Excel, and the leaderboard are updated
in the same data directory. The activated environment is inherited by the job;
model files must be accessible on the compute node. No packages or models are
downloaded by the job. If required by your allocation, add
`--account=YOUR_SLURM_ACCOUNT` to the `sbatch` command.

To evaluate a different API dataset or model configuration:

```bash
sbatch evaluate_reference.sbatch .challenge-other reference-evaluation.clip.json
```

### Evaluate accepted batches after teams upload

Run the organizer evaluation command against the dataset that actually received
the uploads. Stop its API process first so only one process owns the workbook:

```bash
python3 challenge/evaluate_reference.py --data .challenge-reference-v2 --evaluation-config reference-evaluation.clip.json
```

Module execution also works: `python3 -m challenge.evaluate_reference` with the
same arguments. For uploads received by the CLIP-enabled server, change `--data`
to `.challenge-reference-clip`. Use your Python 3.11+ environment with PyTorch
and Transformers installed. No student token is needed for this local organizer
command; it reads the private server database directly.

The command defaults to `CHALLENGE_DATA` when set, otherwise `.challenge`, matching
the FastAPI server. If uploads were received by the original API dataset without
a configured reference task, provide the editing instruction explicitly:

```bash
python3 challenge/evaluate_reference.py --data .challenge --target-prompt "Change the blue backpack fabric to red, preserving the straps and background."
```

The script evaluates every accepted batch against its stored original image and
the dataset's target prompt. CLIP similarity measures correspondence to the
prompt; MSE, PSNR and SSIM measure correspondence to the original, with optional
LPIPS and DINO metrics when configured. No mask or scikit-image is used.
It updates the batch metrics in SQLite, refreshes `results.xlsx` in that dataset,
and updates the reference leaderboard. Downloaded batches without an accepted
edit are skipped. It recomputes all accepted batches on each run so results use
the same evaluator; scores are committed together only after every evaluation
succeeds. A failed evaluation leaves previous scores intact. If the API already
configures learned evaluation, the supplied configuration must match it.

This command can add offline CLIP results to `.challenge-reference-v2` without
changing its frozen API configuration. Later uploads remain pending and are included when you run the organizer evaluation again. The API's
reference leaderboard reads the updated scores after restart. Review the Excel
**Reference uploads** sheet for all batch metrics and **Reference leaderboard**
for each team's best result.

### Use the supplied local CLIP checkpoint

`reference-evaluation.clip.json` points to
`/leonardo_scratch/fast/IscrC_SteFi/models/clip-vit-base-patch32` and records the
SHA256 of its model weights. In your Python 3.11+ environment with the API and
PyTorch/Transformers dependencies installed, create a separate dataset once:

```bash
python3 -m challenge.reference_demo --data .challenge-reference-clip --evaluation-config reference-evaluation.clip.json
CHALLENGE_DATA=.challenge-reference-clip python3 -m uvicorn challenge.api:app --host 127.0.0.1 --port 8000
```

If that dataset already exists, run only the server command. Use its team token
from `.challenge-reference-clip/config.json`, download a fresh batch into a new
folder, and upload the edit using the existing student commands. CLIP similarity
now enables ranking, while unavailable LPIPS and DINO metrics stay blank.
No scikit-image package is required; SSIM uses NumPy integral-image window means.

### Configure learned metrics when checkpoints are available

Install `requirements-ml.txt` with appropriate CPU/CUDA wheels. In a **new**
dataset, configure `reference_evaluation` before starting the server. The demo
initializer accepts a JSON file via `--evaluation-config evaluation.json`:

```json
{
  "clip_directory": "/absolute/path/to/local-clip",
  "dinov2_directory": "/absolute/path/to/local-dinov2",
  "lpips_checkpoint": "/absolute/path/to/lpips-alex-complete.pth",
  "model_version": "frozen-clip-dino-lpips-revisions",
  "device": "cpu"
}
```

You can omit models that are not yet available; their metrics stay null. CLIP
and DINOv2 must be complete Transformers-format checkpoints. LPIPS must contain
both the ImageNet-trained AlexNet backbone and perceptually calibrated linear
layers, not only the small calibration weights shipped with the package. On a
machine where downloading pretrained weights is explicitly intended, prepare
that complete checkpoint once:

```python
import lpips
import torch

torch.save(lpips.LPIPS(net="alex").state_dict(), "lpips-alex-complete.pth")
```

That preparation may download AlexNet weights. Server evaluation loads local
weights only; it never downloads missing weights or substitutes random models.
Keep checkpoint files and their recorded revisions fixed throughout the challenge.
Changing evaluator configuration requires a new results dataset so scores remain
comparable. CLIP text uses the checkpoint's token limit; long prompts are truncated.
Pixel metrics, including windowed SSIM, use NumPy only. Learned metrics follow
[LPIPS](https://github.com/richzhang/PerceptualSimilarity), and the existing CLIP/DINOv2 adapters.

## Give students access

Create one token per team (or use an individual student ID for individual work):

```bash
.venv/bin/python -m challenge.server add-team team_01
.venv/bin/python -m challenge.server add-team team_02
```

Run provisioning commands one at a time, then restart the server. For another dataset, put `--data /path/to/dataset` before `add-team`. The command prints the newly generated token and saves it in the private dataset `config.json` with owner-only permissions. An existing team is rejected without changing its token or results. `.env` only configures the deployment hostname.

Privately give each team its token and server URL. Students can paste the token into the dashboard's connection form, or use it in an API request:

```bash
export CHALLENGE_TOKEN='TOKEN_GIVEN_BY_THE_INSTRUCTOR'
curl --fail 'http://127.0.0.1:8000/api/tasks?split=validation' \
  -H "Authorization: Bearer $CHALLENGE_TOKEN"
```

Students on another computer must use the reachable server URL instead of `127.0.0.1`. A team token permits access to all public task records and source images, submissions under that team's identity, and its own submission artifacts. It does not grant organizer access or access to private test masks. Tokens do not currently expire or restrict a team to an individual task. Never distribute the organizer token or the full configuration file.

## Timed backpack reference

The dashboard serves `data/image.png` through a token-protected reference panel. Each team's first access check starts a repeating cycle: **30 seconds locked, then 30 seconds available**. A countdown and **Load reference image** button show the current window. The preview disappears when access closes. Reloading the page, opening another tab with the same token, or restarting the server does not reset the cycle; its start time is stored in SQLite.

- `GET /api/reference`: returns `available`, `seconds_remaining`, `server_time`, `next_change_at`, and `image_url`.
- `GET /api/reference/image`: returns the sample PNG during the open window, or HTTP **423** with timing information during the wait.
- `GET /api/reference/json`: returns the image as a base64 `image` string together with `reference_id`, `filename`, `content_type`, `encoding`, `image_width`, `image_height`, and the timing fields in one JSON response. The same token and availability rules apply; locked responses contain no image.
- All reference endpoints require `Authorization: Bearer TOKEN`. Responses use `Cache-Control: no-store`. Organizers follow the same timing rule.

```bash
curl --fail 'http://127.0.0.1:8000/api/reference' \
  -H "Authorization: Bearer $CHALLENGE_TOKEN"
# During the available window:
curl --fail 'http://127.0.0.1:8000/api/reference/image' \
  -H "Authorization: Bearer $CHALLENGE_TOKEN" -o reference.png
```

The timer controls new downloads and the dashboard preview; it cannot revoke saved copies. The default sample provides pixel preservation metrics. The mask-free reference demo supplies an editing instruction; local learned checkpoints enable LPIPS, CLIP alignment, and DINO structure distance. Existing scored tasks and temporary image uploads keep their own availability rules.

To retrieve the complete reference JSON during an open window:

```bash
curl --fail 'http://127.0.0.1:8000/api/reference/json' \
  -H "Authorization: Bearer $CHALLENGE_TOKEN" -o reference.json
```

Decode the downloaded image using Python:

```python
import base64
import json
from pathlib import Path

reference = json.loads(Path('reference.json').read_text())
Path('reference.png').write_bytes(base64.b64decode(reference['image']))
```

HTTP 401 means the token is missing or invalid. HTTP 423 means wait for `seconds_remaining` and retry. The JSON bundle contains the viewing reference and timing metadata; it does not expose the private `config.json` or organizer-side `tasks.json`. Public scored-task instructions are available separately at `GET /api/tasks?split=validation`.

### Upload an edit of the downloaded reference batch

Download a fresh `reference.json` using `GET /api/reference/json`; it now includes a server-issued `batch_id` bound to your team and reference window. Older downloads without `batch_id` must be downloaded again. Repeated downloads within the same window return the same batch ID; the next available window issues a new batch.

After editing the image, send an RGB PNG at the original resolution using the **same team token**:

```python
import base64
import json
from pathlib import Path
from challenge.client import Client

reference = json.loads(Path('reference.json').read_text())
result = Client('http://127.0.0.1:8000').request('/api/reference/submissions', {
    'batch_id': reference['batch_id'],
    'edited_image': base64.b64encode(Path('edited.png').read_bytes()).decode('ascii'),
})
print(result)
```

Set `CHALLENGE_TOKEN` before running this code. The API accepts one edit per issued batch and rejects unknown batches, another team's batches, wrong dimensions, invalid images, and repeated uploads. Uploads can arrive after the download window closes. An issued batch establishes ownership and source identity; it cannot prove how a student generated an edit.

Accepted edits persist in SQLite and appear in the **Reference uploads** worksheet in `results.xlsx`. The response is HTTP 201 with `status: accepted`. The server saves the edit with `scoring_status: pending`. The separate evaluation script computes metrics and refreshes Excel and the reference leaderboard. No predicted mask is required. The existing scored-task submission API remains separate.

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

## Local image APIs and Excel results

1. Start the local server with `.venv/bin/python -m challenge.server serve`.
2. A team lists `GET /api/tasks?split=validation`, then downloads each task's `image_url`.
3. The team sends `POST /api/submissions` with the task ID, edited RGB PNG, grayscale localization mask, and run ID. Images are base64 strings in JSON.
4. The server evaluates the submission and saves its metrics. It automatically refreshes `.challenge/results.xlsx` (or `results.xlsx` in your `--data` directory).

Example participant code, with `CHALLENGE_TOKEN` set to the team's token:

```python
import base64
from pathlib import Path
from challenge.client import Client

client = Client('http://127.0.0.1:8000')
task = client.request('/api/tasks?split=validation')[0]
Path('source.png').write_bytes(client.request(task['image_url'], binary=True))
# Run your model using source.png, task['source_prompt'], and task['target_prompt'].
# Write edited.png (RGB) and mask.png (grayscale), both at source resolution.
result = client.request('/api/submissions', {
    'task_id': task['task_id'],
    'edited_image': base64.b64encode(Path('edited.png').read_bytes()).decode(),
    'predicted_mask': base64.b64encode(Path('mask.png').read_bytes()).decode(),
    'metadata': {'run_id': 'experiment_001', 'model_name': 'my_editor'},
})
print(result)
```

The workbook has **Team rankings** (selected runs, all splits, quality and measured modes) and **Submissions** (every accepted result and metric). It includes IoU, Dice, precision, recall, boundary F1, localization success thresholds, background MAE, preservation, edit success, efficiency when measured, composite score, and any enabled representation diagnostics. Scores use the existing challenge rules; unavailable metrics remain blank. Incomplete runs retain missing-task penalties in the rankings.

SQLite remains the authoritative database. Excel is an automatically regenerated results snapshot; manual workbook edits are overwritten. Run one server per data directory. Updates occur on server startup, run registration, submissions, and run selection. If a workbook write fails, the submission remains accepted in SQLite and its response includes `excel_updated: false`; the server logs the failure. Close a locked workbook and retry the organizer export to rebuild it.

With an organizer token, download a fresh workbook using the dashboard's **Download Excel results** button or `GET /api/results.xlsx`. This endpoint includes all teams and private test metrics, so team tokens receive HTTP 403. For example, with `CHALLENGE_TOKEN` set to the organizer token:

```python
from pathlib import Path
from challenge.client import Client

Path('team-results.xlsx').write_bytes(
    Client('http://127.0.0.1:8000').request('/api/results.xlsx', binary=True)
)
```

## API

All `/api/` routes require `Authorization: Bearer TOKEN`. The dashboard shell is public. POST requests require `Content-Type: application/json`; request bodies are bounded to 32 MB, decoded source/output images to 16 million pixels, and metadata to 16 KB. PNG dimensions and modes must match exactly. Non-finite timing values are rejected.

| Method | Route | Behavior |
| --- | --- | --- |
| POST | `/api/images` | Organizer source upload; 60-second receive deadline |
| GET | `/api/images` | List unexpired temporary images |
| GET | `/api/images/{image_id}` | Download within the five-minute availability window |
| GET | `/api/config` | Public configuration and authenticated identity |
| GET | `/api/results.xlsx` | Organizer-only Excel export of team rankings and submission metrics |
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

### Reference Excel layout

For reference datasets, `results.xlsx` contains two sheets:

- **Reference uploads**: Team ID, Batch ID, PSNR, LPIPS, MSE, SSIM, CLIP similarity, and structure distance.
- **Team totals**: Team ID and the cumulative sum of each metric across that team's accepted batches.

Metric names identify the score columns. Missing scores stay blank and do not
contribute to sums; identical images produce `Infinity` for PSNR, including in
totals. Metrics are summed separately because their scales and directions differ.
Team totals do not change the API's best-batch leaderboard ranking. The workbook
is regenerated on upload or evaluation, so reruns do not double-count batches.
