"""Download original BGE files at a fixed revision into project-local models/."""
import hashlib
import json
import urllib.request
from pathlib import Path

from memory_guard.candidates import MODEL_ID, MODEL_REVISION


def main():
    root = Path(__file__).resolve().parent.parent / "models/bge-small-zh-v1.5"
    root.mkdir(parents=True, exist_ok=True)
    files = ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt", "model.safetensors"]
    manifest = {"model_id": MODEL_ID, "revision": MODEL_REVISION, "files": {}}
    for name in files:
        path = root / name
        if not path.exists():
            print("Downloading", name, flush=True)
            temp = path.with_suffix(path.suffix + ".partial")
            urllib.request.urlretrieve(f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/{name}", temp)
            temp.replace(path)
        manifest["files"][name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Model ready:", root, flush=True)


if __name__ == "__main__":
    main()
