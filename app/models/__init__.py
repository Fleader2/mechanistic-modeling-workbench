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
from app.models.calibration import (
    CalibrationArm,
    CalibrationExperiment,
    CalibrationExperimentOutputWeighting,
    CalibrationExperimentVariableBinding,
    CalibrationJob,
    CalibrationJobRevision,
    CalibrationParameterRole,
    CalibrationParameterRoleArm,
)
from app.models.calibration_scenario_evaluation import CalibrationScenarioEvaluationSnapshot
from app.models.cross_module_diagnostic import CrossModuleDiagnostic, CrossModuleDiagnosticRun
from app.models.dataset_model_alias_mapping import (
    DatasetModelAliasMappingAssignment,
    DatasetModelAliasMappingRevision,
)
from app.models.dataset_reference import DatasetReference
from app.models.hierarchy_checkpoint import HierarchyCheckpoint
from app.models.hierarchy_node import HierarchyNode
from app.models.hierarchy_pending_review_item import HierarchyPendingReviewItem
from app.models.hierarchy_resume_attempt import HierarchyResumeAttempt
from app.models.hierarchy_review_decision import HierarchyReviewDecision
from app.models.initial_conditions_alias_mapping import (
    InitialConditionsAliasMappingAssignment,
    InitialConditionsAliasMappingRevision,
)
from app.models.initial_conditions_dataset import (
    InitialConditionsDataset,
    InitialConditionsDatasetRow,
    InitialConditionsMeasurementColumn,
    InitialConditionsMeasurementUncertaintyColumn,
)
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
from app.models.model_import_provenance import ModelImportProvenance
from app.models.model_module import ModelModule
from app.models.model_parameter_catalog import ModelParameter, ModelParameterCatalog
from app.models.model_relationship import ModelRelationship
from app.models.model_species_catalog import ModelCompartment, ModelSpecies, ModelSpeciesCatalog
from app.models.modeling_decision import ModelingDecision, ModelingDecisionOption
from app.models.module_aggregate import ModuleAggregate
from app.models.module_boundary_port import ModuleBoundaryPort
from app.models.module_execution_snapshot import ModuleExecutionSnapshot
from app.models.module_set import (
    ModuleSet,
    ModuleSetDraft,
    ModuleSetDraftMember,
    ModuleSetMember,
    ModuleSetVersion,
)
from app.models.module_set_execution import ModuleSetMemberBoundaryPort, ModuleSetMemberReview
from app.models.project import Project
from app.models.run_record import RunRecord
from app.models.subproject import Subproject
from app.models.time_series_dataset import (
    TimeSeriesDataset,
    TimeSeriesDatasetRow,
    TimeSeriesIndependentVariableColumn,
    TimeSeriesMeasurementColumn,
    TimeSeriesMeasurementUncertaintyColumn,
)
from app.models.unit_resolution import UnitResolution

__all__ = [
    "Base",
    "CalibrationArm",
    "CalibrationExperiment",
    "CalibrationExperimentOutputWeighting",
    "CalibrationExperimentVariableBinding",
    "CalibrationJob",
    "CalibrationJobRevision",
    "CalibrationParameterRole",
    "CalibrationParameterRoleArm",
    "CalibrationScenarioEvaluationSnapshot",
    "CrossModuleDiagnostic",
    "CrossModuleDiagnosticRun",
    "DatasetModelAliasMappingAssignment",
    "DatasetModelAliasMappingRevision",
    "DatasetReference",
    "HierarchyCheckpoint",
    "HierarchyNode",
    "HierarchyPendingReviewItem",
    "HierarchyResumeAttempt",
    "HierarchyReviewDecision",
    "InitialConditionsAliasMappingAssignment",
    "InitialConditionsAliasMappingRevision",
    "InitialConditionsDataset",
    "InitialConditionsDatasetRow",
    "InitialConditionsMeasurementColumn",
    "InitialConditionsMeasurementUncertaintyColumn",
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
    "ModelCompartment",
    "ModelImportProvenance",
    "ModelModule",
    "ModelParameter",
    "ModelParameterCatalog",
    "ModelRelationship",
    "ModelSpecies",
    "ModelSpeciesCatalog",
    "ModelingDecision",
    "ModelingDecisionOption",
    "ModuleAggregate",
    "ModuleBoundaryPort",
    "ModuleExecutionSnapshot",
    "ModuleSet",
    "ModuleSetDraft",
    "ModuleSetDraftMember",
    "ModuleSetMember",
    "ModuleSetMemberBoundaryPort",
    "ModuleSetMemberReview",
    "ModuleSetVersion",
    "Project",
    "RunRecord",
    "Subproject",
    "TimeSeriesDataset",
    "TimeSeriesDatasetRow",
    "TimeSeriesIndependentVariableColumn",
    "TimeSeriesMeasurementColumn",
    "TimeSeriesMeasurementUncertaintyColumn",
    "UnitResolution",
]
