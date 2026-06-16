"""Handler registration for the sentinel2-landchange example.

Imports are deferred to function bodies to avoid import-lock contention when a
RegistryRunner imports handler modules from separate threads.
"""

from __future__ import annotations


def register_all_handlers(poller) -> None:
    """Register all handlers with an AgentPoller."""
    from .analyze.analyze_handlers import register_analyze_handlers
    from .geo.geo_handlers import register_geo_handlers
    from .level.level_handlers import register_level_handlers
    from .render.render_handlers import register_render_handlers
    from .source.source_handlers import register_source_handlers
    from .timeseries.timeseries_handlers import register_timeseries_handlers

    register_geo_handlers(poller)
    register_source_handlers(poller)
    register_analyze_handlers(poller)
    register_render_handlers(poller)
    register_timeseries_handlers(poller)
    register_level_handlers(poller)


def register_all_registry_handlers(runner) -> None:
    """Register all handlers with a RegistryRunner (the in-repo discovery hook)."""
    from .analyze.analyze_handlers import register_handlers as reg_analyze
    from .geo.geo_handlers import register_handlers as reg_geo
    from .level.level_handlers import register_handlers as reg_level
    from .render.render_handlers import register_handlers as reg_render
    from .source.source_handlers import register_handlers as reg_source
    from .timeseries.timeseries_handlers import register_handlers as reg_ts

    reg_geo(runner)
    reg_source(runner)
    reg_analyze(runner)
    reg_render(runner)
    reg_ts(runner)
    reg_level(runner)
