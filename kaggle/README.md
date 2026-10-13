# Kaggle judged-project setup

Selected format: full image-editing projects evaluated by judges (Hackathon).
Target: https://www.kaggle.com/competitions/paolob-bbb/settings

Local materials:

- `overview.md`: competition description.
- `evaluation.md`: proposed 100-point judging rubric.
- `submission.md`: artifact and reproducibility requirements.
- `writeup-template.md`: participant report template.

The rubric retains 30/30/25 points for localization/editing/preservation and
replaces 15-point measured efficiency with reproducibility and DINOv2 evidence.
This is a proposed adaptation for host review.

Live inspection confirmed that the competition is a private, unlaunched Community
Hackathon. No conversion is needed. Live page updates have not yet been verified.

Save these materials in the draft. Remove organizer-only draft notes before
publishing. Confirm dataset access, dates, team limits, judges, and artifact
visibility before launch. Do not upload `.challenge/` or the repository root:
they contain credentials, results, and private test annotations. The synthetic
fixture is not the real challenge dataset.

This format needs neither the Docker/HTTPS server nor a CSV scoring adapter.

Official reference: https://www.kaggle.com/docs/competitions-setup
