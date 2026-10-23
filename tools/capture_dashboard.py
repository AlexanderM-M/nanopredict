"""Capture the real dashboard in anonymous replay mode for the GitHub README.

Requires the optional Playwright package/browser and a running replay server.
"""
import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/images/dashboard-preview.png')
    parser.add_argument('--browser-executable', help='Optional local Chromium executable')
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        parser.error('Use a local replay server')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        options = {'headless': True}
        if args.browser_executable:
            options['executable_path'] = args.browser_executable
        browser = p.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000},
                                    device_scale_factor=1, locale='en-GB',
                                    reduced_motion='reduce')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(args.url, wait_until='networkidle')
            if page.locator('#modeName').inner_text() != 'Historical replay':
                raise RuntimeError('Screenshot capture requires anonymous replay mode')
            page.select_option('#sampleSelect', 'Sample3')
            page.fill('#targetInput', '0.3')
            page.select_option('#speedSelect', '20')
            page.click('#startButton')
            page.click('#advanceButton')
            page.wait_for_function("document.querySelector('#intervalValue').textContent.includes('30-min model')")
            page.click('#advanceButton')
            page.wait_for_function("document.querySelector('#intervalValue').textContent.includes('60-min model')")
            # Allow the transient 'Replay started' toast to disappear naturally.
            page.wait_for_function("getComputedStyle(document.querySelector('#toast')).opacity === '0'")
            page.evaluate('document.fonts.ready')
            if errors:
                raise RuntimeError('Dashboard browser errors: ' + '; '.join(errors))
            page.screenshot(path=str(args.output), full_page=True, animations='disabled')
            print(f'Captured {args.output}: Sample3, 60-minute checkpoint, 0.3 Gb target; no browser errors.')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
