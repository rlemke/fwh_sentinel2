"""sentinel2-landchange example package — Facetwork workflows + handlers that
detect land-cover change from Sentinel-2 imagery between two time windows over
an area of interest and render the result as a tiled MapLibre map.

Discovered by the Facetwork runner via the ``facetwork.domains`` entry point
declared in ``pyproject.toml``::

    [project.entry-points."facetwork.domains"]
    sentinel2-landchange = "sentinel2:domain"

Once ``pip install -e .`` has been run from this repository, Facetwork's
``scripts/start-runner --example sentinel2-landchange`` and
``scripts/seed-examples`` pick this package up automatically — no edits to the
Facetwork repository required.
"""

from __future__ import annotations

from pathlib import Path

from facetwork.domains import DomainPackage

from .handlers import register_all_registry_handlers

# COG window-reads + compositing are blocking I/O; prefer the global execution
# timeout over per-step heartbeats for the fetch/composite facets.
_RUNNER_ENV = {
    "AFL_TASK_EXECUTION_TIMEOUT_MS": "1800000",
    "AFL_STUCK_TIMEOUT_MS": "3600000",
}

domain = DomainPackage(
    name="sentinel2-landchange",
    ffl_dir=Path(__file__).parent / "ffl",
    register_handlers=register_all_registry_handlers,
    runner_env=_RUNNER_ENV,
)
