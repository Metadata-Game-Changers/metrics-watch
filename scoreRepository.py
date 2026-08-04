#!/usr/bin/env python3
"""Score DataCite repositories against the MGC use cases, automatically.

Command-line companion to Metadata Completeness
(https://metadata-game-changers.github.io/recuration-watch/completeness.html):
reads the same public FAIR_spirals.json use-case catalog, samples records from
the DataCite API with the same rules, counts each concept with the same jq
queries, and writes the same useCaseReport JSON the web tool downloads —
so reports from both are interchangeable.

Requires python3 (standard library only) and the `jq` binary on PATH
(preinstalled on GitHub Actions ubuntu runners; `brew install jq` on macOS).

Usage:
  python3 scoreRepository.py --client sjyq.oozvia
  python3 scoreRepository.py --consortium oaem --max 200
  python3 scoreRepository.py --config config.json

Output matches the MGC score-archive conventions exactly (one folder per
repository, the layout the MGC history tooling reads):
  reports/<client-id>/<stem>_useCaseReport__YYYY-MM-DDThh.json   per-run snapshot
  reports/<client-id>/<stem>_useCaseHistory.json                 all runs of the series
where <stem> is the client id plus a query-derived label when a filter is set,
so filtered runs form their own series. The history file is re-derived from the
snapshots after every run — snapshots are canonical, histories are derived.
"""

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = 'https://api.datacite.org'
ALL_DATACITE = 'datacite.all'   # sentinel: score across all of DataCite (no client filter)
USER_AGENT = 'metrics-watch (https://github.com/Metadata-Game-Changers; mailto:info@metadatagamechangers.com)'

# Use-case groups, mirroring completeness.html: FAIR feeds the headline total;
# Projects and SHARE are reported as their own totals.
GROUPS = {
    'FAIR':     ['FAIR_Text', 'FAIR_Identifiers', 'FAIR_Connections', 'FAIR_Contacts'],
    'Projects': ['Project_Team', 'Project_Items', 'Project_Relations'],
    'SHARE':    ['SHARE_stewardship', 'SHARE_harmonization', 'SHARE_access', 'SHARE_reuse', 'SHARE_engagement'],
}


def api_get(path_and_query, retries=3):
    """GET a DataCite API URL (path + query, already encoded) with retries."""
    url = f'{API_BASE}{path_and_query}'
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            if attempt == retries - 1:
                raise RuntimeError(f'DataCite request failed after {retries} tries: {url} ({e})')
            time.sleep(5 * (attempt + 1))


def client_qs(client_id):
    """client-id filter, or nothing for the all-of-DataCite sentinel."""
    return '' if client_id == ALL_DATACITE else f'client-id={urllib.parse.quote(client_id)}&'


def consortium_repositories(consortium_id):
    """All repository client ids under a DataCite consortium.

    Two steps: /providers?consortium-id={id} lists the consortium organizations,
    then /clients?provider-id={org} lists each organization's repositories.
    (The one-hop /clients?consortium-id filter is silently ignored by the API —
    it returns every client in DataCite — so do not use it.)"""
    def pages(path):
        page, out = 1, []
        while True:
            d = api_get(f'{path}&page%5Bsize%5D=1000&page%5Bnumber%5D={page}')
            out += [x['id'] for x in d.get('data', [])]
            if page >= d.get('meta', {}).get('totalPages', 1):
                return out
            page += 1

    orgs = pages(f'/providers?consortium-id={urllib.parse.quote(consortium_id)}')
    if not orgs:
        return []
    repos = []
    for org in orgs:
        repos += pages(f'/clients?provider-id={urllib.parse.quote(org)}')
    print(f'Consortium {consortium_id}: {len(orgs)} organizations, {len(repos)} repositories', flush=True)
    return sorted(set(repos))


def fetch_client_meta(client_id):
    if client_id == ALL_DATACITE:
        return {'name': 'All of DataCite'}
    try:
        d = api_get(f'/clients/{urllib.parse.quote(client_id)}')
        return {'name': d.get('data', {}).get('attributes', {}).get('name') or client_id}
    except Exception:
        return {'name': client_id}


def fetch_records(client_id, cap, random_sample, resource_type, query):
    """Sample records, mirroring completeness.html's fetchRepo: peek at the matching
    total, fall back to a deterministic fetch when everything fits within the cap,
    otherwise draw independent random pages and deduplicate by DOI."""
    filt = ''
    if resource_type:
        filt += f'&resource-type-id={urllib.parse.quote(resource_type)}'
    if query:
        filt += f'&query={urllib.parse.quote(query)}'
    page_size = min(1000, cap)
    records, seen = [], set()
    matching = None
    effective_random = random_sample

    peek = api_get(f'/dois?{client_qs(client_id)}page%5Bsize%5D=1&disable-facets=true{filt}')
    total = peek.get('meta', {}).get('total')
    if isinstance(total, int):
        matching = total
        if total <= cap:
            effective_random = False
        if total == 0:
            return [], 0, False

    page, requests = 1, 0
    while len(records) < cap:
        requests += 1
        base = f'/dois?{client_qs(client_id)}page%5Bsize%5D={page_size}&affiliation=true&publisher=true{filt}'
        url = (f'{base}&random=true&disable-facets=true' if effective_random
               else f'{base}&page%5Bnumber%5D={page}')
        d = api_get(url)
        batch = d.get('data', [])
        added = 0
        for rec in batch:
            if rec['id'] not in seen:
                seen.add(rec['id'])
                records.append(rec)
                added += 1
        t = d.get('meta', {}).get('total')
        if isinstance(t, int):
            matching = t
        if effective_random:
            if len(records) >= cap or (matching is not None and len(records) >= matching):
                break
            if added == 0 or requests >= 30:
                break
        else:
            total_pages = d.get('meta', {}).get('totalPages', page)
            if not batch or page >= total_pages or page >= 10:
                break
            page += 1
        print(f'    fetched {len(records)} of {min(cap, matching or cap)}…', flush=True)
    return records[:cap], matching, effective_random


def count_expr(q):
    """The verbatim queries are `.data[] | select(<EXPR>) | { …projection… }`.
    For scoring we only need how many records the select admits, so drop the
    projection (everything from the first `{`) — identical to the web tool."""
    i = q.find('{')
    if i < 0:
        return q
    return re.sub(r'\|\s*$', '', q[:i]).strip()


def score(records, spirals):
    """Count every concept over the sample with jq — one combined program that
    evaluates each DISTINCT count expression once (the web tool's exact scheme),
    with a per-expression fallback if any expression fails at runtime."""
    flat = []
    for s in spirals:
        for it in s['items']:
            if it.get('jq_query'):
                flat.append({'code': s['code'], 'concept': it['concept'], 'jq': it['jq_query']})

    expr_list, expr_index, flat_expr = [], {}, []
    for it in flat:
        e = count_expr(it['jq'])
        if e not in expr_index:
            expr_index[e] = len(expr_list)
            expr_list.append(e)
        flat_expr.append(expr_index[e])

    matched = [0] * len(expr_list)
    errored = [False] * len(expr_list)
    input_str = json.dumps({'data': records})
    program = '{' + ','.join(f'"c{i}":([ {e} ]|length)' for i, e in enumerate(expr_list)) + '}'

    def run_jq(prog, inp):
        p = subprocess.run(['jq', '-c', prog], input=inp, capture_output=True, text=True)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else f'jq exited {p.returncode}')
        return p.stdout

    try:
        obj = json.loads(run_jq(program, input_str))
        for i in range(len(expr_list)):
            matched[i] = int(obj.get(f'c{i}', 0))
    except Exception as e:
        print(f'    combined scoring failed ({e}); falling back to per-query…', flush=True)
        for i, expr in enumerate(expr_list):
            try:
                matched[i] = int(run_jq(f'[ {expr} ] | length', input_str).strip())
            except Exception:
                errored[i] = True

    total = len(records)
    by_code = {}
    for s in spirals:
        items = []
        for it, u in zip(flat, flat_expr):
            if it['code'] != s['code']:
                continue
            comp = 0.0 if errored[u] else (matched[u] / total if total > 0 else 0.0)
            comp = min(comp, 1.0)
            items.append({'concept': it['concept'], 'matched': matched[u], 'comp': comp, 'errored': errored[u]})
        items.sort(key=lambda i: i['concept'])
        n = len(items) or 1
        by_code[s['code']] = {
            'spiral': s,
            'res': {
                'items': items,
                'average': sum(min(i['comp'], 1.0) for i in items) / n,
                'exist': sum(1 for i in items if i['comp'] > 0),
                'complete': sum(1 for i in items if i['comp'] >= 1),
                'total': total,
            },
        }
    return by_code


def weighted_total(by_code, codes):
    """Concept-count-weighted average of a set of use-case codes."""
    total_score = total_count = 0
    for code in codes:
        e = by_code.get(code)
        if not e:
            continue
        n = len(e['spiral']['items'])
        total_score += e['res']['average'] * n
        total_count += n
    return total_score / total_count if total_count else 0.0


def build_report(client_id, repo_name, by_code, spirals, records, matching, used_random, query, stamp):
    """The useCaseReport JSON — same structure the web tool downloads."""
    # floor(x·10⁴+0.5): JS Math.round semantics (half UP) — Python's round() banker's-rounds
    # halves down (0.53125 -> 0.5312 vs the web tool's 0.5313), breaking report identity
    rnd = lambda x: int(x * 10000 + 0.5) / 10000
    analyzed = len(records)
    repo_total = matching if matching is not None else analyzed
    sampling = (('random sample' if used_random else 'sequential sample')
                if repo_total > analyzed else 'all records')
    use_cases = []
    for s in spirals:
        e = by_code.get(s['code'])
        if not e:
            continue
        res = e['res']
        use_cases.append({
            'code': s['code'],
            'title': s['title'],
            'dialect': s['dialect'],
            'description': s['description'],
            'records': res['total'],
            'average': rnd(res['average']),
            'exist': res['exist'],
            'complete': res['complete'],
            'items': [{'concept': i['concept'],
                       'completeness': None if i['errored'] else rnd(i['comp'])}
                      for i in res['items']],
        })
    return {
        'repository': {
            'id': client_id,
            'name': repo_name or client_id,
            'dateTime': stamp,
            'records': analyzed,
            'totalInRepository': repo_total,
            'sampling': sampling,
            'query': query or '',
            'fairTotal': rnd(weighted_total(by_code, GROUPS['FAIR'])),
            'projectsTotal': rnd(weighted_total(by_code, GROUPS['Projects'])),
            'shareTotal': rnd(weighted_total(by_code, GROUPS['SHARE'])),
        },
        'useCases': use_cases,
    }


def safe_id(client_id):
    return ''.join(ch if (ch.isalnum() or ch in '._-') else '_' for ch in (client_id or 'repository'))


def query_label(query, max_len=80):
    """A compact, filesystem-safe label for a query, so per-run output files don't
    collide (mirrors the MGC desktop tooling). Empty string if no query."""
    if not query:
        return ''
    label = re.sub(r'_+', '_', safe_id(query)).strip('_')
    return label[:max_len].rstrip('_')


def series_label(target):
    """Filename label for a target's filters — an explicit "label" wins, else it is
    derived from the resource type and/or query. Distinct labels = distinct series."""
    if target.get('label'):
        return re.sub(r'_+', '_', safe_id(target['label'])).strip('_')
    parts = []
    if target['resource_type']:
        parts.append(f"Resource-type-id_{safe_id(target['resource_type'])}")
    if target['query']:
        parts.append(query_label(target['query']))
    return '_'.join(p for p in parts if p)


def build_history(dest, stem, repo_id, label):
    """Re-derive <stem>_useCaseHistory.json from this series' snapshots — the same
    structure the MGC score archive uses (snapshots canonical, histories derived)."""
    snap_re = re.compile(re.escape(stem) + r'_useCaseReport__(\d{4}-\d{2}-\d{2}T\d{2})\.json$')
    snaps = sorted((m.group(1), p) for p in dest.iterdir()
                   if (m := snap_re.fullmatch(p.name)))
    snapshots = []
    for stamp, path in snaps:
        rep = json.loads(path.read_text(encoding='utf-8'))
        repository = rep.get('repository')
        snapshots.append({'dateTime': (repository or {}).get('dateTime') or stamp,
                          'source': path.name,
                          'repository': repository,
                          'useCases': rep.get('useCases', [])})
    if not snapshots:
        return None
    out = {'repository': {'id': repo_id, **({'queryLabel': label} if label else {})},
           'note': 'Derived from the snapshot useCaseReport JSONs listed in each entry; '
                   'regenerated by scoreRepository.py on every run rather than edited.',
           'snapshots': snapshots}
    target = dest / f'{stem}_useCaseHistory.json'
    target.write_text(json.dumps(out, indent=1) + '\n', encoding='utf-8')
    return target


def score_one(target, spirals, out_dir, stamp):
    client_id = target['client']
    tag = f"{client_id}{' · ' + target['label'] if target.get('label') else (' · query' if target['query'] else '')}"
    print(f'  {tag}: fetching…', flush=True)
    records, matching, used_random = fetch_records(
        client_id, target['max'], target['random'], target['resource_type'], target['query'])
    if not records:
        print(f'  {tag}: no matching records — skipped', flush=True)
        return None
    print(f'  {tag}: scoring {len(records)} records '
          f'({matching if matching is not None else "?"} matching)…', flush=True)
    by_code = score(records, spirals)
    meta = fetch_client_meta(client_id)
    report = build_report(client_id, meta['name'], by_code, spirals,
                          records, matching, used_random, target['query'], stamp)
    safe = safe_id(client_id)
    label = series_label(target)
    stem = f'{safe}_{label}' if label else safe
    dest = out_dir / safe
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f'{stem}_useCaseReport__{stamp}.json'
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    build_history(dest, stem, client_id, label)
    fair = report['repository']['fairTotal']
    print(f'  {tag}: FAIR total {fair * 100:.0f}% → {path}', flush=True)
    return path


def schedule_due(schedule, today=None):
    """Is a set's schedule due today? daily: every day; weekly: Mondays;
    monthly: the 1st. The workflow cron fires daily so these checks line up."""
    today = today or datetime.now()
    return {'daily': True,
            'weekly': today.weekday() == 0,
            'monthly': today.day == 1}.get(schedule, today.day == 1)


def make_target(entry, defaults):
    """One scoring target from a config entry (a bare client-id string, or an object
    overriding query / resourceType / label / max / random) merged over set defaults."""
    if isinstance(entry, str):
        return {**defaults, 'client': entry}
    return {'client': entry.get('client') or entry.get('id') or '',
            'max': entry.get('max', defaults['max']),
            'random': defaults['random'] if entry.get('random') is None else bool(entry['random']),
            'resource_type': entry.get('resourceType', defaults['resource_type']),
            'query': entry.get('query', defaults['query']),
            'label': entry.get('label', '')}


def build_sets(args, cfg):
    """Resolve CLI + config into scoring sets: {name, schedule, targets}. A config with
    "sets" gets one per entry (each with its own schedule and defaults); a flat config
    or bare CLI flags become a single set."""
    # explicit CLI flags beat config values; otherwise config (set, then flat) wins
    cli = {'max': '--max' in sys.argv, 'random': '--sequential' in sys.argv,
           'resource_type': bool(args.resource_type), 'query': bool(args.query)}

    def defaults_from(over, base):
        return {'max': base['max'] if cli['max'] else over.get('max', base['max']),
                'random': base['random'] if (cli['random'] or over.get('random') is None) else bool(over['random']),
                'resource_type': base['resource_type'] if cli['resource_type'] else over.get('resourceType', base['resource_type']),
                'query': base['query'] if cli['query'] else over.get('query', base['query']),
                'label': ''}

    base = {'max': args.max, 'random': args.random,
            'resource_type': args.resource_type, 'query': args.query}
    key = lambda t: (t['client'], t['resource_type'], t['query'], t['label'])

    def targets_for(over, clients, consortium):
        d = defaults_from(over, base)
        targets = [make_target(e, d) for e in clients]
        if consortium:
            seen = {key(t) for t in targets}
            targets += [t for r in consortium_repositories(consortium)
                        if key(t := {**d, 'client': r}) not in seen]
        out, seen = [], set()
        for t in targets:
            if t['client'] and key(t) not in seen:
                seen.add(key(t)); out.append(t)
        return out

    if cfg.get('sets'):
        return [{'name': cs.get('name') or f'set{i + 1}',
                 'schedule': (cs.get('schedule') or 'monthly').lower(),
                 'targets': targets_for(cs, cs.get('repositories', []), cs.get('consortium') or '')}
                for i, cs in enumerate(cfg['sets'])]
    clients = args.client or cfg.get('repositories', [])
    consortium = args.consortium or cfg.get('consortium') or ''
    return [{'name': 'default', 'schedule': (cfg.get('schedule') or 'monthly').lower(),
             'targets': targets_for(cfg, clients, consortium)}]


def write_manifest(sets, out_dir):
    """docs/sets.json — which series belong to which set, for the suite's Set Viewer.
    History paths are repo-root-relative so the viewer can resolve them against the
    manifest's own URL. Regenerated every run from the full config (all sets, due or
    not); only series whose history file exists are listed."""
    manifest = {'generated': datetime.now().strftime('%Y-%m-%dT%H'), 'sets': []}
    for st in sets:
        series = []
        for t in st['targets']:
            safe = safe_id(t['client'])
            label = series_label(t)
            stem = f'{safe}_{label}' if label else safe
            path = out_dir / safe / f'{stem}_useCaseHistory.json'
            if path.exists():
                series.append({'client': t['client'], 'label': label, 'history': path.as_posix()})
        manifest['sets'].append({'name': st['name'], 'schedule': st['schedule'], 'series': series})
    Path('docs').mkdir(exist_ok=True)
    Path('docs/sets.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    print(f"docs/sets.json: {len(manifest['sets'])} set{'' if len(manifest['sets']) == 1 else 's'}", flush=True)


def main():
    ap = argparse.ArgumentParser(description='Score DataCite repositories against the MGC use cases.')
    ap.add_argument('--client', action='append', default=[],
                    help='repository client id (repeatable); "datacite.all" scores across all of DataCite')
    ap.add_argument('--consortium', default='', help='DataCite consortium id — scores every member repository')
    ap.add_argument('--config', default='', help='JSON config file (see config.json); CLI flags override it')
    ap.add_argument('--max', type=int, default=100, help='records per repository (1–1000·draws, default 100)')
    ap.add_argument('--sequential', dest='random', action='store_false',
                    help='most-recent records instead of a random sample')
    ap.add_argument('--resource-type', default='', help='DataCite resource-type-id filter (e.g. dataset)')
    ap.add_argument('--query', default='', help='DataCite query filter (e.g. IOOS)')
    ap.add_argument('--spirals', default='FAIR_spirals.json', help='use-case catalog (default FAIR_spirals.json)')
    ap.add_argument('--out', default='reports', help='output directory (default reports/)')
    ap.add_argument('--due', action='store_true',
                    help='score only the sets whose schedule is due today (the scheduled '
                         'workflow passes this; without it every set runs)')
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding='utf-8')) if args.config else {}
    sets = build_sets(args, cfg)
    all_sets = sets   # pre-due-filter: the manifest always reflects the whole config
    if not any(st['targets'] for st in sets):
        ap.error('nothing to score — give --client, --consortium, or a --config with repositories/sets')

    if args.due:
        skipped = [st['name'] for st in sets if not schedule_due(st['schedule'])]
        sets = [st for st in sets if schedule_due(st['schedule'])]
        if skipped:
            print(f'Not due today: {", ".join(skipped)}', flush=True)
        if not sets:
            print('Nothing due today — done.', flush=True)
            return

    if subprocess.run(['jq', '--version'], capture_output=True).returncode != 0:
        sys.exit('jq is required but not on PATH (https://jqlang.org/download/)')

    spirals = json.loads(Path(args.spirals).read_text(encoding='utf-8'))
    out_dir = Path(args.out)
    stamp = datetime.now().strftime('%Y-%m-%dT%H')   # to the hour, matches the web tool

    written, failed = 0, []
    for st in sets:
        n = len(st['targets'])
        print(f"Set {st['name']} ({st['schedule']}): {n} target{'' if n == 1 else 's'} — {stamp}", flush=True)
        for target in st['targets']:
            try:
                if score_one(target, spirals, out_dir, stamp):
                    written += 1
            except Exception as e:
                failed.append(target['client'])
                print(f"  {target['client']}: FAILED — {e}", flush=True)
    if args.config and args.out == 'reports':
        write_manifest(all_sets, out_dir)   # config-driven runs keep the Set Viewer manifest fresh
    print(f'Done — {written} report{"" if written == 1 else "s"} written'
          + (f', {len(failed)} failed: {", ".join(failed)}' if failed else ''), flush=True)
    sys.exit(1 if failed and not written else 0)


if __name__ == '__main__':
    main()
