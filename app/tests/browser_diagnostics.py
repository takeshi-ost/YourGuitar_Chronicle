"""Keep diagnostic artifacts only for failed disposable browser checks."""
from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def diagnostic_page(playwright, name):
    executable = os.environ.get('YGC_BROWSER_EXECUTABLE')
    browser = playwright.chromium.launch(**({'executable_path': executable} if executable else {}))
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    folder = os.environ.get('YGC_BROWSER_ARTIFACTS')
    if folder:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        yield page
    except BaseException:
        if folder:
            destination = Path(folder) / name
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'errors.txt').write_text('\n'.join(errors))
            try:
                page.screenshot(path=str(destination / 'failure.png'), full_page=True, timeout=5000)
            except Exception as exc:
                (destination / 'screenshot-error.txt').write_text(str(exc))
            try:
                context.tracing.stop(path=str(destination / 'trace.zip'))
            except Exception as exc:
                (destination / 'trace-error.txt').write_text(str(exc))
        raise
    finally:
        context.close()
        browser.close()
