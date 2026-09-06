#!/usr/bin/env python3
"""Score an organization's DataCite records, client by client — for a LIST of organizations.

Command-line companion to Organization Completeness
(https://metadata-game-changers.github.io/recuration-watch/organizationCompleteness.html):
for each ROR it queries all of DataCite for records carrying the organization's
ROR (creators.affiliation.affiliationIdentifier), reads the client facet to find
the DataCite clients that hold them, samples and scores the organization's
records WITHIN each client against the MGC use cases, and adds an All-of-DataCite
reference column — the same population, no client filter.

Reuses the fetch/scoring engine from scoreRepository.py (same jq queries, same
sampling rules, same JS-compatible rounding), so numbers match the web tool.

Requires python3 (standard library only) and the `jq` binary on PATH.

Usage:
  python3 scoreOrganization.py --ror 04qw24q55
  python3 scoreOrganization.py --ror https://ror.org/04qw24q55 --ror 017zqws13 --top 5 --max 100
  python3 scoreOrganization.py --file organizations.txt --out organizationReports

organizations.txt: one ROR per line (bare id, ror: prefix, or full URL); text
after the first whitespace and `#` comments are ignored.

Output:
  <out>/ror_<id>/ror_<id>_orgCompletenessReport__YYYY-MM-DDThh.json   per organization
      (the same structure the web tool downloads, numbers rounded to 4 dp)
  <out>/organizationSummary__YYYY-MM-DDThh.csv                        one row per
      organization x client, with the web tool's Data Summary columns — the
      batch payoff: every organization in one analysis-ready table.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scoreRepository import (ALL_DATACITE, GROUPS, USER_AGENT, api_get,
                             fetch_records, score, weighted_total)

ROR_API = 'https://api.ror.org/v2/organizations'
TOTAL_CODES   = ['FAIR_Text', 'FAIR_Identifiers', 'FAIR_Connections', 'FAIR_Contacts']
PROJECT_CODES = GROUPS['Projects']
SHARE_CODES   = GROUPS['SHARE']
EXTRA_CODES   = ['DataCite_Relations', 'DataCite_ContributorTypes']

# floor(x·10⁴+0.5): JS Math.round semantics — matches scoreRepository/the web tools
rnd = lambda x: None if x is None else int(x * 10000 + 0.5) / 10000

ROR_ID_RE = re.compile(r'^0[a-hj-km-np-tv-z0-9]{6}\d{2}$')


def parse_ror(value):
    """'04qw24q55', 'ror:04qw24q55', or 'https://ror.org/04qw24q55' -> bare id."""
    v = value.strip()
    v = re.sub(r'^(https?://)?ror\.org/', '', v)
    v = re.sub(r'^ror:', '', v)
    if not ROR_ID_RE.match(v):
        raise ValueError(f'not a ROR id: {value!r}')
    return v


def fetch_org_name(ror_id):
    """The organization's display name from the ROR API (best-effort)."""
    try:
        url = f'{ROR_API}/{urllib.parse.quote("https://ror.org/" + ror_id)}'
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.load(r)
        for n in j.get('names', []):
            if 'ror_display' in (n.get('types') or []):
                return n.get('value')
        names = j.get('names', [])
        return names[0].get('value') if names else None
    except Exception:
        return None


def ror_query(ror_url, user_query):
    """The DataCite query selecting the organization's ROR-identified records
    (verbatim from organizationCompleteness.html, composed with the user query)."""
    clause = f'creators.affiliation.affiliationIdentifier:"{ror_url}"'
    return f'({user_query}) AND {clause}' if user_query else clause


def fetch_client_facet(query, resource_type):
    """The client facet for the ROR query: total matching records and the ten
    most common clients (id, title, count) — the web tool's fetchRepositoryFacet."""
    filt = (f'&resource-type-id={urllib.parse.quote(resource_type)}' if resource_type else '') \
         + f'&query={urllib.parse.quote(query)}'
    d = api_get(f'/dois?page%5Bsize%5D=1&disable-facets=false{filt}')
    meta = d.get('meta', {})
    total = meta.get('total')
    clients = [{'id': c['id'], 'title': c.get('title') or c['id'], 'count': c.get('count') or 0}
               for c in meta.get('clients', [])]
    return (total if isinstance(total, int) else None), clients


def client_totals(by_code):
    """Group totals + per-use-case averages (the web tool's repoTotals)."""
    t = {'fair': weighted_total(by_code, TOTAL_CODES),
         'projects': weighted_total(by_code, PROJECT_CODES),
         'share': weighted_total(by_code, SHARE_CODES)}
    for code, e in by_code.items():
        t[code] = e['res']['average'] if e else None
    return t


def score_org(ror_id, spirals, args):
    """One organization: facet -> top clients -> score each. Returns the report
    dict (web-tool structure) and the summary CSV rows for this organization."""
    ror_url = f'https://ror.org/{ror_id}'
    name = fetch_org_name(ror_id) or ror_url
    print(f'{name} ({ror_url})', flush=True)
    query = ror_query(ror_url, args.query)

    total, facet = fetch_client_facet(query, args.resource_type)
    if not total:
        print('  no records carry this ROR in creators.affiliation — skipped', flush=True)
        return None, []
    facet_sum = sum(c['count'] for c in facet)
    print(f'  {total:,} ROR-identified records · facet coverage '
          f'{facet_sum:,} of {total:,} ({100 * facet_sum / total:.1f}%) in {len(facet)} clients', flush=True)

    targets = [dict(c) for c in facet[:args.top]]
    if not args.no_all:
        targets.append({'id': ALL_DATACITE, 'title': 'All of DataCite', 'count': total})

    clients_out, rows = [], []
    for i, t in enumerate(targets, 1):
        print(f'  [{i}/{len(targets)}] {t["title"]} ({t["id"]})…', flush=True)
        records, matching, _used_random = fetch_records(
            t['id'], args.max, args.random, args.resource_type, query)
        if not records:
            print('    no matching records', flush=True)
            clients_out.append({'clientId': t['id'], 'name': t['title'], 'recordsScored': 0,
                                'matchingTotal': matching or 0, 'totals': None, 'useCases': None})
            rows.append([ror_url, name, t['id'], t['title'], 0, matching or 0]
                        + [''] * (5 + 1 + len(PROJECT_CODES) + 1 + len(SHARE_CODES) + len(EXTRA_CODES)))
            continue
        by_code = score(records, spirals)
        tot = client_totals(by_code)
        print(f'    {len(records)} records scored · FAIR total {tot["fair"]:.1%}', flush=True)
        clients_out.append({
            'clientId': t['id'], 'name': t['title'],
            'recordsScored': len(records), 'matchingTotal': matching,
            'totals': {'fairTotal': rnd(tot['fair']), 'projectsTotal': rnd(tot['projects']),
                       'shareTotal': rnd(tot['share']),
                       'text': rnd(tot.get('FAIR_Text')), 'identifiers': rnd(tot.get('FAIR_Identifiers')),
                       'connections': rnd(tot.get('FAIR_Connections')), 'contacts': rnd(tot.get('FAIR_Contacts'))},
            'useCases': {code: {
                'average': rnd(e['res']['average']),
                'concepts': [{'concept': it['concept'], 'matched': it['matched'],
                              'completeness': None if it['errored'] else rnd(it['comp'])}
                             for it in e['res']['items']]
            } for code, e in by_code.items()},
        })
        rows.append([ror_url, name, t['id'], t['title'], len(records), matching if matching is not None else '',
                     rnd(tot['fair'])]
                    + [rnd(tot.get(c)) for c in TOTAL_CODES]
                    + [rnd(tot['projects'])] + [rnd(tot.get(c)) for c in PROJECT_CODES]
                    + [rnd(tot['share'])] + [rnd(tot.get(c)) for c in SHARE_CODES]
                    + [rnd(tot.get(c)) for c in EXTRA_CODES])

    report = {
        'organization': {'ror': ror_url, 'name': name},
        'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'selection': {'resourceTypeId': args.resource_type or '', 'query': args.query or '',
                      'maxPerClient': args.max, 'random': args.random, 'totalRorRecords': total},
        'note': ("Each client scores a sample of the organization's ROR-identified records in that "
                 'DataCite client, as those records are at the generated time. The population is '
                 'records that already carry the ROR — the well-identified subset of the '
                 "organization's output."),
        'clients': clients_out,
    }
    return report, rows


SUMMARY_HEADERS = (['ROR', 'Organization', 'Client', 'Client_Name', 'Records_Scored', 'Matching',
                    'FAIR_Total', 'Text', 'Identifiers', 'Connections', 'Contacts',
                    'Projects_Total'] + PROJECT_CODES + ['SHARE_Total'] + SHARE_CODES + EXTRA_CODES)


def main():
    ap = argparse.ArgumentParser(description="Score organizations' DataCite records, client by client.")
    ap.add_argument('--ror', action='append', default=[],
                    help='organization ROR (repeatable; bare id, ror: prefix, or full URL)')
    ap.add_argument('--file', default='', help='text file of RORs, one per line (# comments allowed)')
    ap.add_argument('--top', type=int, default=5, help='most common clients to score per organization (1–10, default 5)')
    ap.add_argument('--max', type=int, default=100, help='records sampled per client (default 100)')
    ap.add_argument('--sequential', dest='random', action='store_false',
                    help='most-recent records instead of a random sample')
    ap.add_argument('--no-all', action='store_true', help="skip the All-of-DataCite reference column")
    ap.add_argument('--resource-type', default='', help='DataCite resource-type-id filter (e.g. dataset)')
    ap.add_argument('--query', default='', help='extra DataCite query, ANDed with the ROR clause')
    ap.add_argument('--spirals', default=str(Path(__file__).with_name('FAIR_spirals.json')),
                    help='use-case catalog (default: the FAIR_spirals.json next to this script)')
    ap.add_argument('--out', default='organizationReports', help='output directory (default organizationReports/)')
    args = ap.parse_args()
    args.top = max(1, min(10, args.top))

    rors = []
    try:
        for v in args.ror:
            rors.append(parse_ror(v))
        if args.file:
            for line in Path(args.file).read_text(encoding='utf-8').splitlines():
                line = line.split('#')[0].strip()
                if line:
                    rors.append(parse_ror(line.split()[0]))
    except ValueError as e:
        ap.error(str(e))
    rors = list(dict.fromkeys(rors))   # dedupe, keep order
    if not rors:
        ap.error('nothing to score — give --ror (repeatable) or --file')

    if subprocess.run(['jq', '--version'], capture_output=True).returncode != 0:
        sys.exit('jq is required but not on PATH (https://jqlang.org/download/)')

    spirals = json.loads(Path(args.spirals).read_text(encoding='utf-8'))
    out_dir = Path(args.out)
    stamp = datetime.now().strftime('%Y-%m-%dT%H')   # to the hour, matches the web tools

    all_rows, written, failed = [], 0, []
    for ror_id in rors:
        try:
            report, rows = score_org(ror_id, spirals, args)
        except Exception as e:
            failed.append(ror_id)
            print(f'  ror:{ror_id}: FAILED — {e}', flush=True)
            continue
        if report is None:
            continue
        org_dir = out_dir / f'ror_{ror_id}'
        org_dir.mkdir(parents=True, exist_ok=True)
        dest = org_dir / f'ror_{ror_id}_orgCompletenessReport__{stamp}.json'
        dest.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(f'  wrote {dest}', flush=True)
        all_rows += rows
        written += 1

    if all_rows:
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = out_dir / f'organizationSummary__{stamp}.csv'
        with open(summary, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(SUMMARY_HEADERS)
            w.writerows(all_rows)
        print(f'Summary: {summary} ({len(all_rows)} rows)', flush=True)

    print(f'Done — {written} organization{"" if written == 1 else "s"} scored'
          + (f', {len(failed)} failed: {", ".join(failed)}' if failed else ''), flush=True)
    sys.exit(1 if failed and not written else 0)


if __name__ == '__main__':
    main()
