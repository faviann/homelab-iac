#!/bin/sh
set -eu

apk add --no-cache chromaprint
python -m pip install -r /config/requirements.txt

python - <<'PY'
from pathlib import Path

path = Path("/usr/local/lib/python3.11/site-packages/beetsplug/VGMplug.py")
text = path.read_text()
old = "from beets.autotag.hooks import AlbumInfo, TrackInfo, Distance, string_dist"
new = (
    "from beets.autotag.hooks import AlbumInfo, TrackInfo\n"
    "from beets.autotag.distance import Distance, string_dist"
)

if old in text:
    path.write_text(text.replace(old, new, 1))
elif new not in text:
    raise SystemExit("Unexpected VGMplug import layout; compatibility patch was not applied")

text = path.read_text()
old = '        self._log.setLevel("ERROR")'
new = '        # self._log.setLevel("ERROR")'

if old in text:
    path.write_text(text.replace(old, new, 1))
elif new not in text:
    raise SystemExit("Unexpected VGMplug logger layout; compatibility patch was not applied")
PY

python - <<'PY'
from pathlib import Path

path = Path("/usr/local/lib/python3.11/site-packages/beetsplug/VGMplug.py")
text = path.read_text()

patches = [
    (
        'req = requests.get(f"{self.config[\'searchalbumsurl\'].get()}{query}?format=json", headers=self.headers)',
        'req = requests.get(f"{self.config[\'searchalbumsurl\'].get()}{query}?format=json", headers=self.headers, timeout=5)',
    ),
    (
        'req = requests.get(f"{self.config[\'albumurl\'].get()}{album_id}?format=json", headers=self.headers)',
        'req = requests.get(f"{self.config[\'albumurl\'].get()}{album_id}?format=json", headers=self.headers, timeout=5)',
    ),
]

for old, new in patches:
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise SystemExit(f"VGMplug timeout patch failed: could not find expected line")

path.write_text(text)
PY

python -c "import beetsplug.VGMplug"
