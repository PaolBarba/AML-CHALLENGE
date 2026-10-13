# Evaluation — judged projects

Organizer draft: publish the agreed rubric before submissions open. This adapts
the original scoring proposal to judged projects. The final 15 points assess
reproducibility and DINOv2 evidence instead of unverified speed.

| Criterion | Points | Evidence |
| --- | ---: | --- |
| Target localization | 30 | Correct object/instance selection, boundaries, spatial reasoning, small and occluded targets |
| Requested edit success | 30 | Requested transformation actually occurs, with plausible visual results |
| Context preservation | 25 | Non-target objects, layout, lighting, background, and justified boundary changes |
| Reproducibility and DINOv2 study | 15 | Runnable pipeline (5), controlled DINOv2 ablation (5), architecture, failure analysis and compute reporting (5) |

For each of the first three criteria, rate each evaluation task from 0 to 4.
Average within task type, then average task types equally. Divide by 4 and
multiply by the criterion's points. Missing or unreadable task outputs receive
zero for all three criteria.

- 0: requirement not met.
- 1: major errors; only a small part of the requirement is met.
- 2: partly successful with clear remaining errors.
- 3: largely successful with minor visible errors.
- 4: requirement fully met with no material errors.

IoU and preservation diagnostics can support judging where reference masks exist;
they are not a separate automatic Kaggle leaderboard. An unchanged image earns
zero edit-success credit. An oversized predicted mask does not redefine the
permitted edit region.

For each 5-point experimental-evidence item: 0 means missing; 1–2 means incomplete
or unsupported; 3–4 means usable with identifiable limitations; 5 means complete
and reproducible. Report hardware, runtime, loading policy, precision, resolution,
and memory where available. Self-reported speed earns no efficiency bonus.

Use the same evaluation tasks for all teams. Review complete outputs, not only
selected examples. If multiple judges are appointed, average their independent
total scores. Break ties by edit success, preservation, then localization;
remaining ties share rank. Before launch, freeze the task set, appoint judges,
verify artifact access, and calibrate ratings on common example outputs.
