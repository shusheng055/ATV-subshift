"""Verify the frozen application against a local mock API; never contact a remote service."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import argparse
from pathlib import Path
import json
import os
import subprocess
import threading
import sys

sys.stdout.reconfigure(encoding='utf-8')

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--folder', type=Path, default=root / 'dist' / 'ATV subshift')
parser.add_argument('--report', type=Path, default=root / 'evidence' / 'frozen-selfcheck.json')
args = parser.parse_args()
report = args.report.resolve()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        # Segment requests carry history separately from the source passage.
        if self.path == '/v1/chat/completions':
            content = payload['messages'][-1]['content']
            try:
                passage = json.loads(content)
                if isinstance(passage, dict) and 'subtitle_to_translate' in passage:
                    payload['messages'][-1]['content'] = passage['subtitle_to_translate']
            except (ValueError, TypeError):
                pass
        if self.path == '/v1/chat/completions' and payload['messages'][-1]['content'] == 'Hello':
            response = {'choices': [{'message': {'content': '测试译文'}}]}
        elif self.path == '/v1/responses' and payload['input'][0]['content'] == 'Hello':
            response = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '测试译文'}]}]}
        elif self.path == '/v1/messages' and payload['messages'][0]['content'] == 'Hello':
            response = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '测试译文'}]}
        elif self.path == '/v1/models/test:generateContent' and payload['contents'][0]['parts'][0]['text'] == 'Hello':
            response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '测试译文'}]}}]}
        else:
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


server = HTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
environment = dict(os.environ, ATV_SUBSHIFT_TEST_API=f'http://127.0.0.1:{server.server_port}/v1')
try:
    result = subprocess.run([str(args.folder.resolve() / 'ATV subshift.exe'),
                             '--self-check', str(report)], env=environment, timeout=40,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    print('Frozen runtime exit:', result.returncode)
    if report.exists():
        raw = json.loads(report.read_text('utf-8'))
        raw['process_exit_code'] = result.returncode
        raw['passed'] = bool(raw.get('passed')) and result.returncode == 0
        report.write_text(json.dumps(raw, ensure_ascii=False, indent=2), 'utf-8')
        print(report.read_text('utf-8'))
    raise SystemExit(result.returncode)
finally:
    server.shutdown()
    server.server_close()
