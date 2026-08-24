#!/usr/bin/env python3
"""Audit: how much of each concept's completeness comes from empty-string values?

The catalog's queries count a record when the element is present and non-null —
an empty string ("" or whitespace-only) passes, so a repository that emits
"resourceType": "" in every record scores 100% on Resource Type while carrying
no information. This audit measures that inflation, per concept, by running the
FULL catalog queries (values projections included) over a sample and re-counting
records under strict semantics: at least one value that is not an empty/blank
string.

For each concept it reports the current completeness, the strict completeness,
and the drop; for each use case and the FAIR/Projects/SHARE totals it reports
both averages — i.e. exactly what a catalog-wide "empty is absent" methodology
change would do to this repository's scores.

Usage:
  python3 auditEmptyValues.py --client ethz.marvel --max 300
  python3 auditEmptyValues.py --file marvel.json --label ethz.marvel
  python3 auditEmptyValues.py --client a.b --client c.d --csv audit.csv

--file reads an already-downloaded DataCite response ({"data": [records]}) —
e.g. the web tools' "Download metadata (JSON)" file — instead of fetching.
Requires python3 (stdlib) and jq, like the scorer. Read-only unless --csv.
"""

import argparse
import csv
import json
import subprocess
from pathlib import Path

from scoreRepository import fetch_records, GROUPS


def is_blank(v):
    return isinstance(v, str) and v.strip() == ''


def audit_records(name, records, spirals):
    """[{code, concept, n, cur, strict, empty_vals, total_vals, errored}] for one sample."""
    n = len(records)
    input_str = json.dumps({'data': records})
    print(f'  {name}: auditing {n} records across the full catalog…', flush=True)
    rows = []
    for uc in spirals:
        for it in uc['items']:
            p = subprocess.run(['jq', '-c', f"[ {it['jq_query']} ]"],
                               input=input_str, capture_output=True, text=True)
            if p.returncode != 0:
                rows.append(dict(code=uc['code'], concept=it['concept'], n=n,
                                 cur=0, strict=0, empty_vals=0, total_vals=0, errored=True))
                continue
            outs = json.loads(p.stdout)
            cur = len(outs)                      # current semantics: the select admitted the record
            strict = empty_vals = total_vals = 0
            for o in outs:
                vals = o.get('values')
                vals = vals if isinstance(vals, list) else [vals]
                vals = [v for v in vals if v is not None]
                total_vals += len(vals)
                empty_vals += sum(1 for v in vals if is_blank(v))
                if any(not is_blank(v) for v in vals):
                    strict += 1                  # strict semantics: some value is real
            rows.append(dict(code=uc['code'], concept=it['concept'], n=n,
                             cur=cur, strict=strict, empty_vals=empty_vals,
                             total_vals=total_vals, errored=False))
    return rows


def averages(rows, use):
    """Per-use-case averages under one semantics ('cur' or 'strict')."""
    by_code = {}
    for r in rows:
        by_code.setdefault(r['code'], []).append(min(r[use] / r['n'], 1.0) if r['n'] else 0.0)
    return {code: sum(v) / len(v) for code, v in by_code.items()}


def weighted(avg, rows, codes):
    counts = {}
    for r in rows:
        counts[r['code']] = counts.get(r['code'], 0) + 1
    score = total = 0
    for c in codes:
        if c in avg:
            score += avg[c] * counts[c]
            total += counts[c]
    return score / total if total else 0.0


def report(name, rows):
    inflated = [r for r in rows if r['cur'] > r['strict']]
    cur_avg, strict_avg = averages(rows, 'cur'), averages(rows, 'strict')
    print(f"\n=== {name} ({rows[0]['n']} records) — "
          f'{len(inflated)} of {len(rows)} concepts inflated by empty strings')
    for r in sorted(inflated, key=lambda r: r['strict'] / r['n'] - r['cur'] / r['n']):
        print(f"  {r['code']:26s} {r['concept']:34s} {r['cur']/r['n']:6.0%} -> {r['strict']/r['n']:6.0%}"
              f"   ({r['empty_vals']} empty of {r['total_vals']} values)")
    for gname, codes in GROUPS.items():
        c, s = weighted(cur_avg, rows, codes), weighted(strict_avg, rows, codes)
        marker = '  <- changes' if abs(c - s) >= 0.005 else ''
        print(f'  {gname + " total":26s} {c:6.1%} -> {s:6.1%}{marker}')


def main():
    ap = argparse.ArgumentParser(description='Audit empty-string inflation of completeness scores.')
    ap.add_argument('--client', action='append', default=[], help='repository client id (repeatable; fetches a sample)')
    ap.add_argument('--file', action='append', default=[],
                    help='local DataCite JSON ({"data": [...]}) to audit instead of fetching (repeatable)')
    ap.add_argument('--label', action='append', default=[],
                    help='display name for the matching --file (repeatable, in order)')
    ap.add_argument('--max', type=int, default=300, help='records sampled per fetched repository (default 300)')
    ap.add_argument('--resource-type', default='')
    ap.add_argument('--query', default='')
    ap.add_argument('--spirals', default='FAIR_spirals.json')
    ap.add_argument('--csv', default='', help='also write every concept row (all samples) to this CSV')
    args = ap.parse_args()
    if not args.client and not args.file:
        ap.error('give at least one --client or --file')

    spirals = json.loads(Path(args.spirals).read_text(encoding='utf-8'))
    all_rows = []

    for i, f in enumerate(args.file):
        name = args.label[i] if i < len(args.label) else Path(f).name
        records = json.loads(Path(f).read_text(encoding='utf-8')).get('data', [])
        if not records:
            print(f'  {name}: no records in {f} — skipped', flush=True)
            continue
        rows = audit_records(name, records, spirals)
        for r in rows:
            r['client'] = name
        all_rows += rows
        report(name, rows)

    for client in args.client:
        print(f'  {client}: fetching…', flush=True)
        records, matching, _ = fetch_records(client, args.max, True, args.resource_type, args.query)
        if not records:
            print(f'  {client}: no records — skipped', flush=True)
            continue
        rows = audit_records(client, records, spirals)
        for r in rows:
            r['client'] = client
        all_rows += rows
        report(client, rows)

    if args.csv and all_rows:
        with open(args.csv, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['Client', 'Use_Case', 'Concept', 'Records', 'Current_Matched', 'Strict_Matched',
                        'Current_Completeness', 'Strict_Completeness', 'Empty_Values', 'Total_Values'])
            for r in all_rows:
                w.writerow([r['client'], r['code'], r['concept'], r['n'], r['cur'], r['strict'],
                            round(r['cur'] / r['n'], 4), round(r['strict'] / r['n'], 4),
                            r['empty_vals'], r['total_vals']])
        print(f'\nWrote {len(all_rows)} concept rows to {args.csv}')


if __name__ == '__main__':
    main()
