# Manuscript completion and evidence map

Updated 23 October 2026 for the duration-aware defaults in version 0.11.0.

The scientific text, development table, diagnostic figure and supplementary methods are complete for author review in the local journal-template Word manuscript (`NanoPredict_manuscript_bioadv_20261023.docx`). [The Markdown source](manuscript.md) is authoritative for regeneration. Earlier Word copies and the pre-revision text are preserved; this revision does not alter model artifacts or historical predictions.

## Investigator details supplied

The current author list is Alexander Miller-Michlits, Yelyzaveta Miller-Michlits, Matthias Demetz, Christian Freyschlag and Adelheid Woehrer. The investigator requested removal of Christian Rohrandt and Franz-Josef Müller, supplied ethics reference N1115/2026, confirmed GitHub code availability and declared no conflicts of interest. These changes are present in the current manuscript and Word output. They do not supply missing affiliations, funding or committee details by implication.

## Evidence aligned to claims

| Statement | Supporting evidence | Interpretation |
|---|---|---|
| Version 0.11.0 bundles the duration-aware models | [Replacement record](evidence/duration_model_default_replacement/replacement.json) | Source/model replacement published on GitHub main; no claim that the sequencing machine or PyPI was updated |
| Development begins with 183 MinION acquisitions and 86 recorded groups | [Original MinION summary](evidence/minion_model_development/summary.json) | Recorded relationships; not proof of distinct patients |
| Eligible fitting/calibration counts are 133/32, 134/33, 134/33 | [Current audit](evidence/manuscript_20261023/evidence_audit.json) | Required-input exclusions explicitly retained |
| Run MAE is 0.298/0.259/0.236 Gb; group MAE is worse than the previous model | [Recomputed common-row metrics](evidence/manuscript_20261023/development_metrics.csv) | Descriptive development comparison; no general superiority claim |
| Two real MinION runs recorded earlier models at all checkpoints | Supplementary Methods S6; preserved archive reviews | Technical operation on two acquisitions sharing a flowcell; operator blinding not established |
| New-model forecasts are closer than recorded earlier forecasts on those runs | [Figure data](evidence/manuscript_20261023/figure1_data.csv) | Post-hoc diagnostic comparisons; both runs informed design; cumulative extrapolation remains closer |
| 103 source tests, 59 portable tests, 98 calibration runtime checks | [Replacement verification](evidence/duration_model_default_replacement/verification.json), development manifest | Software checks on recorded snapshots; not live validation of the replacement |
| Reliable independent accuracy, nominal coverage or probability calibration | Not established | No affirmative claim in the revised manuscript |

## Remaining author and submission tasks

- Supply author affiliations and corresponding author name, institutional email and postal address.
- Confirm author contributions and final approval; complete funding information or confirm no specific funding.
- Name the ethics committee, confirm approved scope and consent/waiver basis, and state permitted data sharing. The provided reference N1115/2026 is already included.
- Verify/deposit the exact source and model version and finalize data-access terms. The exact source/model revision is now on GitHub main. A separately deposited archival release and data-access terms remain for author completion.
- Verify final pagination in Word against the four-page limit after completing front matter. The template structure and embedded figure/table were inspected; a Word layout engine is unavailable here, so page count is not certified.
- If adding independent accuracy or new-model live-validation claims, obtain matching evidence first. The next MinION run can support technical qualification; one run alone cannot validate population accuracy or calibration. Such claims are not needed to describe the completed development/technical work honestly.

This is a complete scientific revision for author review, with explicit author-information fields remaining. The software/source update is published to GitHub main; no PyPI release, archival deposit or journal submission has been performed.

## Preserved earlier records

The pre-revision readiness document, manuscript and supporting files are saved under `archive/manuscript-duration-alignment-20261023/` with hashes. The complete legacy numerical analyses remain in [Supplementary Historical Results](historical_model_results.md), with the original frozen evidence in `evidence/retrospective/` and `evidence/replacement_assessment/`. The old readiness narrative includes historical requirements and claims that are superseded by this dated status, including the previously pending explicit-model recorder support and the former absence of live technical examples.
