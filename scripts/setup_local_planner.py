"""Download the pinned CPU planner into this checkout; no global installation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "llama-cpp"
MODEL = ROOT / "models" / "qwen3-0.6b"
RELEASE = "b11951"
REVISION = "23749fefcc72300e3a2ad315e1317431b06b590a"
ARCHIVE = f"llama-{RELEASE}-bin-win-cpu-x64.zip"
ARCHIVE_SHA256 = "ac5edf9c936132fb16c9ff863db8b627c2a67621ff2e796ffd184585aea567ea"
MODEL_SHA256 = "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031"


def receive(url: str, path: Path, size: int = 0, expected: str = "") -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        print(f"Downloading {path.name}", flush=True)
        temporary = path.with_name(path.name + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "MemoryGuard-local-planner/1"})
        started = time.monotonic()
        downloaded = 0
        next_progress = 32 * 1024 * 1024
        with urllib.request.urlopen(request, timeout=30) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_progress:
                    print(f"{path.name}: {downloaded:,}/{size:,} bytes", flush=True)
                    next_progress += 32 * 1024 * 1024
                if time.monotonic() - started > 900:
                    raise TimeoutError(f"Download exceeded 15 minutes: {path.name}")
        check_file(temporary, size, expected)
        temporary.replace(path)
    digest = check_file(path, size, expected)
    return {"file": path.name, "source": url, "bytes": path.stat().st_size,
            "sha256": digest, "upstream_sha256": expected}


def check_file(path: Path, size: int, expected: str) -> str:
    if size and path.stat().st_size != size:
        raise ValueError(f"Size mismatch: {path}")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if expected and digest != expected:
        raise ValueError(f"SHA256 mismatch: {path}")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    model_base = f"https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/{REVISION}"
    downloads = [
        (f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{ARCHIVE}", RUNTIME / ARCHIVE, 24378362, ARCHIVE_SHA256),
        (f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{RELEASE}/LICENSE", RUNTIME / "LICENSE", 0, ""),
        (f"{model_base}/Qwen3-0.6B-Q8_0.gguf", MODEL / "Qwen3-0.6B-Q8_0.gguf", 639446688, MODEL_SHA256),
        (f"{model_base}/LICENSE", MODEL / "LICENSE", 11544, ""),
        (f"{model_base}/README.md", MODEL / "README.md", 6236, ""),
    ]
    with ThreadPoolExecutor(max_workers=3) as executor:
        records = list(executor.map(lambda args: receive(*args), downloads))
    release_dir = RUNTIME / RELEASE
    if not (release_dir / "llama-server.exe").exists():
        with zipfile.ZipFile(RUNTIME / ARCHIVE) as archive:
            archive.extractall(release_dir)
    model_manifest = {"model": "Qwen/Qwen3-0.6B-GGUF", "revision": REVISION,
                      "quantization": "Q8_0", "license": "Apache-2.0", "files": records[2:]}
    runtime_manifest = {"repository": "https://github.com/ggml-org/llama.cpp", "release": RELEASE,
                        "license": "MIT", "files": records[:2],
                        "server_sha256": check_file(release_dir / "llama-server.exe", 0, "")}
    for path, content in [(MODEL / "manifest.json", model_manifest), (RUNTIME / "manifest.json", runtime_manifest)]:
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Ready: {release_dir / 'llama-server.exe'}", flush=True)
    if args.start:
        endpoint = f'http://127.0.0.1:{args.port}/v1'
        try:
            with urllib.request.urlopen(endpoint + '/models', timeout=2) as response:
                active = json.load(response)
            if any(m['id'] == 'qwen3-0.6b-q8_0' for m in active.get('data', [])):
                print(f'Planner already running: {endpoint}', flush=True)
                return
        except OSError:
            pass
        command = [str(release_dir / 'llama-server.exe'), '-m', str(MODEL / 'Qwen3-0.6B-Q8_0.gguf'),
                   '--alias', 'qwen3-0.6b-q8_0', '--host', '127.0.0.1', '--port', str(args.port),
                   '-c', '4096', '-t', '4', '-np', '1', '--jinja', '-ngl', '0']
        with (RUNTIME / 'server.stdout.log').open('wb') as stdout, (RUNTIME / 'server.stderr.log').open('wb') as stderr:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        (RUNTIME / 'server.json').write_text(json.dumps(dict(pid=process.pid, arguments=command,
                url=endpoint), ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Started planner PID {process.pid}: {endpoint}', flush=True)


if __name__ == "__main__":
    main()
