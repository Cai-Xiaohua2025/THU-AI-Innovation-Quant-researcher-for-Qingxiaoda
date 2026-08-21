"""Qingyan Liangce financial research core bundled for the Skill CLI.

The competition Skill does not import the Flask service eagerly.  This keeps
the deterministic research and self-test paths usable with the minimal
dependency set.  Deployments that need the HTTP service can still import
``qingyan_agent.app.create_app`` explicitly after installing the full set.
"""

__version__ = "0.3.0-skill"

__all__ = ["__version__"]
