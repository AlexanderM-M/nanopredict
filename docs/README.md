# Dashboard preview

`images/dashboard-preview.png` is captured from the actual NanoPredict web
interface using the packaged anonymous `Sample3` replay at its 60-minute
checkpoint and a 0.3 Gb target. Forecasts come from the bundled model; the
capture script does not replace UI text or fabricate measurements. The image
illustrates the interface, not independent predictive performance.

To refresh it after a UI change, install the optional capture dependency in a
development environment (it is not a NanoPredict runtime dependency):

```bash
python -m pip install playwright
python -m playwright install chromium
nanopredict start --source replay --foreground --no-browser
```

In a second terminal, run:

```bash
python tools/capture_dashboard.py
```

The capture only accepts a local server and checks that it is in replay mode
before starting an example. It sets the target and advances through the real
UI controls. Inspect the resulting image before committing it. A custom local
Chromium binary can be selected with `--browser-executable`.
