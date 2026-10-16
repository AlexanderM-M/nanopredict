# Local archive and release checklist

Current state: preparation archive only; independent validation outstanding. No publication, upload, tag, GitHub release, PyPI release or journal submission is authorized by this checklist.

## Archive contents

The local archive builder packages the clean committed tree with a revision and per-file SHA-256 manifest. It includes source, package metadata/license/notices, unchanged bundled prediction/target/replay assets, tests, reproducible analysis/validation tools, manuscript draft, protocol, templates and explicitly developmental evidence. It excludes Git internals, the virtual environment, ignored local archive output, prospective study databases, secret keys and untracked files. New local source locators and raw reconstruction inputs are kept in ignored `paper/archive/` and must remain excluded. The tracked retrospective record contains coded aggregate counts and checksums only, not specimen paths or diagnostic outputs. Review the tracked-file list for any sensitive material before building; exclusion of untracked files is not a substitute for data review.

```bash
python tools/paper/prepare_archive.py --output paper/archive
```

The command refuses a dirty tree and writes `nanopredict-preparation-REVISION.tar.gz` plus a manifest. This is a local review artifact, not a validated journal dataset or public release. Test extraction into a temporary directory and rerun tests using the intended environment. For a future release, build source/wheel distributions and test a clean install on the stated platforms, including the study CLI and packaged data.

## Before a submission release

- Finish the readiness evidence map and independent study; reconcile cohort counts, missingness and all figure/table numerators/denominators against machine-readable outputs.
- Review original-model provenance limitations and scope. Keep manuscript claims limited to yield forecasts and monitoring; retain the documented development and evaluation limitations.
- Ensure scientific results have adequate data availability consistent with the journal's policy and site governance. Publish only approved derived data; never include identity crosswalks, local linkage secrets, identifiable BAMs or study databases by default.
- Finalize author list, contributions, affiliations, correspondence, funding, conflicts, AI-assistance disclosure, citations and permissions. Have authors review results and the entire manuscript.
- Recheck official Bioinformatics Advances requirements; format the final Application Note and supplementary material, verify word/page/figure limits and visual readability, and prepare a cover letter.
- Check installation and tests on supported operating systems/Core versions. Record qualified versus untested configurations and operational limits.
- Freeze release commit and immutable approved code/test-data archive contents. Inspect the archive itself and record checksums. Request publication/deposit instructions before obtaining a public DOI/URL or making a release.
- Insert actual archival identifiers and final evidence, then obtain explicit instructions for submission. Never replace placeholders with guessed results or URLs.

The existing GitHub release workflow publishes to PyPI when a release is published. Creating a local commit or archive does not trigger it; do not publish a GitHub release as an incidental preparation step.
