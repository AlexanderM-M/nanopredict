"""Build a local default-model update with source, models and checksums."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]

INSTALL = '''Replace the active NanoPredict installation with version 0.11.0 and its bundled duration-aware models. The user has authorized this replacement. Prepare a NEW technical qualification for the next MinION acquisition.

Do the setup and verification. Do not modify MinKNOW, sequencing, basecalling, or any previous recorder/freeze/environment. Inspect active processes first and preserve all local changes. If sequencing is active, stage the new environment and wait to enroll a fresh acquisition.

1. Verify the adjacent ZIP checksum and SHA256SUMS.txt after extracting. Read manifest.json and evidence/development-summary.json. These are the newly selected package defaults; independent predictive accuracy is still unvalidated. The known October runs influenced the design but were not used for fitting; their diagnostic comparisons are not validation. Simple cumulative extrapolation remains a required comparator.

2. Create a separate Python 3.11 environment and install the runtime/ directory as an editable package. Use its pinned dependencies. The archive contains the exact runtime needed by the new serialized DurationYieldRegressor; updating only the model files in an old installation will not work. Preserve runtime/tools/paper/evaluate_frozen.py in this source layout for study freeze verification.

3. Run pip check and the included tests from runtime/ with the new Python: python -m unittest discover -s tests -v. Inspect tests and diagnostics before treating the installation as ready. Confirm all three candidate SHA-256 hashes match manifest.json. The package version alone does not identify these candidates.

4. The new models are bundled in runtime/src/nanopredict/data/models and duplicated at top-level models/ for checksum inspection. Remove or update any old NANOPREDICT_MODELS_DIR override in the new dashboard launcher. Switch the usual NanoPredict shortcut/service to the new environment and source. Preserve a working rollback launcher for the previous environment. Restart only the NanoPredict dashboard, leaving MinKNOW and existing recorders untouched. Existing active recorders must continue using their original environment. If switching a shared launcher would disturb an active recorder, stage its replacement for after that recorder finishes and report this clearly. Run read-only doctor checks using the new environment. Confirm the dashboard loads model_name=minion_duration_extrapolation at 30/60/120 minutes, with the expected artifact hashes. Its forecasting inputs are cumulative passed bases, observed seconds and planned hours. Missing duration must remain unavailable; never substitute 72 hours.

5. Prepare a new qualification protocol and recorder, using the new environment:
python -m nanopredict.study init --study NEW_RECORDER --protocol PROTOCOL_FILE --qualification --predictions-visible

Use --predictions-visible if a dashboard may expose forecasts; omit only when forecasts are actually hidden. Verify freeze.json names the selected model hashes and the embedded MinION development comparator provenance. Retain all audit features even though only three enter this model. The stored method key 'bundled' denotes the new duration-aware default; identify it by hashes/model name. Verify model_selection is bundled_default. Never bypass drift checks or modify an old freeze.

6. Prepare persistent collection using python -m nanopredict.study collect --study NEW_RECORDER. Preserve the previous acquisition records. Do not enroll an already-started run; do not invent sample relationships. Ask for missing material/group details when required. Provide the exact new-run enrollment command and ensure enrollment occurs before the first checkpoint. Do not claim independence or blinding for a qualification run.

7. Report the new environment, source fingerprint, candidate model hashes, recorder location, diagnostics/test results and exact dashboard/collector/enrollment commands. Check the captured planned duration at the next checkpoint. Capture all checkpoints, errors and actual final passed yield after basecalling drains, together with final reports and sequencing summary. No retraining or outcome-dependent adjustment is authorized during collection.

Do not publish or push. If a check fails, preserve the evidence and explain the failure. Finish everything possible without disturbing an active sequencing acquisition.
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output directory must be new')
    development = json.loads((args.development / 'manifest.json').read_text())
    payload = {}
    for name, checksum in development['models'].items():
        data = (args.development / 'models' / name).read_bytes()
        if sha(data) != checksum:
            raise ValueError('Candidate hash mismatch')
        if (ROOT / 'src/nanopredict/data/models' / name).read_bytes() != data:
            raise ValueError('Bundled defaults do not match selected development models')
        payload['models/' + name] = data
    files = [ROOT / n for n in ('README.md', 'LICENSE', 'MANIFEST.in', 'pyproject.toml')]
    files += [p for p in (ROOT / 'src/nanopredict').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py', '.html', '.css', '.js', '.json', '.csv', '.joblib')]
    files += [ROOT / 'tools/paper' / n for n in ('train_duration.py', 'train_minion.py', 'evaluate_frozen.py', 'package_duration_candidate.py')]
    files += [ROOT / 'tests' / n for n in ('test_duration_model.py', 'test_minion_training.py', 'test_study.py', 'test_dashboard.py', 'test_report.py', 'test_live.py')]
    files += [ROOT / 'tools/paper/feature_contract.json']
    for p in files:
        payload['runtime/' + p.relative_to(ROOT).as_posix()] = p.read_bytes()
    payload['INSTALL-CODEX.txt'] = INSTALL.encode()
    payload['evidence/default-replacement.json'] = (ROOT / 'paper/evidence/duration_model_default_replacement/replacement.json').read_bytes()
    payload['evidence/development-summary.json'] = (args.development / 'manifest.json').read_bytes()
    # Only the aggregate/diagnostic table: no patient identifiers or raw records.
    payload['evidence/posthoc-live-diagnostics.csv'] = (args.development / 'posthoc_live_diagnostics.csv').read_bytes()
    manifest = {'purpose': 'Local transfer for technical qualification; not a public release',
                'base_git_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'source_identity': 'Source snapshot includes local changes; use source hashes, not base revision alone',
                'models': development['models'],
                'runtime_source_sha256': {n: sha(data) for n, data in payload.items() if n.startswith('runtime/')},
                'python_used': platform.python_version(),
                'package_versions_used': {p: importlib.metadata.version(p) for p in ('numpy', 'scikit-learn', 'joblib', 'scipy', 'minknow_api', 'protobuf', 'grpcio', 'bamnostic')},
                'model_directory': 'runtime/src/nanopredict/data/models', 'runtime_directory': 'runtime',
                'package_version': '0.11.0',
                'qualification_only': True, 'legacy_bundled_models_retained': False}
    payload['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    payload['SHA256SUMS.txt'] = ''.join(f'{sha(data)}  {name}\n' for name, data in sorted(payload.items())).encode()
    args.output.mkdir(parents=True)
    path = args.output / 'nanopredict-duration-default-20261022.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(payload.items()):
            z.writestr(name, data)
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        for name, data in payload.items():
            assert sha(z.read(name)) == sha(data)
    path.with_suffix('.zip.sha256').write_text(f'{sha(path.read_bytes())}  {path.name}\n')
    (args.output / 'sequencing-machine-update.txt').write_text(INSTALL)
    print(path, path.stat().st_size, 'bytes; all payload hashes verified')


if __name__ == '__main__':
    main()
