"""Write the recorded-run page data: docs/cases/*.json and docs/i18n.json (config/pages.toml).

No key and no network: recorded runs are replayed through the checker, eval runs are read as saved.
Usage: uv run scripts/build-pages.py
"""

from terkini.packs import REPO_ROOT
from terkini.pages import build_files

for rel, text in build_files().items():
    path = REPO_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(rel)
