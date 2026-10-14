"""Orchestration adapter: the Workbench's own consumer of the integration
harness's canonical entrypoint.

Nothing here implements scientific logic. This package only (1) locates
the sibling harness repository, (2) serializes/deserializes the contract
types in ``app.contracts.harness``, (3) invokes the harness as a
subprocess, and (4) drives ``RunRecord``'s own lifecycle
(``app.persistence.run_record``) from the result. See
``docs/03_workbench_harness_contract.md``.
"""
