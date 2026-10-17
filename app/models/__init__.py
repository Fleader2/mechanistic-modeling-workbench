"""SQLAlchemy ORM models for the Workbench.

Submodules are imported so that ``Base.metadata`` is fully populated as soon
as ``app.models`` is imported, which is what ``migrations/env.py`` relies on
for Alembic to discover table metadata.

No model here ever declares a foreign key into another repository's
database -- there is no such thing as a cross-database foreign key in
PostgreSQL, and even if there were, the Workbench never assumes direct
access to Agent 1 (or any other agent's) tables (see
``docs/01_workbench_architecture.md``). Every reference to an Agent-1-owned
biological entity is a plain, nullable ``(entity_type, entity_id)`` pair --
a copied identifier, never a constraint-enforced relationship.
"""

from app.db.base import Base
from app.models.cross_module_diagnostic import CrossModuleDiagnostic, CrossModuleDiagnosticRun
from app.models.dataset_reference import DatasetReference
from app.models.hierarchy_checkpoint import HierarchyCheckpoint
from app.models.hierarchy_node import HierarchyNode
from app.models.hierarchy_pending_review_item import HierarchyPendingReviewItem
from app.models.hierarchy_resume_attempt import HierarchyResumeAttempt
from app.models.hierarchy_review_decision import HierarchyReviewDecision
from app.models.model import Model
from app.models.model_build_request import (
    ModelBuildRequest,
    ModelBuildRequestAssumption,
    ModelBuildRequestCompartment,
    ModelBuildRequestEnzymeState,
    ModelBuildRequestGeneProtein,
    ModelBuildRequestPathway,
    ModelBuildRequestReaction,
    ModelBuildRequestRegulatoryInteraction,
    ModelBuildRequestSpecies,
)
from app.models.model_module import ModelModule
from app.models.modeling_decision import ModelingDecision, ModelingDecisionOption
from app.models.module_aggregate import ModuleAggregate
from app.models.module_boundary_port import ModuleBoundaryPort
from app.models.module_execution_snapshot import ModuleExecutionSnapshot
from app.models.project import Project
from app.models.run_record import RunRecord
from app.models.subproject import Subproject

__all__ = [
    "Base",
    "CrossModuleDiagnostic",
    "CrossModuleDiagnosticRun",
    "DatasetReference",
    "HierarchyCheckpoint",
    "HierarchyNode",
    "HierarchyPendingReviewItem",
    "HierarchyResumeAttempt",
    "HierarchyReviewDecision",
    "Model",
    "ModelBuildRequest",
    "ModelBuildRequestAssumption",
    "ModelBuildRequestCompartment",
    "ModelBuildRequestEnzymeState",
    "ModelBuildRequestGeneProtein",
    "ModelBuildRequestPathway",
    "ModelBuildRequestReaction",
    "ModelBuildRequestRegulatoryInteraction",
    "ModelBuildRequestSpecies",
    "ModelModule",
    "ModelingDecision",
    "ModelingDecisionOption",
    "ModuleAggregate",
    "ModuleBoundaryPort",
    "ModuleExecutionSnapshot",
    "Project",
    "RunRecord",
    "Subproject",
]
