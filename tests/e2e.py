#!/usr/bin/env python3
"""End-to-end check of the hub in headless Chromium, against a mock eng-agents live dashboard.

  pip install playwright && python -m playwright install chromium
  python tests/e2e.py

Serves this repo on 127.0.0.1:8802 and a mock dashboard on 127.0.0.1:4300 (the mock speaks the
shell API from eng-agents docs/shell-api.md). Exit 1 if any check fails.
"""
import functools, http.server, json, os, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = 'http://127.0.0.1:8802'
ENG = 'http://127.0.0.1:4300'
LOG = []

STATUS = {'app': 'eng-agents-dashboard', 'api': 1, 'version': '1.5.0', 'workspace': 'work', 'opencode': {'connected': True}, 'error': None,
          'items': [{'id': '123', 'title': 'Fix login', 'lane': 'bug', 'stage': 'build', 'tasks': {'done': 2, 'total': 5},
                     'next': {'command': '/do-task 123 3', 'text': 'Task 3: Add test', 'needsYou': False},
                     'paused': False, 'blocked': False, 'agent': 'busy', 'waiting': False, 'autopilot': None}],
          'starting': []}
PAGE = f"""<!doctype html><body><h3>Mock dashboard</h3><script>
addEventListener('message', e => {{ if (e.origin === '{HUB}') fetch('/log', {{method: 'POST', body: JSON.stringify(e.data)}}); }});
parent.postMessage({{type: 'eng-ready'}}, '{HUB}');
</script>"""


class Mock(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def cors(self):
        self.send_header('Access-Control-Allow-Origin', HUB)
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def reply(self, code, body, ctype='application/json', shell=False):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        if shell: self.cors()
        if ctype == 'text/html': self.send_header('Content-Security-Policy', f"frame-ancestors 'self' {HUB}")
        self.end_headers(); self.wfile.write(body.encode())

    def do_OPTIONS(self):
        self.send_response(204); self.cors(); self.end_headers()

    def do_GET(self):
        if self.path == '/api/shell/status':
            return self.reply(200 if self.headers.get('Origin') == HUB else 403, json.dumps(STATUS), shell=True)
        self.reply(200, PAGE, 'text/html')

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0)).decode() or '{}'
        if self.path == '/log': LOG.append(json.loads(body)); return self.reply(200, '{}')
        if self.path == '/api/shell/start': LOG.append({'start': json.loads(body)}); return self.reply(200, '{"ok":true}', shell=True)
        self.reply(404, '{}')


class Static(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass


def serve(port, handler):
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


failed = []
def check(name, ok):
    print(('PASS  ' if ok else 'FAIL  ') + name)
    if not ok: failed.append(name)


def add_ado_task(frame, tid, title, ado_id, typ):
    frame.evaluate("""([tid, title, id, typ]) => { const P = window.__prioritizer;
      P.state.tasks.push({id: tid, title, listId: P.state.lists[0].id, value: 3, effort: 'S', created: '2026-10-14', ado: {id, type: typ, state: 'Active', url: 'http://ado/' + id, project: 'p'}});
      P.state = P.sanitize(P.state); P.commit(); }""", [tid, title, ado_id, typ])


def main():
    serve(8802, functools.partial(Static, directory=ROOT))
    serve(4300, Mock)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={'width': 1280, 'height': 800})
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.route('**/fonts.g*/**', lambda r: r.abort())

        pg.goto(HUB + '/'); pg.wait_for_timeout(800)
        check('opens on Prioritizer', pg.url.endswith('#/prioritizer'))
        frame = next(f for f in pg.frames if f.url.endswith('/prioritizer/'))
        frame.on('pageerror', lambda e: errors.append(str(e)))
        check('Prioritizer hides its theme button in the hub', frame.evaluate("document.getElementById('themeBtn').hidden"))
        add_ado_task(frame, 'a1', 'Fix login', '123', 'Bug')
        check('no stage chips before the Dashboard connects', frame.locator('.chip.eng').count() == 0)

        pg.click('.app-btn[data-app=dashboard]'); pg.wait_for_timeout(1500)
        check('Dashboard connects and shows the frame', pg.locator('#pane-dashboard iframe').count() == 1)
        check('Dashboard header shows version and workspace', 'eng-agents 1.5.0 · work' in pg.inner_text('#pane-dashboard .dhead'))
        check('theme sent to the dashboard', any(m.get('type') == 'eng-theme' for m in LOG))

        pg.keyboard.press('Alt+1'); pg.wait_for_timeout(1500)
        chip = frame.locator('.chip.eng')
        check('Alt+1 returns to Prioritizer', pg.url.endswith('#/prioritizer'))
        check('ADO task shows its stage', chip.count() == 1 and 'Build 2/5' in chip.inner_text())
        chip.click(); pg.wait_for_timeout(1000)
        check('stage chip opens the Dashboard at that item', pg.url.endswith('#/dashboard') and {'type': 'eng-focus', 'id': '123'} in LOG)

        pg.click('#themeBtn'); pg.click('.menu [data-th=nord]'); pg.wait_for_timeout(500)
        check('theme reaches Prioritizer', frame.evaluate('document.documentElement.dataset.theme') == 'nord')
        check('theme reaches the dashboard', {'type': 'eng-theme', 'theme': 'nord'} in LOG)

        pg.keyboard.press('Alt+1'); pg.wait_for_timeout(300); frame.click('#main'); pg.keyboard.press('Alt+2'); pg.wait_for_timeout(400)
        check('Alt+2 inside Prioritizer switches apps', pg.url.endswith('#/dashboard'))

        pg.keyboard.press('Alt+1'); pg.wait_for_timeout(300)
        add_ado_task(frame, 'a2', 'New story', '456', 'User Story'); pg.wait_for_timeout(300)
        frame.locator('.row', has_text='New story').first.click(); pg.wait_for_timeout(300)
        frame.click('[data-d=eng-start][data-lane=feature]'); pg.wait_for_timeout(600)
        check('Start as feature reaches the dashboard', {'start': {'id': '456', 'lane': 'feature'}} in LOG)

        pg.goto(HUB + '/#/dashboard'); pg.wait_for_timeout(1200)
        pg.click('[data-eng=settings]'); pg.click('[data-eng=off]'); pg.wait_for_timeout(300)
        check('Disconnect turns stages off', pg.evaluate("JSON.parse(localStorage.getItem('em.eng')).on") is False)

        sp = b.new_page(); sp.route('**/fonts.g*/**', lambda r: r.abort())
        sp.on('pageerror', lambda e: errors.append(str(e)))
        sp.goto(HUB + '/prioritizer/'); sp.wait_for_timeout(600)
        check('Prioritizer still works on its own', not sp.evaluate("document.getElementById('themeBtn').hidden") and sp.locator('#snav .sitem').count() == 6)

        check('no page errors', not errors)
        if errors: print('  ' + '\n  '.join(errors))
        b.close()
    print('\nAll checks passed.' if not failed else f'\n{len(failed)} failed.')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
