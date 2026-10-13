# Advanced Machine Learning Challenge: Semantic Image Editing with DINOv2

## Your task

Build a system that identifies a region of an image from a natural-language description, edits that region according to a second instruction, and preserves the surrounding scene.

Each task provides a source image, a source prompt identifying the region to edit, and a target prompt specifying the transformation. Return an edited image and a predicted localization mask at the original image resolution.

For example, given a photograph of a red car, a dog, and a tree:

- Source prompt: “The red car on the left side of the image.”
- Target prompt: “Replace the red car with a blue sports car.”
- Expected result: the specified car becomes a blue sports car while the dog, tree, background, lighting, and scene composition remain consistent.

The challenge evaluates semantic localization, edit success, context preservation, and computational efficiency. Strong solutions must balance all four: returning an unchanged image preserves the background but fails the requested edit.

## Learning objectives

Investigate how DINOv2 patch representations support dense correspondence, region similarity, object localization, and preservation of visual context. Combine these representations with text-image alignment, segmentation, or generative editing as needed.

DINOv2 is a visual representation model. It does not by itself provide natural-language grounding or generate edited images. Explain the role of each model in your pipeline and how information passes between localization and editing.

Include a controlled comparison of your system with and without its DINOv2 component. Keep the data, editing model, compute budget, and evaluation procedure comparable so the experiment measures the contribution of those features.

## Tasks and data

| Task type | Source prompt | Target prompt |
| --- | --- | --- |
| Object replacement | The dog sitting next to the car | Replace the dog with a cat |
| Attribute modification | The red car in the foreground | Change its color to blue |
| Object removal | The person standing behind the bicycle | Remove the person and reconstruct the background |
| Spatial reasoning | The leftmost bird on the branch | Replace it with a butterfly |
| Texture editing | The wooden table in the center | Transform its surface into marble |
| Fine-grained editing | The hat worn by the person on the right | Change the hat to green |

The dataset should cover multiple objects, similar object categories, small and occluded targets, varied scales, complex backgrounds, and spatial relationships. Challenging referring expressions must still identify an annotatable target. Organizers should resolve genuinely ambiguous samples or annotate acceptable alternatives before scoring them.

Each organizer-side record follows this schema:

```json
{
  "task_id": "task_0001",
  "image_id": "image_0001",
  "source_image": "images/image_0001.png",
  "source_prompt": "The red car on the left",
  "target_prompt": "Replace the red car with a blue sports car",
  "task_type": "object_replacement",
  "difficulty": "medium",
  "split": "train",
  "ground_truth_mask": "masks/task_0001.png",
  "metadata": {
    "image_width": 1024,
    "image_height": 1024,
    "num_objects": 5
  }
}
```

Use task-specific mask filenames because different tasks may refer to different objects in the same image. Images are RGB; reference masks are binary and have the same width and height as their source image. Include image provenance and permitted usage in the dataset documentation.

### Splits

- **Training:** public images, prompts, and localization masks for development.
- **Validation:** public examples and reference annotations for reproducible local evaluation.
- **Test:** public task inputs with private reference masks and any private edit-success annotations.

Split by source image and group near duplicates together to prevent leakage across partitions. Do not train on test tasks or manually edit final test outputs. Declare pretrained models, external data, and any additional annotations used.

Publish the scoring formula, preprocessing, metric versions, and submission rules before the challenge begins. Keep test annotations private; hidden scoring rules would make results difficult to interpret.

## Student workflow

1. Obtain a task from the challenge server.
2. Download its image and localize the source prompt.
3. Generate the edit using the predicted region and target prompt.
4. Submit the predicted mask, edited image, and experiment metadata.
5. Inspect validation feedback, record experiments, and improve your method.

A public task response contains:

```json
{
  "task_id": "task_0001",
  "image_url": "/images/image_0001.png",
  "source_prompt": "The red car on the left",
  "target_prompt": "Replace the red car with a blue sports car"
}
```

The predicted mask represents confidence that each pixel belongs to the target region, with values in [0, 1]. Submit it as an 8-bit grayscale PNG, where 0 means background and 255 means target. The evaluator thresholds it at 128 for binary localization metrics. Submit the edited image as an RGB PNG at the source resolution.

A submission contains:

```json
{
  "task_id": "task_0001",
  "student_id": "team_01",
  "predicted_mask": "base64_encoded_png",
  "edited_image": "base64_encoded_png",
  "metadata": {
    "run_id": "experiment_001",
    "model_name": "custom_dinov2_editor",
    "seed": 42,
    "localization_time_ms": 350,
    "editing_time_ms": 4200
  }
}
```

The authenticated team identity must match the submission identity. Malformed images, incorrect dimensions, unknown tasks, and non-finite or negative timings are rejected. A rejected submission does not replace a previously accepted result.

## Evaluation

Report all four dimensions individually alongside the composite score. Use the reference mask for preservation metrics; a participant cannot improve preservation scores by submitting an oversized mask.

### 1. Semantic localization

For the thresholded predicted mask P and reference mask G:

```text
IoU       = |P ∩ G| / |P ∪ G|
Dice      = 2 |P ∩ G| / (|P| + |G|)
Precision = |P ∩ G| / |P|
Recall    = |P ∩ G| / |G|
```

The primary localization score is IoU. Also report Dice, precision, recall, boundary F1, and success rates at IoU thresholds 0.25, 0.50, and 0.75. Publish the boundary tolerance in pixels or relative to image size.

Reference target masks must be nonempty. An empty prediction receives zero for these localization measures, including precision. Organizers should exclude invalid reference annotations before evaluation.

Validation visualizations show source images, predicted masks, reference masks, and overlays. Test feedback must not expose reference masks or private annotations.

### 2. Editing accuracy

Evaluate whether the requested change occurred at the intended location. Use a frozen, versioned semantic evaluator with task-specific rubrics, and validate its judgments against human ratings on a representative subset.

Possible supplementary measurements include text-image alignment, directional CLIP similarity, region-level visual similarity, and vision-language model judgments. Directional similarity compares:

```text
image_delta = image_embedding(edited) - image_embedding(source)
text_delta  = text_embedding(target_description) - text_embedding(source_description)
directional_similarity = cosine(image_delta, text_delta)
```

The text inputs should be comparable descriptions of the region before and after editing. Raw instructions such as “remove it” are not reliable target descriptions. Define a zero-vector policy before evaluation; an unchanged image must not receive directional edit credit.

Text-image alignment alone does not establish successful editing. Check replacement identity, requested attributes, correct instance selection, or removal and plausible background reconstruction according to task type. Score these checks on a published scale normalized to [0, 1]. Freeze model versions, prompts, and generation settings used by the evaluator.

DINOv2 similarity can help measure structure and correspondence, but cannot alone verify every text-directed change. Do not present it as a complete edit-success metric.

### 3. Context preservation

For RGB images normalized to [0, 1], compute background mean absolute error:

```text
background_MAE = sum((1 - G) * abs(edited - source)) / (3 * sum(1 - G))
preservation_score = 1 - background_MAE
```

Broadcast the mask across RGB channels. Evaluate at the original resolution. Require a nonempty background for this metric; flag full-image edits separately rather than divide by zero.

Some replacements and removals require changes immediately around the original object, including its boundary or shadow. Annotate an allowed edit region when needed. Use that region consistently for preservation while retaining the original object mask for localization. Publish this distinction and the annotation protocol.

Report optional perceptual and structural metrics separately. Masked LPIPS or SSIM requires an explicit spatial reduction protocol; blacking out the target and applying a whole-image metric can introduce boundary artifacts.

### 4. Computational efficiency

Measure localization time, editing time, total inference time, and peak GPU memory on standardized hardware. Record hardware, precision, batch size, resolution, software versions, and model-loading policy. Synchronize GPU execution before timing and specify whether preprocessing and output encoding are included.

The preferred final evaluation runs submitted code on organizer hardware. Start timing at task ingestion and stop after image and mask generation. Record model initialization separately. Enforce a published timeout and memory budget.

For an upload-only server, student timings are descriptive and unverified. HTTP upload latency is not inference time. Do not award efficiency points from unverified reports; use a separate provisional quality leaderboard until organizer-side execution is available. Hardware-specific leaderboards are acceptable when standardized execution is unavailable.

A proposed efficiency score is:

```text
efficiency_score = min(1, reference_time_ms / measured_total_time_ms)
```

Choose and publish the positive reference time from a baseline measured on the same hardware. Treat timeouts and failed executions as unsuccessful tasks. Report memory independently and enforce its budget rather than silently folding it into a time score.

## Ranking

Normalize each dimension to [0, 1] and use the proposed weights:

```text
total_score = 0.30 * localization_score
            + 0.30 * editing_score
            + 0.25 * preservation_score
            + 0.15 * efficiency_score
```

Freeze weights and normalization before final testing. For the provisional upload-only quality leaderboard, omit efficiency and divide the remaining weighted sum by 0.85. Label that ranking clearly.

Evaluate one selected run per team on the same full task set. Missing tasks, timeouts, and failed outputs contribute zero to the run score. Average task scores within each task type, then average equally across task types so common categories do not dominate. Report difficulty breakdowns and the number of completed tasks. Resolve exact ties using edit-success score, then preservation score, then measured total runtime where available.

Set validation submission limits and a final submission deadline before launch. Keep test feedback aggregated to reduce annotation leakage through repeated queries.

## Deliverables

Submit:

- Source code and a reproducible environment with pinned model and library versions.
- An inference entry point accepting a task and producing its edited image and predicted mask.
- A selected final run covering every evaluation task.
- A report describing architecture, DINOv2 usage, external data, experiments, failure cases, and compute requirements.
- A controlled DINOv2 ablation and a baseline comparison on validation data.

Your inference must run without manual intervention. Declare network and external service requirements; final evaluation should use locally available, fixed model artifacts wherever possible.

## Platform requirements for organizers

The platform implementation should provide:

- A versioned dataset manifest and split-aware task API that never exposes test annotation paths or files.
- Authenticated submissions, bounded payloads and decoded image sizes, dimension validation, and durable experiment records.
- An evaluation worker that records metric configuration, evaluator versions, failures, and per-task results.
- Run-level leaderboards, task-type and difficulty breakdowns, and timing and memory comparisons.
- A validation dashboard displaying image pairs, mask overlays, difference maps, and experiment comparisons.
- A private organizer view for test annotations and evaluation audits.
- A reproducible runner for organizer-measured performance, with execution isolation and resource limits.

Adding datasets should require a compatible manifest and evaluator configuration rather than changes to core submission logic. Persist artifacts privately and serve only authorized public assets. Never execute participant code inside the public API process.

## Launch checklist

Before opening submissions, organizers must supply licensed data, verified masks, an edit-success annotation rubric, evaluator calibration results, fixed hardware budgets, final deadlines, and submission limits. Validate metrics using unchanged images, deliberately wrong edits, oversized masks, missing tasks, malformed uploads, and known successful edits.

This document defines the challenge and its platform requirements. The local implementation and synthetic demo are described in [README.md](README.md). A research dataset, trained editor, and calibrated general semantic evaluator still need to be supplied by organizers or students.
