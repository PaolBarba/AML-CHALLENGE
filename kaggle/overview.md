# Semantic Image Editing with DINOv2

Build a system that identifies an image region from a natural-language description,
edits that region according to a second instruction, and preserves the surrounding
scene.

For example, given an image containing a red car, a dog, and a tree:

- Source prompt: "The red car on the left side of the image."
- Target prompt: "Replace the red car with a blue sports car."
- Desired result: the specified car changes while the dog, tree, and surrounding
  scene remain consistent.

## Learning objectives

Investigate how DINOv2 patch representations support localization, correspondence,
and context preservation. DINOv2 does not itself provide text grounding or generate
edits; explain how your pipeline combines it with other models. Include a
controlled comparison with and without DINOv2, keeping the dataset, editing model,
compute budget, and evaluation procedure comparable.

## Task inputs and outputs

Each task provides an RGB source image, a source prompt identifying the target,
and a target prompt describing the edit. Your pipeline produces an RGB edited
image and an 8-bit grayscale localization mask at the source resolution.

Training and validation reference masks are provided for development. Test
reference annotations remain private. Split images and near duplicates together
to avoid leakage. Declare pretrained models, external data, and annotations.
Final outputs must be generated without manual editing.

## Reproducibility

Provide source code, pinned dependencies and model versions, inference
instructions, and a report covering architecture, DINOv2 usage, baseline and
ablation results, failure cases, and compute requirements.

## Judged project submissions

Submit a Kaggle Writeup linking reproducible code and complete edited-image and
mask artifacts. Judges assess localization, editing, preservation, and experimental
evidence using the published rubric. There is no automatic CSV prediction score.
Use the accompanying submission instructions and writeup template.

## Organizer draft — resolve before publishing

The judged project format is selected. The proposed judging rubric needs host
review; dataset release, dates, and team limits still need to be finalized.
The repository's six synthetic color-edit examples are workflow fixtures, not the
real competition benchmark. Do not publish this draft as an open competition
until the evaluation and data are ready.
