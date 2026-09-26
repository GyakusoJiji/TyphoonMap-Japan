"""Local TyphoonMap server with a same-origin JMA update endpoint."""
from __future__ import annotations

import argparse
import json
import re
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools.update_data import current_storms

ROOT = Path(__file__).resolve().parent
TRACKS = ROOT / 'data' / 'tracks.js'
PREFIX = 'window.TYPHOON_DATA='


def read_stored_data():
    raw = TRACKS.read_text(encoding='utf-8').strip()
    if not raw.startswith(PREFIX) or not raw.endswith(';'):
        raise ValueError('data/tracks.js の形式が正しくありません。')
    return json.loads(raw[len(PREFIX):-1])


def fresh_data():
    data = read_stored_data()
    active = current_storms()
    active_ids = {storm['id'] for storm in active}
    data['storms'] = [storm for storm in data['storms'] if storm['id'] not in active_ids] + active
    data['liveUpdatedAt'] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    return data, active


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.js': 'application/javascript; charset=utf-8'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path != '/api/refresh':
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            data, active = fresh_data()
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            print(f'JMA refresh: {len(active)} active storm(s)', flush=True)
        except Exception as error:
            body = json.dumps({'error': f'気象庁のデータを取得できませんでした: {error}'}, ensure_ascii=False).encode('utf-8')
            self.send_response(HTTPStatus.BAD_GATEWAY)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        print(f'{self.address_string()} - {format % args}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'TyphoonMap: http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
