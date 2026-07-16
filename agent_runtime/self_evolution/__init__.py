"""Governed AgentLab component evolution package.

Modules are intentionally not imported here. RoleCatalog is used by protocol
and routing bootstraps, while the compiler depends on both of those layers;
eager package exports would create a circular import during CLI startup.
"""
