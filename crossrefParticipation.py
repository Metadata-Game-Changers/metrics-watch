#!/usr/bin/env python3
"""Retrieve Crossref Participation Reports for a list of members — in bulk.

Crossref precomputes each member's metadata coverage (the numbers behind
https://www.crossref.org/members/prep/<id>) and serves them on
/members/<id> as `coverage-type`: era (current = the last two calendar
years / backfile / all) x content type x fourteen checks. This tool
harvests those reports for many members at once and writes one tidy,
analysis-ready CSV — one row per member x era x content type — so
members can be compared side by side.

Requires python3 (standard library only). No jq — this reads Crossref's
own numbers; nothing is sampled or scored locally.

Usage:
  python3 crossrefParticipation.py --member 4374 --member 340
  python3 crossrefParticipation.py --file members.txt
  python3 crossrefParticipation.py --search "university press" --rows 40
  python3 crossrefParticipation.py --member 4374 --era current --type journal-article

members.txt: one member id per line; `#` comments and text after the
first whitespace are ignored.

Output: crossrefParticipation__YYYY-MM-DDThh.csv (override with --csv).
Columns: Member_ID, Member_Name, Location, Era, Content_Type, Records,
Total_DOIs, Last_Checked, then the fourteen coverage checks (0-1, 4 dp).
"""

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = 'https://api.crossref.org'
MAILTO = 'ted@metadatagamechangers.com'   # Crossref polite pool
USER_AGENT = f'metrics-watch crossrefParticipation (https://github.com/Metadata-Game-Changers/metrics-watch; mailto:{MAILTO})'

# The fourteen Participation Report checks, in report order.
CHECKS = ['abstracts', 'orcids', 'references', 'funders', 'award-numbers', 'licenses',
          'affiliations', 'ror-ids', 'affiliation-ror-ids', 'funder-ror-ids',
          'update-policies', 'resource-links', 'similarity-checking', 'descriptions']
ERAS = ['current', 'backfile', 'all']

rnd = lambda x: None if x is None else int(x * 10000 + 0.5) / 10000


def api_get(path_and_query, retries=3):
    url = f'{API_BASE}{path_and_query}'
    sep = '&' if '?' in url else '?'
    url += f'{sep}mailto={urllib.parse.quote(MAILTO)}'
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            if attempt == retries - 1:
                raise RuntimeError(f'Crossref request failed after {retries} tries: {url} ({e})')
            time.sleep(3 * (attempt + 1))


def member_rows(msg, eras, type_filter):
    """The tidy rows for one member message (list rows and /members/<id> are identical)."""
    name = msg.get('primary-name') or f"member {msg.get('id')}"
    loc = msg.get('location') or ''
    total = (msg.get('counts') or {}).get('total-dois')
    checked = msg.get('last-status-check-time')
    checked = datetime.fromtimestamp(checked / 1000).strftime('%Y-%m-%d') if checked else ''
    ct = msg.get('coverage-type') or {}
    counts = msg.get('counts-type') or {}
    rows = []
    types = sorted({t for era in ct.values() for t in era},
                   key=lambda t: -((counts.get('all') or {}).get(t) or 0))
    for t in types:
        if type_filter and t != type_filter:
            continue
        for era in eras:
            c = (ct.get(era) or {}).get(t)
            if not c:
                continue
            n = (counts.get(era) or {}).get(t)
            rows.append([msg.get('id'), name, loc, era, t,
                         n if n is not None else '', total if total is not None else '', checked]
                        + [('' if c.get(k) is None else rnd(c.get(k))) for k in CHECKS])
    if not rows:
        print(f'  member {msg.get("id")} ({name}): no coverage data', flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser(description='Harvest Crossref Participation Reports for many members.')
    ap.add_argument('--member', action='append', default=[], help='Crossref member id (repeatable)')
    ap.add_argument('--file', default='', help='text file of member ids, one per line (# comments allowed)')
    ap.add_argument('--search', default='', help='retrieve every member matching this name search')
    ap.add_argument('--rows', type=int, default=20, help='max members retrieved by --search (default 20)')
    ap.add_argument('--era', choices=ERAS, default='', help='only this era (default: all three)')
    ap.add_argument('--type', default='', help='only this content type (e.g. journal-article)')
    ap.add_argument('--csv', default='', help='output CSV (default crossrefParticipation__<stamp>.csv)')
    args = ap.parse_args()

    ids = list(args.member)
    if args.file:
        for line in Path(args.file).read_text(encoding='utf-8').splitlines():
            line = line.split('#')[0].strip()
            if line:
                ids.append(line.split()[0])
    if not ids and not args.search:
        ap.error('nothing to retrieve — give --member (repeatable), --file, or --search')
    bad = [i for i in ids if not i.isdigit()]
    if bad:
        ap.error(f'member ids are numeric; not ids: {", ".join(bad)}')

    eras = [args.era] if args.era else ERAS
    all_rows = []

    for mid in dict.fromkeys(ids):
        d = api_get(f'/members/{mid}')
        msg = d.get('message') or {}
        print(f'{mid}: {msg.get("primary-name")}', flush=True)
        all_rows += member_rows(msg, eras, args.type)

    if args.search:
        d = api_get(f'/members?query={urllib.parse.quote(args.search)}&rows={max(1, min(1000, args.rows))}')
        items = (d.get('message') or {}).get('items') or []
        total = (d.get('message') or {}).get('total-results')
        print(f'search "{args.search}": {total} members match, retrieving {len(items)}', flush=True)
        for msg in items:
            print(f'{msg.get("id")}: {msg.get("primary-name")}', flush=True)
            all_rows += member_rows(msg, eras, args.type)

    if not all_rows:
        sys.exit('no coverage rows retrieved')
    stamp = datetime.now().strftime('%Y-%m-%dT%H')
    out = Path(args.csv) if args.csv else Path(f'crossrefParticipation__{stamp}.csv')
    with open(out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['Member_ID', 'Member_Name', 'Location', 'Era', 'Content_Type',
                    'Records', 'Total_DOIs', 'Last_Checked'] + [c.replace('-', '_') for c in CHECKS])
        w.writerows(all_rows)
    print(f'Wrote {out} ({len(all_rows)} rows)', flush=True)


if __name__ == '__main__':
    main()
