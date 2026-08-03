# Example: a history file during an active re-curation project

During 2025 Metadata Game Changers worked with the [EarthScope Consortium](https://www.earthscope.org/) (now the operator of NSF's National Geophysical Facility, NGF) to re-curate their DataCite metadata. The metadata are in two repositories that reflect the original organizations that provided amazing support for the geodetic (unavco.unavco) and seismological (iris.iris) research communities.

[`iris.iris_useCaseHistory.json`](iris.iris_useCaseHistory.json) is a real
useCaseHistory record, stored in json — that shows the work done during that project. It is an example of the file that the metrics-watch accumulates for your repository run by run —
from the IRIS seismology data repository, captured across the active metadata re-curation project during 2025.

**[The Metrics Viewer ↗](https://metadata-game-changers.github.io/recuration-watch/metricsViewer.html?src=https://raw.githubusercontent.com/Metadata-Game-Changers/metrics-watch/main/example/iris.iris_useCaseHistory.json)** shows how the metadata completeness evolved during this project as a table and as three plots (lines, radar grids, and a movie). The viewer shows several groups of use cases but the Project and SHARE use cases were not available during that project so they are empty in this example.

The file records thirteen scoring runs between March and December 2025. Because every run scores the
repository's records *as they are on that day*, the effect of re-curation is
visible directly: the FAIR total climbs in several steps from **11% in March to 37% by
August** and holds there — with the radar **Grid** and **Movie** views showing
*which* use cases and concepts improved (watch all four use cases fill
in during the project). This is what "making invisible curation work visible" looks like as data.

The file is in exactly the format this repository's scheduled runs produce
(snapshots derived from `useCaseReport` JSONs — here translated from the MGC
score archive), so it doubles as a reference for the format documented in the
[main README](../README.md#what-a-run-produces).

**More about the project:**  
Habermann, T., & Riley, J. (2025). Tech Notes: Identifying EarthScope. Zenodo. https://doi.org/10.5281/ZENODO.17238702  
Habermann, T., & Riley, J. (2025). How ROR IDs Help the EarthScope Consortium Track Organizational Partnerships. Research Organization Registry (ROR). https://doi.org/10.71938/T5BN-BM23
