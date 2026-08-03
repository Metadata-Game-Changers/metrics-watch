# Example: a history file during an active re-curation project

[`iris.iris_useCaseHistory.json`](iris.iris_useCaseHistory.json) is a real
`useCaseHistory.json` — the file a metrics-watch fork accumulates run by run —
from the IRIS seismology data repository (iris.iris, now part of EarthScope),
captured across an active metadata re-curation project in 2025.

**[Open it in the Metrics Viewer ↗](https://metadata-game-changers.github.io/recuration-watch/metricsViewer.html?src=https://raw.githubusercontent.com/Metadata-Game-Changers/metrics-watch/main/example/iris.iris_useCaseHistory.json)**

Thirteen scoring runs span March to December 2025. Because every run scores the
repository's records *as they are on that day*, the effect of re-curation is
visible directly: the FAIR total climbs from **11% in March to 37% by
August** and holds there — with the radar **Grid** and **Movie** views showing
*which* use cases and concepts improved (watch Connections and Contacts fill
in). This is what "making invisible curation work visible" looks like as data.

The file is in exactly the format this repository's scheduled runs produce
(snapshots derived from `useCaseReport` JSONs — here translated from the MGC
score archive), so it doubles as a reference for the format documented in the
[main README](../README.md#what-a-run-produces).
