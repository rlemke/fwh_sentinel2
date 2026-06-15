#!/usr/bin/env python3
"""sentinel2-landchange RegistryRunner entry point.

Starts a RegistryRunner that advertises every Sentinel-2 land-change event facet
(``s2.source.*``, ``s2.analyze.*``, ``s2.render.*``) and dispatches them to the
handlers in this package.

Usage::

    # From a Facetwork checkout (preferred — handles env + seeding):
    scripts/start-runner --example sentinel2-landchange

    # Or directly, once `pip install -e .` has registered the package:
    python agent.py

Requires (Docker/MongoDB mode)::

    AFL_MONGODB_URL=mongodb://localhost:27017
    AFL_MONGODB_DATABASE=facetwork
"""

from __future__ import annotations

from facetwork.runtime.registry_runner import create_registry_runner

from sentinel2.handlers import register_all_registry_handlers


def main() -> None:
    runner = create_registry_runner("sentinel2-landchange", topics=["s2.*"])
    register_all_registry_handlers(runner)
    print(f"sentinel2-landchange RegistryRunner started with "
          f"{len(runner.registered_names())} handlers")
    runner.start()


if __name__ == "__main__":
    main()
