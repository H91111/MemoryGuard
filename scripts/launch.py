"""Wait until the local server is bound before opening the browser."""
import argparse
import json
import threading
import urllib.request
import webbrowser
from pathlib import Path

from memory_guard.server import create_server
from memory_guard.schema import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    url = f'http://127.0.0.1:{args.port}'
    db = Path('runtime/memory.db').resolve()
    existing = None
    try:
        with urllib.request.urlopen(url+'/api/health', timeout=1) as response:
            existing = json.load(response)
    except (OSError, ValueError):
        pass
    if isinstance(existing, dict) and existing.get('workspace') == digest(str(db)) and existing.get('version') == '0.2.0':
        print('Memory Guard is already running: '+url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return
    try:
        server = create_server(str(db), args.port)
    except OSError as exc:
        raise SystemExit(f'Cannot start on port {args.port}: {exc}\nUse: powershell -File start.ps1 -Port 8766')
    print(f'Memory Guard v0.2.0 ready: {url}\nKeep this window open. Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        timer = threading.Timer(0.4, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
