"""A local stand-in for the Anthropic Messages API: records every request and returns a canned reply."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeAnthropic:
    def __init__(self):
        self.requests = []          # {'headers': {...}, 'body': {...}} for every call
        self.text = '```sql\nSELECT 1;\n```\nReturns one.'
        self.stop_reason = 'end_turn'
        self.status = 200
        self.error_type = 'api_error'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                owner.requests.append({'headers': {k.lower(): v for k, v in self.headers.items()}, 'body': body, 'path': self.path})
                if owner.status != 200:
                    payload = {'type': 'error', 'error': {'type': owner.error_type, 'message': 'fake failure'}}
                    status = owner.status
                else:
                    status = 200
                    payload = {'id': 'msg_fake', 'type': 'message', 'role': 'assistant', 'model': body.get('model', 'fake'),
                               'content': [{'type': 'text', 'text': owner.text}], 'stop_reason': owner.stop_reason,
                               'stop_sequence': None, 'usage': {'input_tokens': 321, 'output_tokens': 45}}
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reply(self, text, stop_reason='end_turn'):
        self.text, self.stop_reason, self.status = text, stop_reason, 200

    def fail(self, status, error_type):
        self.status, self.error_type = status, error_type

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    @property
    def last(self):
        return self.requests[-1]

    @property
    def sent_text(self):
        """Everything the app put in the request, as one string."""
        b = self.last['body']
        return json.dumps(b['system']) + json.dumps(b['messages'])
