"""Standalone diagnostic scripts shipped with Femtobot (PR 5.1).

Each module here can be invoked as ``python -m femtobot.scripts.<name>``
without dragging the full runtime into the import graph — the
``audit_agents_md`` auditor in particular has zero network and zero
state, so it runs in a half-installed checkout and on CI.
"""
