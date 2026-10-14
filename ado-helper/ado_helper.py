#!/usr/bin/env python3
"""
Prioritizer ADO helper.

A tiny local server that lets the Prioritizer app show your Azure DevOps work items.
It reads your PAT from an environment variable, calls your ADO server, and answers
only on this computer (127.0.0.1). Your PAT never leaves this machine except in the
requests to your own ADO server. Python 3.8+ standard library only, nothing to install.

Run:      py ado_helper.py            (first run asks for your ADO URL and PAT variable name)
Options:  --setup     re-run the setup questions
          --add-pr-source  add a collection + project to pull your pull requests from
          --test      check the connection, print what it finds, and exit
          --startup   start automatically when you log in to Windows
          --no-startup  undo --startup
"""
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = '1.1.0'
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, 'ado-helper.json')
DEFAULTS = {
    'base_url': '',                       # e.g. https://tfs.example.com/DefaultCollection
    'pat_env': 'ADO_PAT',                 # name of the environment variable holding your PAT
    'api_version': '6.0',
    'port': 4791,
    'types': ['Issue', 'Bug', 'User Story'],
    'closed_states': ['Resolved', 'Closed', 'Done'],  # counts as finished in the app
    'removed_states': ['Removed'],        # counts as won't do in the app
    'allowed_origins': ['https://prioritizer.alexisdavidson.org'],
    'verify_ssl': True,
    # Pull requests to review. Each source is a collection URL + project, optionally limited to some repos.
    # Leave empty to skip PRs. Example:
    # [{"base_url": "https://tfs.example.com/Collection", "project": "Platform", "repos": []}]
    'pr_sources': [],
    'pr_teams': [],                       # team names that count as yours; empty = every team you're on
}
DEV_ORIGINS = ('http://localhost', 'http://127.0.0.1')  # any port, for testing a local copy of the app
LOCAL_HOSTS = ('127.0.0.1', 'localhost')


# ---------------------------------------------------------------- config

def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg.update(json.load(f))
    cfg['base_url'] = cfg['base_url'].rstrip('/')
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)


def setup(cfg):
    print('\nPrioritizer ADO helper setup\n')
    print('1) Your ADO collection URL, the part before the project name.')
    print('   Example: https://tfs.yourcompany.com/DefaultCollection')
    url = input(f'   URL [{cfg["base_url"] or "required"}]: ').strip()
    if url:
        cfg['base_url'] = url.rstrip('/')
    print('\n2) The name of the environment variable that holds your PAT (not the PAT itself).')
    env = input(f'   Variable name [{cfg["pat_env"]}]: ').strip()
    if env:
        cfg['pat_env'] = env
    save_config(cfg)
    if not cfg.get('pr_sources'):
        print('\n3) Pull requests to review (optional). Press Enter to skip.')
        add_pr_sources(cfg)
    print(f'\nSaved to {CONFIG_PATH}. Edit that file to change work item types, states or PR sources.\n')
    return cfg


def add_pr_sources(cfg):
    srcs = list(cfg.get('pr_sources') or [])
    while True:
        default = cfg['base_url'] if not srcs else ''
        url = input(f'   Collection URL for PRs [{default or "Enter to finish"}]: ').strip() or default
        if not url:
            break
        proj = input('   Project name: ').strip()
        if not proj:
            break
        repos = input('   Only these repos, comma separated [all]: ').strip()
        srcs.append({'base_url': url.rstrip('/'), 'project': proj,
                     'repos': [r.strip() for r in repos.split(',') if r.strip()]})
        default = ''
        if input('   Add another? [y/N]: ').strip().lower() != 'y':
            break
    cfg['pr_sources'] = srcs
    save_config(cfg)
    return cfg


def pat(cfg):
    v = os.environ.get(cfg['pat_env'], '').strip()
    if not v:
        raise HelperError(f'Environment variable {cfg["pat_env"]} is empty or missing. '
                          'If you just set it, open a new terminal window and run the helper again.')
    return v


class HelperError(Exception):
    pass


# ---------------------------------------------------------------- ADO client

class Ado:
    def __init__(self, cfg, base=None):
        self.cfg = cfg
        self.base = (base or cfg['base_url']).rstrip('/')
        if not self.base:
            raise HelperError('No ADO URL set. Run: py ado_helper.py --setup')
        token = base64.b64encode((':' + pat(cfg)).encode()).decode()
        self.headers = {'Authorization': 'Basic ' + token, 'Accept': 'application/json',
                        'Content-Type': 'application/json'}
        self.ctx = ssl.create_default_context() if cfg.get('verify_ssl', True) else ssl._create_unverified_context()

    def call(self, method, path, body=None, query=None, project=None, api=None):
        q = dict(query or {})
        q['api-version'] = api or self.cfg['api_version']
        scope = f'{self.base}/{urllib.parse.quote(project)}' if project else self.base
        url = f'{scope}/_apis/{path}?{urllib.parse.urlencode(q)}'
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=45) as r:
                raw = r.read()
                if r.headers.get_content_type() != 'application/json':
                    raise HelperError('ADO answered with a sign-in page instead of data. Check the URL and that the PAT is valid.')
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                need = 'Code (Read)' if '/git/' in url else 'Project and Team (Read)' if '/teams' in url else 'Work Items (Read)'
                raise HelperError(f'ADO rejected the PAT (HTTP {e.code}) for {self.base}. It may be expired or missing the {need} scope.')
            if e.code == 404:
                raise HelperError(f'ADO URL not found (HTTP 404): {url.split("?")[0]}. Check the collection URL and project name.')
            detail = ''
            try:
                detail = json.loads(e.read()).get('message', '')
            except Exception:
                pass
            raise HelperError(f'ADO error HTTP {e.code}. {detail}'.strip())
        except urllib.error.URLError as e:
            raise HelperError(f'Could not reach ADO at {self.base}. Are you on VPN? ({e.reason})')

    def wiql(self, where):
        q = f'SELECT [System.Id] FROM WorkItems WHERE {where} ORDER BY [System.ChangedDate] DESC'
        res = self.call('POST', 'wit/wiql', {'query': q})
        return [w['id'] for w in res.get('workItems', [])]

    def details(self, ids):
        out = {}
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            res = self.call('POST', 'wit/workitemsbatch', {'ids': chunk, '$expand': 'Links', 'errorPolicy': 'omit'})
            for w in res.get('value') or []:
                if w and w.get('id'):
                    out[w['id']] = w
        return out


def wiql_list(values):
    return ', '.join("'" + v.replace("'", "''") + "'" for v in values)


def person(v):
    if isinstance(v, dict):
        return v.get('displayName') or v.get('uniqueName') or ''
    return str(v or '').split('<')[0].strip()


def day(v):
    return v[:10] if isinstance(v, str) and len(v) >= 10 else None


def shape(w, base):
    f = w.get('fields', {})
    project = f.get('System.TeamProject', '')
    link = (((w.get('_links') or {}).get('html') or {}).get('href')
            or f'{base}/{urllib.parse.quote(project)}/_workitems/edit/{w["id"]}')
    return {
        'id': w['id'],
        'title': f.get('System.Title', ''),
        'type': f.get('System.WorkItemType', ''),
        'state': f.get('System.State', ''),
        'project': project,
        'assignedTo': person(f.get('System.AssignedTo')),
        'priority': f.get('Microsoft.VSTS.Common.Priority'),
        'due': day(f.get('Microsoft.VSTS.Scheduling.DueDate') or f.get('Microsoft.VSTS.Scheduling.TargetDate')),
        'changed': f.get('System.ChangedDate'),
        'url': link,
    }


def sync(cfg, known, known_prs=None):
    """Open items assigned to me, plus what happened to known items that dropped off."""
    ado = Ado(cfg)
    types, done = wiql_list(cfg['types']), wiql_list(cfg['closed_states'] + cfg['removed_states'])
    mine = ado.wiql(f'[System.AssignedTo] = @Me AND [System.WorkItemType] IN ({types}) AND [System.State] NOT IN ({done})')
    mine_set = set(mine)
    dropped = [i for i in known if i not in mine_set]
    info = ado.details(mine + dropped)
    items = [shape(info[i], ado.base) for i in mine if i in info]
    gone = []
    for i in dropped:
        w = info.get(i)
        if not w:
            gone.append({'id': i, 'reason': 'missing'})
            continue
        s = shape(w, ado.base)
        if s['state'] in cfg['closed_states']:
            s['reason'] = 'closed'
        elif s['state'] in cfg['removed_states']:
            s['reason'] = 'removed'
        elif s['type'] not in cfg['types']:
            s['reason'] = 'filtered'
        else:
            s['reason'] = 'reassigned'   # still open, right type, but no longer assigned to you
        gone.append(s)
    out = {'items': items, 'gone': gone, 'syncedAt': datetime.now(timezone.utc).isoformat()}
    if cfg.get('pr_sources'):
        try:   # a PR problem shouldn't stop work items from syncing
            out['prs'] = sync_prs(cfg, known_prs or [])
        except HelperError as e:
            out['prError'] = str(e)
    return out


# ---------------------------------------------------------------- pull requests
#
# Tiers (how much a PR is waiting on you):
#   blocking  you were added by name as a Required reviewer
#   asked     you were added by name, optional
#   pool      only one of your teams was added, so any teammate can take it
# Your vote decides whether it's on you: none = to review, "Waiting for author" = waiting,
# Approve / Approve with suggestions / Reject = done. For team-only PRs, a teammate voting for
# the team also counts as done.

APPROVED, SUGGEST, WAITING, REJECTED = 10, 5, -5, -10


def pr_key(src, pid):
    return f'{src["base_url"].rstrip("/")}|{src["project"]}|{pid}'


class PrSource:
    def __init__(self, cfg, src):
        self.src = dict(src, base_url=src['base_url'].rstrip('/'))
        self.ado = Ado(cfg, self.src['base_url'])
        self.project = self.src['project']
        self.repos = {r.lower() for r in self.src.get('repos') or []}
        self.cfg = cfg
        self.me = None
        self.teams = {}     # id -> name

    def identify(self):
        """Who am I here, and which teams am I on."""
        for url in (self.ado.base, '/'.join(self.ado.base.split('/')[:3])):   # collection, then server root
            try:
                res = Ado(self.cfg, url).call('GET', 'connectionData', api='1.0')
                self.me = (res.get('authenticatedUser') or {}).get('id')
            except HelperError:
                continue
            if self.me:
                break
        if not self.me:
            raise HelperError(f'Could not tell who you are on {self.ado.base}.')
        wanted = {t.lower() for t in self.cfg.get('pr_teams') or []}
        try:
            res = self.ado.call('GET', f'projects/{urllib.parse.quote(self.project)}/teams', query={'$mine': 'true', '$top': 500})
            for t in res.get('value', []):
                if not wanted or t['name'].lower() in wanted:
                    self.teams[t['id']] = t['name']
        except HelperError as e:
            self.team_error = str(e)   # still works for PRs you're named on

    def active(self):
        """Active PRs where you or one of your teams is a reviewer, by PR id."""
        out = {}
        for rid in [self.me] + list(self.teams):
            res = self.ado.call('GET', 'git/pullrequests', project=self.project, query={
                'searchCriteria.status': 'active', 'searchCriteria.reviewerId': rid, '$top': 500})
            for pr in res.get('value', []):
                if self.repos and ((pr.get('repository') or {}).get('name') or '').lower() not in self.repos:
                    continue
                out[pr['pullRequestId']] = pr
        return out

    def one(self, pid):
        try:
            return self.ado.call('GET', f'git/pullrequests/{pid}', project=self.project)
        except HelperError as e:
            if 'HTTP 404' in str(e):
                return None
            raise

    def classify(self, pr):
        """(status, info). status: review, waiting, reviewed, covered, unassigned, draft, own, merged, abandoned."""
        revs = pr.get('reviewers') or []
        mine = next((r for r in revs if r.get('id') == self.me), None)
        teams = [r for r in revs if r.get('id') in self.teams]
        repo = (pr.get('repository') or {}).get('name', '')
        author = person(pr.get('createdBy'))
        req_others = [r for r in revs if r.get('isRequired') and r.get('id') != self.me]
        info = {
            'key': pr_key(self.src, pr['pullRequestId']),
            'id': pr['pullRequestId'],
            'title': pr.get('title', ''),
            'repo': repo,
            'project': self.project,
            'author': author,
            'created': day(pr.get('creationDate')),
            'url': f'{self.ado.base}/{urllib.parse.quote(self.project)}/_git/{urllib.parse.quote(repo)}/pullrequest/{pr["pullRequestId"]}',
            'tier': 'blocking' if mine and mine.get('isRequired') else 'asked' if mine else 'pool',
            'via': [self.teams[r['id']] for r in teams],
            # every other required reviewer already approved: you're the last one holding it up
            'lastBlocker': bool(mine and mine.get('isRequired') and all(r.get('vote', 0) >= SUGGEST for r in req_others)),
        }
        status = pr.get('status')
        if status == 'completed':
            return 'merged', info
        if status == 'abandoned':
            return 'abandoned', info
        if (pr.get('createdBy') or {}).get('id') == self.me:
            return 'own', info
        if pr.get('isDraft'):
            return 'draft', info
        if not mine and not teams:
            return 'unassigned', info
        vote = mine.get('vote', 0) if mine else 0
        if vote == WAITING:
            return 'waiting', info
        if vote:
            return 'reviewed', info
        team_ids = {r['id'] for r in teams}
        voted_for_team = any(r.get('vote', 0) and team_ids & {v.get('id') for v in r.get('votedFor') or []} for r in revs)
        if not mine and (voted_for_team or any(r.get('vote', 0) for r in teams)):
            return 'covered', info
        return 'review', info


def sync_prs(cfg, known):
    """PRs on you now, plus what happened to known PRs that dropped off."""
    items, gone, notes = [], [], []
    known = set(known)
    for src in cfg.get('pr_sources') or []:
        ps = PrSource(cfg, src)
        ps.identify()
        if getattr(ps, 'team_error', None):
            notes.append(f'Team-only PRs skipped for {ps.project}: {ps.team_error}')
        active = ps.active()
        seen = set()
        for pr in active.values():
            st, info = ps.classify(pr)
            if st in ('review', 'waiting'):
                info['waiting'] = st == 'waiting'
                items.append(info)
                seen.add(info['key'])
            elif info['key'] in known:
                info['reason'] = st
                gone.append(info)
                seen.add(info['key'])
        prefix = pr_key(src, '')
        for key in known:
            if key in seen or not key.startswith(prefix):
                continue
            pid = key[len(prefix):]
            pr = ps.one(int(pid)) if pid.isdigit() else None
            if not pr:
                gone.append({'key': key, 'reason': 'missing'})
                continue
            st, info = ps.classify(pr)
            if st in ('review', 'waiting'):   # repo filter or paging missed it; still yours
                info['waiting'] = st == 'waiting'
                items.append(info)
            else:
                info['reason'] = st
                gone.append(info)
    return {'items': items, 'gone': gone, 'notes': notes}


# ---------------------------------------------------------------- local server

class Handler(BaseHTTPRequestHandler):
    cfg = None
    server_version = 'PrioritizerAdoHelper/' + VERSION

    def log_message(self, fmt, *args):
        sys.stderr.write('%s  %s\n' % (datetime.now().strftime('%H:%M:%S'), fmt % args))

    def origin_ok(self):
        o = self.headers.get('Origin', '')
        allowed = self.cfg['allowed_origins']
        return o in allowed or any(o == d or o.startswith(d + ':') for d in DEV_ORIGINS)

    def host_ok(self):
        # blocks DNS rebinding: the request must be addressed to this computer by name
        host = (self.headers.get('Host') or '').rsplit(':', 1)[0].strip('[]')
        return host in LOCAL_HOSTS

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        o = self.headers.get('Origin')
        if o and self.origin_ok():
            self.send_header('Access-Control-Allow-Origin', o)
            self.send_header('Vary', 'Origin')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guard(self):
        if not self.host_ok() or not self.origin_ok():
            self.send_json(403, {'error': 'Not allowed from this site.'})
            return False
        return True

    def do_OPTIONS(self):
        if not self.guard():
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin'))
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Max-Age', '600')
        self.send_header('Vary', 'Origin')
        self.end_headers()

    def do_GET(self):
        if not self.guard():
            return
        if self.path.split('?')[0] == '/health':
            return self.send_json(200, {'ok': True, 'version': VERSION, 'base': self.cfg['base_url'], 'types': self.cfg['types'],
                                        'prSources': [f'{s["base_url"]} / {s["project"]}' for s in self.cfg.get('pr_sources') or []]})
        self.send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.guard():
            return
        if self.path.split('?')[0] != '/sync':
            return self.send_json(404, {'error': 'Not found'})
        try:
            n = min(int(self.headers.get('Content-Length') or 0), 1_000_000)
            body = json.loads(self.rfile.read(n) or b'{}')
            known = [int(x) for x in body.get('known', []) if str(x).isdigit()][:5000]
            known_prs = [str(x)[:500] for x in body.get('knownPrs', []) if isinstance(x, str)][:2000]
            self.send_json(200, sync(self.cfg, known, known_prs))
        except HelperError as e:
            self.send_json(502, {'error': str(e)})
        except Exception as e:  # keep running whatever happens
            self.send_json(500, {'error': f'Helper error: {e}'})


def serve(cfg):
    Handler.cfg = cfg
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', int(cfg['port'])), Handler)
    except OSError:
        raise HelperError(f'Port {cfg["port"]} is busy. The helper may already be running.')
    print(f'Prioritizer ADO helper {VERSION} running at http://127.0.0.1:{cfg["port"]}')
    print(f'ADO: {cfg["base_url"]}   PAT from: %{cfg["pat_env"]}%')
    print('Leave this window open (or use --startup). Press Ctrl+C to stop.')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------- Windows startup

def startup_file():
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise HelperError('--startup only works on Windows.')
    return os.path.join(appdata, r'Microsoft\Windows\Start Menu\Programs\Startup', 'prioritizer-ado-helper.cmd')


def install_startup():
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
    runner = pyw if os.path.exists(pyw) else exe
    with open(startup_file(), 'w', encoding='utf-8') as f:
        f.write(f'@echo off\r\nstart "" "{runner}" "{os.path.abspath(__file__)}"\r\n')
    print(f'It will start in the background when you log in: {startup_file()}')


def main():
    if sys.stdout is None or sys.stderr is None:  # started hidden with pythonw: log to a file instead
        log = open(os.path.join(HERE, 'ado-helper.log'), 'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    args = set(sys.argv[1:])
    cfg = load_config()
    try:
        if '--no-startup' in args:
            p = startup_file()
            if os.path.exists(p):
                os.remove(p)
            print('Removed from startup.')
            return
        if '--setup' in args or not cfg['base_url']:
            if not sys.stdin or not sys.stdin.isatty():
                raise HelperError('Not set up yet. Run it once in a terminal: py ado_helper.py')
            cfg = setup(cfg)
        if '--add-pr-source' in args:
            add_pr_sources(cfg)
        if '--startup' in args:
            install_startup()
        if '--test' in args:
            r = sync(cfg, [])
            print(f'Connected. {len(r["items"])} open work items assigned to you:')
            for it in r['items'][:15]:
                print(f'  #{it["id"]}  {it["type"]:<11} {it["state"]:<10} {it["title"]}')
            if not cfg.get('pr_sources'):
                print('\nNo PR sources set. Add one with: py ado_helper.py --add-pr-source')
            elif r.get('prError'):
                print('\nPull requests failed: ' + r['prError'])
            else:
                prs = r['prs']['items']
                print(f'\n{len(prs)} pull requests waiting on you:')
                order = {'blocking': 0, 'asked': 1, 'pool': 2}
                for p in sorted(prs, key=lambda p: (order[p['tier']], p['created'] or '')):
                    tag = 'waiting' if p['waiting'] else p['tier'] + (' (last one)' if p['lastBlocker'] else '')
                    print(f'  PR {p["id"]:<6} {tag:<20} {p["repo"]}: {p["title"]}')
                for n in r['prs']['notes']:
                    print('  Note: ' + n)
            return
        serve(cfg)
    except HelperError as e:
        print('\n' + str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
