"""Download the pinned OpenCV model artifacts declared by backend/models.manifest.json."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path


root = Path(__file__).resolve().parents[1]
backend = root / "backend"
sys.path.insert(0, str(backend))

from app.core.config import get_settings  # noqa: E402


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    settings = get_settings()
    settings.ensure_directories()
    manifest = json.loads((backend / "models.manifest.json").read_text(encoding="utf-8"))
    for name, item in manifest.items():
        target = settings.model_dir / item["filename"]
        if target.is_file() and checksum(target) == item["sha256"]:
            print(f"{name}: already verified")
            continue
        print(f"Downloading {name}…")
        temporary = target.with_suffix(target.suffix + ".download")
        urllib.request.urlretrieve(item["url"], temporary)
        actual = checksum(temporary)
        if actual != item["sha256"]:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Checksum mismatch for {name}: expected {item['sha256']}, got {actual}")
        temporary.replace(target)
        print(f"{name}: verified")


if __name__ == "__main__":
    main()
