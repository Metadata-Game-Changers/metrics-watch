#!/usr/bin/env python3
"""Compare Crossref Participation Reports with measured connectivity — in bulk.

For each Crossref member this samples works and puts three parallel measurements
side by side in ONE CSV, for each requested era:

  PReP_<check>        Crossref's own record-level coverage (share of records with
                      at least one <check>), from coverage-type on /members/<id> —
                      exhaustive, computed by Crossref.
  Record_<check>      the same record-level counting computed from our sample —
                      the apples-to-apples validation of PReP.
  Occurrence_<check>  the connectivity-bar counting: identified occurrences ÷ all
                      occurrences (authors with ORCIDs ÷ author slots, identified
                      affiliations ÷ affiliation slots, …).

Checks: orcids, affiliations, affiliation_ror_ids, funders (Registry-identified),
funder_ror_ids. One row per member × era; default eras are `all` and `current`,
default content type journal-article.

Eras use Crossref's Participation Report definition: CURRENT = records published
or issued in the current calendar year or up to two years previously (in 2026:
2024, 2025, 2026); BACKFILE = anything published earlier.

Requires python3 (standard library only) — no jq; sampling uses the API's native
random `sample=` draws, deduplicated by DOI.

Usage:
  python3 comparePrepConnectivity.py --member 4374 --member 340
  python3 comparePrepConnectivity.py --file members.txt --max 200
  python3 comparePrepConnectivity.py --member 4374 --era all --era current --era backfile

Output: comparePrepConnectivity__YYYY-MM-DDThh.csv (override with --csv).
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
USER_AGENT = f'metrics-watch comparePrepConnectivity (https://github.com/Metadata-Game-Changers/metrics-watch; mailto:{MAILTO})'
SELECT = 'DOI,author,funder'
CHECKS = ['orcids', 'affiliations', 'affiliation_ror_ids', 'funders', 'funder_ror_ids']
PREP_KEY = {'orcids': 'orcids', 'affiliations': 'affiliations',
            'affiliation_ror_ids': 'affiliation-ror-ids', 'funders': 'funders',
            'funder_ror_ids': 'funder-ror-ids'}

rnd = lambda x: '' if x is None else int(x * 10000 + 0.5) / 10000


def api_get(path_and_query, retries=3):
    url = f'{API_BASE}{path_and_query}'
    url += ('&' if '?' in url else '?') + f'mailto={urllib.parse.quote(MAILTO)}'
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            if attempt == retries - 1:
                raise RuntimeError(f'Crossref request failed after {retries} tries: {url} ({e})')
            time.sleep(3 * (attempt + 1))


def era_filter(era):
    """Participation Report eras: current = published in the current calendar year
    or up to two years previously; backfile = earlier; all = no date filter."""
    y = datetime.now().year
    if era == 'current':
        return f'from-pub-date:{y - 2}-01-01'
    if era == 'backfile':
        return f'until-pub-date:{y - 3}-12-31'
    return ''


def sample_works(member_id, type_id, era, cap):
    """Random sample via repeated sample= draws, deduplicated by DOI (the same
    pattern the web tools use). Returns (works, matching_total)."""
    filters = ','.join(f for f in [f'member:{member_id}', f'type:{type_id}', era_filter(era)] if f)
    common = f'/works?filter={urllib.parse.quote(filters)}&select={urllib.parse.quote(SELECT)}'
    peek = api_get(f'{common}&rows=0')
    total = (peek.get('message') or {}).get('total-results')
    if not total:
        return [], total or 0
    works, seen, requests = [], set(), 0
    if total <= cap:   # everything fits — fetch deterministically with cursor paging
        cursor = '*'
        while len(works) < total and requests < 10:
            requests += 1
            d = (api_get(f'{common}&rows=1000&cursor={urllib.parse.quote(cursor)}').get('message') or {})
            batch = d.get('items') or []
            for w in batch:
                if w.get('DOI') and w['DOI'] not in seen:
                    seen.add(w['DOI']); works.append(w)
            cursor = d.get('next-cursor') or ''
            if not batch or not cursor:
                break
        return works, total
    while len(works) < cap and requests < 30:
        requests += 1
        batch = (api_get(f'{common}&sample={min(100, cap)}').get('message') or {}).get('items') or []
        added = 0
        for w in batch:
            if w.get('DOI') and w['DOI'] not in seen:
                seen.add(w['DOI']); works.append(w); added += 1
        if added == 0:
            break
    return works[:cap], total


def is_ror(idobj):
    return str(idobj.get('id-type', '')).upper() == 'ROR'


def measure(works):
    """Record-level (>=1 per work) and occurrence-level shares for the five checks."""
    n = len(works)
    rec = dict.fromkeys(CHECKS, 0)
    auth_occ = orcid_occ = aff_auth_occ = 0        # author slots
    aff_occ = aff_ror_occ = 0                      # affiliation slots
    fun_occ = fun_id_occ = fun_ror_occ = 0         # funder slots
    for w in works:
        authors = [a for a in (w.get('author') or []) if isinstance(a, dict)]
        affs = [f for a in authors for f in (a.get('affiliation') or []) if isinstance(f, dict) and f.get('name')]
        funders = [f for f in (w.get('funder') or []) if isinstance(f, dict) and f.get('name')]
        if any(a.get('ORCID') for a in authors):
            rec['orcids'] += 1
        if affs:
            rec['affiliations'] += 1
        if any(any(is_ror(i) for i in (f.get('id') or [])) for f in affs):
            rec['affiliation_ror_ids'] += 1
        if any(f.get('DOI') or f.get('id') for f in funders):
            rec['funders'] += 1
        if any(any(is_ror(i) for i in (f.get('id') or [])) for f in funders):
            rec['funder_ror_ids'] += 1
        auth_occ += len(authors)
        orcid_occ += sum(1 for a in authors if a.get('ORCID'))
        aff_auth_occ += sum(1 for a in authors if any(isinstance(f, dict) and f.get('name') for f in (a.get('affiliation') or [])))
        aff_occ += len(affs)
        aff_ror_occ += sum(1 for f in affs if any(is_ror(i) for i in (f.get('id') or [])))
        fun_occ += len(funders)
        fun_id_occ += sum(1 for f in funders if f.get('DOI') or f.get('id'))
        fun_ror_occ += sum(1 for f in funders if any(is_ror(i) for i in (f.get('id') or [])))
    share = lambda a, b: a / b if b else None
    return {
        'record': {k: share(rec[k], n) for k in CHECKS},
        'occurrence': {
            'orcids': share(orcid_occ, auth_occ),
            'affiliations': share(aff_auth_occ, auth_occ),
            'affiliation_ror_ids': share(aff_ror_occ, aff_occ),
            'funders': share(fun_id_occ, fun_occ),
            'funder_ror_ids': share(fun_ror_occ, fun_occ),
        },
        'denominators': {'authors': auth_occ, 'affiliations': aff_occ, 'funders': fun_occ},
    }


def main():
    ap = argparse.ArgumentParser(description='Compare Crossref Participation Reports with sampled connectivity.')
    ap.add_argument('--member', action='append', default=[], help='Crossref member id (repeatable)')
    ap.add_argument('--file', default='', help='text file of member ids, one per line (# comments allowed)')
    ap.add_argument('--era', action='append', default=[], choices=['all', 'current', 'backfile'],
                    help='era (repeatable; default: all and current)')
    ap.add_argument('--type', default='journal-article', help='Crossref work type (default journal-article)')
    ap.add_argument('--max', type=int, default=100, help='works sampled per member per era (default 100)')
    ap.add_argument('--csv', default='', help='output CSV (default comparePrepConnectivity__<stamp>.csv)')
    args = ap.parse_args()

    ids = list(args.member)
    if args.file:
        for line in Path(args.file).read_text(encoding='utf-8').splitlines():
            line = line.split('#')[0].strip()
            if line:
                ids.append(line.split()[0])
    if not ids:
        ap.error('nothing to compare — give --member (repeatable) or --file')
    bad = [i for i in ids if not i.isdigit()]
    if bad:
        ap.error(f'member ids are numeric; not ids: {", ".join(bad)}')
    eras = args.era or ['all', 'current']

    headers = (['Member_ID', 'Member_Name', 'Era', 'Content_Type',
                'PReP_Records', 'PReP_Last_Checked', 'Matching', 'Sample_N',
                'Author_Occurrences', 'Affiliation_Occurrences', 'Funder_Occurrences']
               + [f'{fam}_{c}' for c in CHECKS for fam in ('PReP', 'Record', 'Occurrence')])
    rows = []
    for mid in dict.fromkeys(ids):
        msg = (api_get(f'/members/{mid}').get('message') or {})
        name = msg.get('primary-name') or f'member {mid}'
        checked = msg.get('last-status-check-time')
        checked = datetime.fromtimestamp(checked / 1000).strftime('%Y-%m-%d') if checked else ''
        print(f'{mid}: {name}', flush=True)
        for era in eras:
            prep = ((msg.get('coverage-type') or {}).get(era) or {}).get(args.type) or {}
            prep_n = ((msg.get('counts-type') or {}).get(era) or {}).get(args.type)
            works, matching = sample_works(mid, args.type, era, args.max)
            if not works:
                print(f'  {era}: no matching works — skipped', flush=True)
                continue
            m = measure(works)
            print(f"  {era}: {len(works)} sampled of {matching:,} · "
                  f"ORCIDs PReP {prep.get('orcids', 0):.0%} / record {m['record']['orcids']:.0%} / occ {m['occurrence']['orcids']:.0%}", flush=True)
            row = [mid, name, era, args.type,
                   prep_n if prep_n is not None else '', checked, matching, len(works),
                   m['denominators']['authors'], m['denominators']['affiliations'], m['denominators']['funders']]
            for c in CHECKS:
                row += [rnd(prep.get(PREP_KEY[c])), rnd(m['record'][c]), rnd(m['occurrence'][c])]
            rows.append(row)

    if not rows:
        sys.exit('no rows produced')
    stamp = datetime.now().strftime('%Y-%m-%dT%H')
    out = Path(args.csv) if args.csv else Path(f'comparePrepConnectivity__{stamp}.csv')
    with open(out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)
    print(f'Wrote {out} ({len(rows)} rows)', flush=True)


if __name__ == '__main__':
    main()
