# metrics-watch

**Automatic metadata metrics for DataCite repositories.** Fork this repository,
name your repositories in one config file, and a scheduled GitHub Action scores
their metadata against the [Metadata Game Changers use
cases](https://metadata-game-changers.github.io/recuration-watch/useCases.html)
every month — committing the reports here and publishing a trend page, with no
server and nothing to install.

It is the automation companion to the [MGC Repository
Tools](https://metadata-game-changers.github.io/recuration-watch/): the scorer
runs the same jq queries over the same DataCite API sampling rules as the
[Metadata Completeness](https://metadata-game-changers.github.io/recuration-watch/completeness.html)
web tool, and writes the same report files — so automated runs, web-tool
downloads, and the MGC score archive all speak one format.

## Set up your own (about two minutes)

1. **Fork** this repository (button at the top right).
2. On your fork, open the **Actions** tab and click **"I understand my workflows,
   go ahead and enable them"** (GitHub disables workflows on forks until you opt in).
3. Edit [`config.json`](config.json): list your repository ids (the DataCite
   *client id*, e.g. `sjyq.oozvia` — find yours by searching your repository name
   in any of the web tools), or set `"consortium"` to a DataCite consortium id to
   score every member repository.
4. Optionally, run it now: **Actions → Score metadata → Run workflow**.
   Otherwise the schedule (first of each month, 06:00 UTC) takes it from there.
5. Optionally, publish the trend page: **Settings → Pages → Deploy from a
   branch → `main` / `docs`**. Your page appears at
   `https://<you>.github.io/metrics-watch/`.

Each run commits its results, so the repository accumulates a public, versioned
history of your metadata's improvement.

### config.json

| key | meaning |
|---|---|
| `repositories` | list of DataCite client ids to score |
| `consortium` | a DataCite consortium id — adds every member repository |
| `max` | records sampled per repository (default 500) |
| `random` | `true` for a random sample; `false` for most-recent records |
| `resourceType` | optional DataCite resource-type-id filter (e.g. `dataset`) |
| `query` | optional DataCite query filter — filtered runs form their own series |

## What a run produces

```
reports/<client-id>/<stem>_useCaseReport__YYYY-MM-DDThh.json   one snapshot per run
reports/<client-id>/<stem>_useCaseHistory.json                 every run of the series, concatenated
docs/index.html                                                trend page over all series
```

`<stem>` is the client id, plus a filter-derived label when `resourceType` or
`query` is set, so filtered series never mix with whole-repository series.
Snapshots are canonical; the history file is re-derived from them on every run.

The snapshot JSON is exactly what the Metadata Completeness web tool's
**⬇ Data (JSON)** button downloads — `{repository: {…run stats, fairTotal,
projectsTotal, shareTotal}, useCases: [{code, title, average, items: [{concept,
completeness}]}]}` — and the history file matches the MGC score-archive format,
so existing MGC tooling reads both.

## Running locally

Requires python3 (standard library only) and [jq](https://jqlang.org/download/)
(`brew install jq` on macOS; preinstalled on GitHub's ubuntu runners).

```
python3 scoreRepository.py --client sjyq.oozvia
python3 scoreRepository.py --consortium oaem --max 200
python3 scoreRepository.py --config config.json
python3 makeTrendPage.py
```

## What does it look like in practice?

[`example/`](example/) holds a real history file from the IRIS seismology
repository, captured during an active 2025 re-curation project — FAIR total
climbing from 11% to 37% run by run.
[Open it in the Metrics Viewer ↗](https://metadata-game-changers.github.io/recuration-watch/metricsViewer.html?src=https://raw.githubusercontent.com/Metadata-Game-Changers/metrics-watch/main/example/iris.iris_useCaseHistory.json)

## Updating your fork

Improvements to the scorer, the trend page, and the use-case catalog land in
this upstream repository — they do **not** reach your fork automatically. Your
fork's front page shows a **Sync fork** button whenever upstream has news: one
click merges the updates. Your `config.json` and accumulated `reports/` are
yours alone (upstream never changes them after setup), so syncing is normally
conflict-free.

## Good to know

- **Scheduled workflows pause after ~60 days without repository activity.**
  Each run's commit counts as activity, so a healthy setup keeps itself alive —
  but if runs start failing silently, GitHub will eventually email you to
  re-enable the schedule. Glance at the Actions tab now and then.
- **Scores are current-state.** Every run samples records *as they are that
  day* — so a rising line means your re-curation is working, whichever year the
  records were registered.
- **Sampling noise.** With `max` 500 against a large repository, totals move a
  point or two run-to-run from sampling alone. Use `"random": false` for small
  repositories (≤ max) to score every record deterministically.
- **The use-case catalog** ([`FAIR_spirals.json`](FAIR_spirals.json)) is copied
  from the [recuration-watch](https://github.com/Metadata-Game-Changers/recuration-watch)
  suite — update it from there when the use cases evolve.

## License

[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) ·
[Metadata Game Changers](https://metadatagamechangers.com) — Better
Documentation | Better Data | Better Science.
