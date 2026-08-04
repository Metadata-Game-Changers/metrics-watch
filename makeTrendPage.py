#!/usr/bin/env python3
"""Build docs/index.html — a static trend page over the accumulated score history.

Reads every reports/<client-id>/*_useCaseHistory.json (the derived history files
scoreRepository.py maintains — same format as the MGC score archive) and, for
each series, draws the FAIR / Projects / SHARE totals over time as inline SVG
(no JavaScript) with a table of runs. Regenerated on every scoring run; publish
it by enabling GitHub Pages on the /docs folder.
"""

import json
import os
import re
import subprocess
from html import escape
from pathlib import Path

REPORTS = Path('reports')
OUT = Path('docs/index.html')

VIEWER = 'https://metadata-game-changers.github.io/recuration-watch/metricsViewer.html'
SET_VIEWER = 'https://metadata-game-changers.github.io/recuration-watch/setViewer.html'


def repo_slug_branch():
    """(owner/repo, branch) for building raw file URLs — from the Actions environment
    when scheduled, from git otherwise. (None, None) if neither is available."""
    slug = os.environ.get('GITHUB_REPOSITORY')
    branch = os.environ.get('GITHUB_REF_NAME') or 'main'
    if slug:
        return slug, branch
    try:
        url = subprocess.run(['git', 'remote', 'get-url', 'origin'],
                             capture_output=True, text=True).stdout.strip()
        m = re.search(r'github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?$', url)
        if m:
            b = subprocess.run(['git', 'branch', '--show-current'],
                               capture_output=True, text=True).stdout.strip()
            return m.group(1), b or 'main'
    except Exception:
        pass
    return None, None


SERIES = [('fairTotal', 'FAIR', '#673289'),
          ('projectsTotal', 'Projects', '#EF9B20'),
          ('shareTotal', 'SHARE', '#2F6FB0')]


def load_histories():
    """[(client_dir, history-file-path, history-dict), …] for every series history file."""
    out = []
    if not REPORTS.is_dir():
        return out
    for d in sorted(p for p in REPORTS.iterdir() if p.is_dir()):
        for f in sorted(d.glob('*_useCaseHistory.json')):
            try:
                h = json.loads(f.read_text(encoding='utf-8'))
            except Exception:
                continue
            if h.get('snapshots'):
                out.append((d.name, f, h))
    return out


def chart_svg(snaps):
    """Inline SVG line chart of the three group totals over the snapshots."""
    W, H, PADL, PADR, PADT, PADB = 640, 200, 40, 12, 14, 34
    n = len(snaps)
    x = lambda i: PADL + (i * (W - PADL - PADR) / (n - 1) if n > 1 else (W - PADL - PADR) / 2)
    y = lambda v: PADT + (1 - v) * (H - PADT - PADB)
    rep = lambda s: s.get('repository') or {}
    s = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;max-width:{W}px;background:#fff;border:1px solid #e6e3ec;border-radius:8px">']
    for pct in (0, 0.25, 0.5, 0.75, 1):
        s.append(f'<line x1="{PADL}" y1="{y(pct):.1f}" x2="{W - PADR}" y2="{y(pct):.1f}" stroke="#eee"/>' +
                 f'<text x="{PADL - 6}" y="{y(pct) + 3:.1f}" font-size="9" fill="#6b7280" text-anchor="end">{int(pct * 100)}%</text>')
    step = max(1, (n + 7) // 8)
    for i, snap in enumerate(snaps):
        if i % step and i != n - 1:
            continue
        s.append(f'<text x="{x(i):.1f}" y="{H - 18}" font-size="9" fill="#6b7280" text-anchor="middle">{str(snap.get("dateTime", ""))[:10]}</text>')
    for key, label, color in SERIES:
        pts = [(i, rep(snap).get(key)) for i, snap in enumerate(snaps)]
        pts = [(i, v) for i, v in pts if isinstance(v, (int, float))]
        if not pts:
            continue
        s.append('<polyline points="' + ' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in pts)
                 + f'" fill="none" stroke="{color}" stroke-width="2"/>')
        for i, v in pts:
            s.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.6" fill="{color}"/>')
    lx = PADL
    for key, label, color in SERIES:
        s.append(f'<rect x="{lx}" y="{H - 10}" width="14" height="3" fill="{color}"/>' +
                 f'<text x="{lx + 18}" y="{H - 6}" font-size="9" fill="#374151">{label}</text>')
        lx += 22 + 7 * len(label)
    s.append('</svg>')
    return ''.join(s)


def main():
    histories = load_histories()
    pct = lambda v: f'{v * 100:.0f}%' if isinstance(v, (int, float)) else '—'
    parts = ['''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Metadata Metrics — automated use-case scores</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Montserrat:wght@400;500&display=swap" rel="stylesheet"/>
<style>
  body{font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1f2330;background:#fbfafe;margin:0;line-height:1.5}
  .topbar{border-bottom:2px solid #1f2330;background:#fff;padding:.55rem 1.25rem .35rem}
  .topbar-inner{max-width:760px;margin:0 auto;display:flex;align-items:flex-end;gap:1rem}
  .brand-logo{height:52px;width:auto;display:block}
  .brand-name{font-family:Montserrat,sans-serif;font-size:1.55rem;letter-spacing:.02em;color:#673289;text-transform:uppercase;line-height:1;padding-bottom:.3rem}
  .topbar-inner a.suite{margin-left:auto;font-size:.72rem;color:#6b7280;text-decoration:none;padding-bottom:.45rem;white-space:nowrap}
  .topbar-inner a.suite:hover{color:#673289}
  .hero{background:#f0eaf5;border-bottom:2px solid #9167b0;padding:.9rem 1.25rem}
  .hero p{max-width:760px;margin:0 auto;font-size:.8rem;color:#1f2330}
  .hero a{color:#673289;font-weight:600;text-decoration:none}
  .hero a:hover{text-decoration:underline}
  .wrap{max-width:760px;margin:0 auto;padding:1.4rem 1.25rem 2.5rem}
  .sub{font-size:.8rem;color:#6b7280;margin:0 0 1.6rem}
  .sub a,.foot a{color:#9167b0}
  h2{font-size:1rem;color:#673289;margin:1.8rem 0 .5rem}
  h2 span{font-family:ui-monospace,monospace;font-size:.72rem;color:#6b7280;font-weight:400;margin-left:.5rem}
  table{border-collapse:collapse;font-size:.76rem;margin-top:.6rem;width:100%}
  th,td{border:1px solid #e6e3ec;padding:.3rem .55rem;text-align:right}
  th:first-child,td:first-child{text-align:left}
  th{background:#f0eaf5;color:#673289}
  .foot{border-top:1px solid #e6e3ec;margin-top:2.5rem;padding:1rem 1.25rem;background:#fff;font-size:.72rem;color:#6b7280}
  .foot-inner{max-width:760px;margin:0 auto;display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}
  .foot-inner img{height:20px;width:auto;display:block}
</style></head><body>
<div class="topbar"><div class="topbar-inner">
  <a href="https://metadatagamechangers.com" target="_blank" rel="noopener"><img class="brand-logo" src="https://images.squarespace-cdn.com/content/v1/52ffa419e4b05b374032e6d9/1577498408185-9LMHCVUJMNL2UBCIUOB9/Metadata+Game+Changers+Logo-Light.png?format=300w" alt="Metadata Game Changers" onerror="this.style.display=&#39;none&#39;"/></a>
  <div class="brand-name">Metadata Metrics</div>
  <a class="suite" href="https://metadata-game-changers.github.io/recuration-watch/" target="_blank" rel="noopener">MGC Repository Tools ↗</a>
</div></div>
<div class="hero"><p>Automated use-case scores for the repositories in this metrics-watch fork, measured with the
<a href="https://metadata-game-changers.github.io/recuration-watch/useCases.html" target="_blank" rel="noopener">MGC use cases</a>.
Every run scores the records <b>as they are that day</b> — a rising line is re-curation you can see.</p></div>
<div class="wrap">''']
    if not histories:
        parts.append('<p class="sub">No reports yet — the first scheduled run will populate this page.</p>')
    slug, branch = repo_slug_branch()
    # sets line: every set links into the suite's Set Viewer (whole-set radar grid, one run)
    manifest = Path('docs/sets.json')
    if slug and manifest.exists():
        try:
            m = json.loads(manifest.read_text(encoding='utf-8'))
        except Exception:
            m = None
        with_series = [st for st in (m.get('sets', []) if m else []) if st.get('series')]
        if with_series:
            raw = f'https://raw.githubusercontent.com/{slug}/{branch}/docs/sets.json'
            links = ' · '.join(
                f'<a href="{SET_VIEWER}?src={escape(raw)}&amp;set={escape(st["name"])}" target="_blank" '
                f'rel="noopener">{escape(st["name"])} ({len(st["series"])})</a>' for st in with_series)
            parts.append(f'<p class="sub"><b>Sets</b> — compare all members side by side in the Set Viewer: {links}</p>')
    for client_dir, hpath, h in histories:
        snaps = h['snapshots']
        repo = h.get('repository') or {}
        last = snaps[-1].get('repository') or {}
        name = last.get('name') or repo.get('id') or client_dir
        qlabel = repo.get('queryLabel') or ''
        viewer = ''
        if slug:
            raw = f'https://raw.githubusercontent.com/{slug}/{branch}/{hpath.as_posix()}'
            viewer = (f' <a style="font-size:.7rem;font-weight:600" href="{VIEWER}?src={escape(raw)}" '
                      f'target="_blank" rel="noopener">Open in Metrics Viewer ↗</a>')
        parts.append(f'<h2>{escape(name)}<span>{escape(repo.get("id") or client_dir)}'
                     + (f' · {escape(qlabel)}' if qlabel else '') + f'</span>{viewer}</h2>')
        parts.append(chart_svg(snaps))
        parts.append('<table><tr><th>Run</th><th>Records</th><th>Sampling</th><th>FAIR</th><th>Projects</th><th>SHARE</th></tr>')
        for snap in reversed(snaps):
            r = snap.get('repository') or {}
            parts.append(f'<tr><td>{escape(str(snap.get("dateTime", "—")))}</td><td>{r.get("records", "—")}</td>'
                         f'<td style="text-align:left">{escape(str(r.get("sampling", "—")))}</td>'
                         f'<td>{pct(r.get("fairTotal"))}</td><td>{pct(r.get("projectsTotal"))}</td>'
                         f'<td>{pct(r.get("shareTotal"))}</td></tr>')
        parts.append('</table>')
    parts.append('</div>')
    parts.append('<div class="foot"><div class="foot-inner">'
                 '<a href="https://metadatagamechangers.com" target="_blank" rel="noopener">'
                 '<img src="https://images.squarespace-cdn.com/content/v1/52ffa419e4b05b374032e6d9/1577498408185-9LMHCVUJMNL2UBCIUOB9/Metadata+Game+Changers+Logo-Light.png?format=300w" alt="Metadata Game Changers" onerror="this.style.display=&#39;none&#39;"/></a>'
                 '<span>Report JSONs and history files live in this repository under <code>reports/</code> — the formats of the '
                 '<a href="https://metadata-game-changers.github.io/recuration-watch/completeness.html" target="_blank" rel="noopener">Metadata Completeness</a> tool and the MGC score archive. '
                 'Powered by <a href="https://github.com/Metadata-Game-Changers/metrics-watch" target="_blank" rel="noopener">metrics-watch</a> from '
                 '<a href="https://metadatagamechangers.com" target="_blank" rel="noopener">Metadata Game Changers</a> — '
                 'Better Documentation | Better Data | Better Science · '
                 '<a href="https://creativecommons.org/licenses/by-nc/4.0/" target="_blank" rel="noopener">CC BY-NC 4.0</a></span>'
                 '</div></div></body></html>')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text('\n'.join(parts) + '\n', encoding='utf-8')
    print(f'{OUT}: {len(histories)} series')


if __name__ == '__main__':
    main()
