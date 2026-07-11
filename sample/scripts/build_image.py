"""Package the sample MicroVM app (Dockerfile + worker) into a zip artifact (``make build``).

`MicrovmSource.from_asset` already zips at synth time — this script exists for the
``from_asset_zip`` / ``from_s3`` flows and for inspecting exactly what ships in the image.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

APP_DIR = Path(__file__).parent.parent / 'microvm_app'
DIST_DIR = Path(__file__).parent.parent / 'dist'
ARTIFACT = DIST_DIR / 'microvm_app.zip'


def build() -> Path:
    if not (APP_DIR / 'Dockerfile').is_file():
        raise SystemExit(f'missing Dockerfile in {APP_DIR}')
    DIST_DIR.mkdir(exist_ok=True)
    with zipfile.ZipFile(ARTIFACT, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(APP_DIR.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path, path.relative_to(APP_DIR))
    print(f'built {ARTIFACT} ({ARTIFACT.stat().st_size} bytes)')
    return ARTIFACT


if __name__ == '__main__':
    build()
