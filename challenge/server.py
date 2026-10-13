import argparse
import base64
import io
import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from .demo import initialize
from .store import Invalid, Store

STATIC = Path(__file__).resolve().parent.parent / 'static'
REFERENCE = STATIC.parent / 'data' / 'image.png'
MAX_BODY = 32 * 1024 * 1024


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, store):
        self.store = store
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt, *args):
        # Avoid logging request URLs: authentication must only use the header.
        logging.info('HTTP request from %s', self.client_address[0])

    def reply(self, status, body, content_type='application/json'):
        if content_type == 'application/json':
            body = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.handle_api(False)

    def do_POST(self):
        self.handle_api(True)

    def handle_api(self, post):
        try:
            self.route(post)
        except PermissionError as exc:
            self.reply(403, {'error': str(exc)})
        except KeyError:
            self.reply(404, {'error': 'Resource not found'})
        except (Invalid, ValueError, TypeError, OverflowError) as exc:
            self.reply(400, {'error': str(exc)})
        except (TimeoutError, socket.timeout):
            self.reply(408, {'error': 'Request timed out'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception('Request failed')
            self.reply(500, {'error': 'Evaluation failed; contact the organizer'})

    def read_upload(self, length):
        deadline = time.monotonic() + 60
        chunks = []
        remaining = length
        try:
            while remaining:
                budget = deadline - time.monotonic()
                if budget <= 0:
                    raise TimeoutError('Image upload exceeded 60 seconds')
                self.connection.settimeout(budget)
                chunk = self.rfile.read1(min(remaining, 64 * 1024))
                if not chunk:
                    raise Invalid('Incomplete request body')
                chunks.append(chunk)
                remaining -= len(chunk)
            if time.monotonic() >= deadline:
                raise TimeoutError('Image upload exceeded 60 seconds')
            return b''.join(chunks)
        finally:
            self.connection.settimeout(15)

    def route(self, post):
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if not post and path in ('/', '/app.js', '/reference.js', '/style.css'):
            filename, mime = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/reference.js': ('reference.js', 'text/javascript; charset=utf-8'),
                              '/style.css': ('style.css', 'text/css; charset=utf-8')}[path]
            self.reply(200, (STATIC / filename).read_bytes(), mime)
            return
        if not path.startswith('/api/'):
            raise KeyError()
        authorization = self.headers.get('Authorization', '')
        if not authorization.startswith('Bearer ') or len(authorization) > 1024:
            self.reply(401, {'error': 'Provide an Authorization: Bearer token header'})
            return
        store = self.server.store
        team, admin = store.authenticate(authorization[7:])
        if not team:
            self.reply(401, {'error': 'Invalid authentication token'})
            return
        if post:
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise Invalid('Content-Type must be application/json')
            length = self.headers.get('Content-Length')
            if length is None or not length.isdigit() or not 0 < int(length) <= MAX_BODY:
                self.reply(413, {'error': 'Body must be between 1 byte and 32 MB'})
                return
            if path == '/api/images':
                if not admin:
                    raise PermissionError('Only organizers can upload source images')
                raw = self.read_upload(int(length))
            else:
                raw = self.rfile.read(int(length))
            if len(raw) != int(length):
                raise Invalid('Incomplete request body')
            payload = json.loads(raw, parse_constant=lambda v: (_ for _ in ()).throw(Invalid('Non-finite JSON number')))
            if not isinstance(payload, dict):
                raise Invalid('Request body must be a JSON object')
            if path == '/api/images':
                self.reply(201, store.upload_image(payload, admin))
                return
            if path in ('/api/submissions', '/api/measured-submissions'):
                self.reply(201, store.submit(payload, team, admin, path.endswith('measured-submissions')))
                return
            if path == '/api/reference/submissions':
                self.reply(201, store.submit_reference(payload, team, admin))
                return
            if path == '/api/runs':
                selected_team = payload.get('student_id', team) if admin else team
                measured = payload.get('mode', 'quality') == 'measured'
                if measured and not admin:
                    raise PermissionError('Only organizers can register measured runs')
                store.register_run(selected_team, payload.get('split'), payload.get('run_id'), measured)
                self.reply(201, {'status': 'registered'})
                return
            if path == '/api/select-run':
                selected_team = payload.get('student_id', team) if admin else team
                if selected_team not in store.config['teams']:
                    raise Invalid('Unknown team')
                store.select(selected_team, payload.get('split'), payload.get('run_id'))
                self.reply(200, {'status': 'selected'})
                return
            raise KeyError()
        if path == '/api/reference/leaderboard':
            self.reply(200, store.reference_leaderboard())
            return
        if path in ('/api/reference', '/api/reference/image', '/api/reference/json'):
            window = store.reference_window(team)
            if path == '/api/reference':
                self.reply(200, window)
            elif not window['available']:
                self.reply(423, dict(window, error='Reference image is locked until the next window'))
            elif path == '/api/reference/json':
                raw = store.reference_image_path().read_bytes()
                with Image.open(io.BytesIO(raw)) as image:
                    width, height = image.size
                batch_id = store.issue_reference_batch(team, raw, width, height, window['next_change_at'])
                self.reply(200, dict(window, reference_id='backpack_reference', filename='image.png',
                                     batch_id=batch_id,
                                     content_type='image/png', encoding='base64',
                                     image_width=width, image_height=height,
                                     image=base64.b64encode(raw).decode('ascii'), **store.reference_instructions()))
            else:
                self.reply(200, store.reference_image_path().read_bytes(), 'image/png')
            return
        if path == '/api/images':
            self.reply(200, store.shared_images())
            return
        if path == '/api/results.xlsx':
            if not admin:
                raise PermissionError('Only organizers can export all team results')
            self.reply(200, store.export_excel(),
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            return
        parts = path.strip('/').split('/')
        if len(parts) == 3 and parts[:2] == ['api', 'images']:
            self.reply(200, store.shared_image(parts[2]), 'image/png')
            return
        if path == '/api/config':
            public = {k: store.config[k] for k in ('name', 'dataset_version', 'weights', 'reference_time_ms', 'hardware_profile')}
            public.update(identity=team, admin=admin,
                          splits={s: sum(t['split'] == s for t in store.tasks.values()) for s in ('train', 'validation', 'test')})
            self.reply(200, public)
            return
        split = query.get('split', ['validation'])[0]
        if split not in ('train', 'validation', 'test'):
            raise Invalid('Unknown split')
        if path == '/api/tasks':
            tasks = [store.public_task(t) for t in store.tasks.values() if t['split'] == split]
            if admin:
                for t in tasks:
                    t['mask_url'] = f'/api/tasks/{t["task_id"]}/mask'
            self.reply(200, tasks)
            return
        if path == '/api/leaderboard':
            self.reply(200, store.leaderboard(split, query.get('mode', ['quality'])[0] == 'measured'))
            return
        if path == '/api/submissions':
            self.reply(200, store.submissions(team, admin))
            return
        parts = path.strip('/').split('/')
        if len(parts) == 4 and parts[:2] == ['api', 'tasks']:
            task = store.tasks.get(parts[2])
            if task is None:
                raise KeyError()
            kind = parts[3]
            if kind == 'image':
                field = 'source_image'
            elif kind == 'mask':
                if (task['split'] == 'test' or task is store.reference_task) and not admin:
                    raise PermissionError('Reference and test annotations are private')
                field = 'ground_truth_mask'
            else:
                raise KeyError()
            from .store import image_bytes
            self.reply(200, image_bytes(store.load(task, field, 'RGB' if kind == 'image' else 'L')), 'image/png')
            return
        if len(parts) == 4 and parts[:2] == ['api', 'submissions']:
            self.reply(200, store.artifact(int(parts[2]), parts[3], team, admin), 'image/png')
            return
        raise KeyError()


def main():
    parser = argparse.ArgumentParser(description='Local semantic image editing challenge platform')
    parser.add_argument('--data', default='.challenge')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('init-demo', help='Generate synthetic fixture and local credentials')
    team = sub.add_parser('add-team', help='Create a team token; restart the server afterward')
    team.add_argument('team_id')
    serve = sub.add_parser('serve')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.action == 'init-demo':
        initialize(args.data)
        print(f'Demo initialized. Credentials: {Path(args.data).resolve() / "config.json"}')
    elif args.action == 'add-team':
        from .credentials import add_team
        try:
            token = add_team(args.data, args.team_id)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(f'Team: {args.team_id}\nToken: {token}\nShare this token privately with the team. Restart the server to enable it.')
    else:
        logging.basicConfig(level=logging.INFO)
        server = Server((args.host, args.port), Store(args.data))
        print(f'Challenge dashboard: http://{args.host}:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            server.store.db.close()


if __name__ == '__main__':
    main()
