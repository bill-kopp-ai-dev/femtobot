"""Tool collections for the Femtobot agent.

Each module in this package exports a ``toolset()`` function that
returns a list of PydanticAI ``Tool`` instances. FemtobotAgent
combines them based on the active config (``tools.*.enabled``).

See Phase 3 for the migration of individual tools.
"""
