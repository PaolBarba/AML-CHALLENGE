# Project submission instructions

Submit one final Kaggle Writeup per team through the competition's Writeups flow.
Include accessible links to a fixed source-code revision or versioned notebook,
pinned environment and model versions, complete output archive, and a report.
Include a baseline comparison, controlled DINOv2 ablation, and failure analysis.

Arrange outputs by the supplied task identifiers:

```text
outputs/
  task_id/
    edited.png
    mask.png
    metadata.json
```

The edit must be RGB and the mask 8-bit grayscale, both at source resolution.
Mask values represent target confidence from 0 to 255. Metadata records model
identity, seed, and available timings/memory; label self-reported measurements.
Include a manifest of task IDs and file hashes to identify the submitted version.

Your inference command must accept `--input TASK_JSON --output OUTPUT_DIRECTORY`
and generate the three files without manual intervention. Give exact setup and
inference commands, fixed model-weight locations, and external dependencies.

Declare external data, pretrained models, annotations, and usage permissions.
Do not train on private test annotations or manually retouch final test outputs.
Provide every evaluation result, including failures. Never include credentials,
private organizer annotations, or `.challenge/config.json`.

The host will announce dataset access, artifact visibility, dates, and team limits
before launch. Keep linked artifacts available through judging and unchanged after
the Kaggle deadline. Judges may request reproduction of the submitted revision.
