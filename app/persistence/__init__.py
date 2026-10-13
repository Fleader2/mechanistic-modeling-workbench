"""Persistence functions for the Workbench's own schema.

Every ``persist_*``/``add_*`` function here only ever flushes, never
commits or rolls back -- that is the caller's own transaction to own,
mirroring the convention used across the sibling agent repositories.
"""
