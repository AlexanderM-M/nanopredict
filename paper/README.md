# NanoPredict manuscript and supporting evidence

Current revision: 23 October 2026, version 0.11.0 duration-aware models, targeting a Bioinformatics Advances Application Note.

## Manuscript and reproducible evidence

- [Current manuscript source](manuscript.md).
- [Supplementary Methods and Results](supplementary_methods.md).
- [Figure 1 vector PDF](evidence/manuscript_20261023/figure1.pdf), [600-dpi PNG](evidence/manuscript_20261023/figure1.png) and [exact data](evidence/manuscript_20261023/figure1_data.csv).
- [Supplementary Historical Results](historical_model_results.md), preserving earlier legacy-model analyses.
- [Author completion and evidence map](readiness.md) and [journal requirements](journal_requirements.md).

The manuscript remains an author draft. Affiliations, correspondence, contributions,
funding and final ethics/data-access wording require author completion. Generated
Word documents, the supplied journal template, author-completion notes and review
ZIP files are local author materials and are not included in Git. Earlier local
Word copies have been preserved. No journal submission has been performed.

## What the paper reports

The new defaults use cumulative passed bases, observed seconds and configured duration, with fitting-only selection of decay and scale. The original MinION group partition is retained. Required-input eligibility leaves 133/32, 134/33 and 134/33 fitting/calibration acquisitions at 30/60/120 minutes. Run-weighted calibration MAE improves over the previous model on common rows, but group-weighted MAE is worse. Simple extrapolation remains a required comparator.

Two live technical runs used earlier models, shared a flowcell and informed the revision. Applying the new model to their recorded inputs is post-hoc diagnostic work. It is not independent validation or prospective testing of version 0.11.0. The scientific text explicitly retains unfavorable comparisons and the distinction between planned-duration forecasts and observed-ending development outcomes.

The [current audit](evidence/manuscript_20261023/evidence_audit.json), [common-row metrics](evidence/manuscript_20261023/development_metrics.csv) and [replacement verification](evidence/duration_model_default_replacement/verification.json) support the reported claims. The 103 source tests and 59 portable tests refer to the replacement snapshot. No model was refitted during manuscript revision.

## Reproduce the current author files

With Matplotlib 3.9.4 installed, render the figure from aggregate data:

```bash
python tools/paper/render_duration_manuscript.py
```

With Pandoc and lxml installed and an author-supplied Bioinformatics Advances
Word template at `paper/bioadv-word-template.docx`, generate a local Word copy:

```bash
python tools/paper/export_word.py --output paper/NanoPredict_manuscript_bioadv_20261023.docx
pandoc paper/supplementary_methods.md --standalone --metadata=lang:en-GB \
  --output paper/NanoPredict_supplementary_methods_20261023.docx
```

These commands replace the named generated files; preserve author edits or choose a new output path. The main file retains the template's title/abstract block, two-column text, styles and headers, with a full-width table and figure. Final pagination must be inspected in Word after author completion; the four-page limit is not certified by XML inspection.

## Development and historical records

The 22 October artifacts are documented in [the duration development summary](evidence/duration_model_development/summary.json). That record was written before promotion and retains its original status. The later [replacement record](evidence/duration_model_default_replacement/replacement.json) documents their adoption as defaults. The preceding [16 October MinION-only development](evidence/minion_model_development/summary.json) and [early-model diagnosis](evidence/early_model_diagnosis/summary.json) remain preserved. Historical summaries saying defaults were unchanged describe those earlier snapshots.

Training reproduction with access-controlled inputs is specified in Supplementary Methods S7 and `tools/paper/train_duration.py`. Full model development requires the original feature table, relationship manifest and preceding plan; public aggregate results alone are not sufficient to recreate those inputs.

The original 20-run legacy reconstruction had 14 training-overlapping acquisitions. Later identity screens and replacement-upload comparisons are retained in the historical supplement and `evidence/`. They do not validate the new model. Frozen models, private inputs and original output tables have not been overwritten. The previous manuscript/readiness documents are preserved under `archive/manuscript-duration-alignment-20261023/`.

Additional methodological records:

- [Repository/model audit](audit.md) and [feature timing audit](feature_audit.md).
- [Historical benchmark methods](benchmark_methods.md).
- [Matched validation](matched_validation.md), [independent protocol](independent_protocol.md) and [operator instructions](operator_instructions.md).
- [Machine handoff](machine_handoff.md) and [release checklist](release_checklist.md).

New recorders can now select explicit models with `--models-dir`; without it, initialization freezes the bundled defaults. Use a new environment/recorder for a new model and retain old freezes. The local sequencing-machine transfer includes update instructions. The version
0.11.0 source and model changes are published on GitHub `main`; no PyPI release,
archival deposit or manuscript submission is implied.
