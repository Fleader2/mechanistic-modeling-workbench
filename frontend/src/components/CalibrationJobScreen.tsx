import { useCallback, useEffect, useRef, useState } from "react";
import {
  addCalibrationArm,
  addCalibrationExperiment,
  addCalibrationParameterRole,
  addCalibrationVariableBinding,
  ApiRequestError,
  completeCalibrationReview,
  declareModelRelationship,
  getCalibrationJob,
  getCalibrationJobRevision,
  getCalibrationScenarioEvaluation,
  getCurrentAliasMapping,
  getCurrentInitialConditionsAliasMapping,
  getModelingStudy,
  getModelingStudyModels,
  getProject,
  listCalibrationJobModelRelationships,
  listCalibrationJobRevisions,
  listCalibrationScenarioEvaluations,
  listInitialConditionsDatasets,
  listTimeSeriesDatasets,
  previewCalibrationReview,
  removeCalibrationArm,
  removeCalibrationExperiment,
  removeCalibrationExperimentOutputWeighting,
  removeCalibrationParameterRole,
  removeCalibrationVariableBinding,
  setCalibrationExperimentInitialConditionsDataset,
  setCalibrationExperimentInitialConditionsMapping,
  setCalibrationExperimentMapping,
  setCalibrationExperimentObjectiveWeighting,
  setCalibrationExperimentOutputWeighting,
  setCalibrationExperimentRole,
  submitCalibrationScenarioEvaluation,
} from "../api/client";
import { createStaleGuard } from "../lib/staleGuard";
import { formatRunStatus, formatScientific, fullPrecisionTitle } from "../format";
import { RouterLink } from "./RouterLink";
import type {
  CalibrationArmItem,
  CalibrationBindingModelMeaning,
  CalibrationBindingValueSource,
  CalibrationExperimentItem,
  CalibrationJobDetail,
  CalibrationJobRevisionDetail,
  CalibrationJobRevisionSummary,
  CalibrationParameterRoleKind,
  CalibrationReviewResult,
  InitialConditionsDatasetListItem,
  ModelListItem,
  ModelRelationshipItem,
  OutputWeightingItem,
  ProjectDetail,
  ScenarioEvaluationRunItem,
  SubprojectDetail,
  TimeSeriesDatasetListItem,
} from "../types";

type LoadState<T> =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; value: T };

type Step = "models" | "variables" | "review";

interface CalibrationJobScreenProps {
  projectId: string;
  studyId: string;
  jobId: string;
  onProjectChange: (project: ProjectDetail | null) => void;
  onStudyChange: (study: SubprojectDetail | null) => void;
}

function errorMessage(error: unknown): string {
  return error instanceof ApiRequestError ? error.message : "An unexpected error occurred.";
}

/** The Joint Calibration Workflow configuration-only increment's own three-screen workflow,
 * rendered as three steps of one routed page (see docs/30's own disclosed simplification: one
 * URL, internal step state, rather than three distinct URLs).
 *
 * Screen 1 "Models & experimental data," Screen 2 "Variables, parameters & experimental
 * settings," Screen 3 "Review & readiness" -- see docs/29_joint_calibration_workflow_design.md
 * §7. Every mutation here persists immediately (there is no separate "unsaved" staging state
 * to lose), guarded by the job's own `edit_version` optimistic-concurrency token. Nothing on
 * this screen ever executes anything -- whole-model execution does not exist yet (docs/29 §6),
 * so Screen 3's "Run" is always disabled, with a named reason, regardless of how complete the
 * configuration is. */
export function CalibrationJobScreen({
  projectId,
  studyId,
  jobId,
  onProjectChange,
  onStudyChange,
}: CalibrationJobScreenProps) {
  const [projectState, setProjectState] = useState<LoadState<ProjectDetail>>({
    status: "loading",
  });
  const [studyState, setStudyState] = useState<LoadState<SubprojectDetail>>({
    status: "loading",
  });
  const [jobState, setJobState] = useState<LoadState<CalibrationJobDetail>>({
    status: "loading",
  });
  const [models, setModels] = useState<ModelListItem[]>([]);
  const [datasets, setDatasets] = useState<TimeSeriesDatasetListItem[]>([]);
  const [initialConditionsDatasets, setInitialConditionsDatasets] = useState<
    InitialConditionsDatasetListItem[]
  >([]);
  const [relationships, setRelationships] = useState<ModelRelationshipItem[]>([]);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("models");
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(null);
  const [reviewState, setReviewState] = useState<LoadState<CalibrationReviewResult>>({
    status: "loading",
  });
  const guard = useRef(createStaleGuard<string>()).current;

  const reloadJob = useCallback(() => {
    return getCalibrationJob(projectId, studyId, jobId).then((job) => {
      setJobState({ status: "ready", value: job });
      return job;
    });
  }, [projectId, studyId, jobId]);

  const reloadRelationships = useCallback(() => {
    listCalibrationJobModelRelationships(projectId, studyId, jobId)
      .then(setRelationships)
      .catch(() => {
        /* supplementary; its own load failure never blocks the screen */
      });
  }, [projectId, studyId, jobId]);

  useEffect(() => {
    const key = `${projectId}/${studyId}/${jobId}`;
    guard.start(key);
    setProjectState({ status: "loading" });
    setStudyState({ status: "loading" });
    setJobState({ status: "loading" });
    onProjectChange(null);
    onStudyChange(null);

    getProject(projectId)
      .then((project) => {
        if (!guard.isCurrent(key)) return;
        setProjectState({ status: "ready", value: project });
        onProjectChange(project);

        return getModelingStudy(projectId, studyId).then((study) => {
          if (!guard.isCurrent(key)) return;
          setStudyState({ status: "ready", value: study });
          onStudyChange(study);

          getModelingStudyModels(projectId, studyId).then((items) => {
            if (guard.isCurrent(key)) setModels(items);
          });
          listTimeSeriesDatasets(projectId, studyId).then((items) => {
            if (guard.isCurrent(key)) setDatasets(items);
          });
          listInitialConditionsDatasets(projectId, studyId).then((items) => {
            if (guard.isCurrent(key)) setInitialConditionsDatasets(items);
          });

          getCalibrationJob(projectId, studyId, jobId)
            .then((job) => {
              if (!guard.isCurrent(key)) return;
              setJobState({ status: "ready", value: job });
              reloadRelationships();
            })
            .catch((error: unknown) => {
              if (!guard.isCurrent(key)) return;
              setJobState(
                error instanceof ApiRequestError && error.status === 404
                  ? { status: "not-found" }
                  : { status: "error", message: errorMessage(error) },
              );
            });
        });
      })
      .catch((error: unknown) => {
        if (!guard.isCurrent(key)) return;
        setProjectState(
          error instanceof ApiRequestError && error.status === 404
            ? { status: "not-found" }
            : { status: "error", message: errorMessage(error) },
        );
      });

    return () => {
      onProjectChange(null);
      onStudyChange(null);
    };
  }, [projectId, studyId, jobId]);

  function withJob<A extends unknown[]>(
    mutate: (job: CalibrationJobDetail, ...args: A) => Promise<CalibrationJobDetail>,
  ) {
    return (...args: A) => {
      if (jobState.status !== "ready") return;
      setMutationError(null);
      mutate(jobState.value, ...args)
        .then((job) => {
          setJobState({ status: "ready", value: job });
          if (jobState.value.arms.length !== job.arms.length) reloadRelationships();
        })
        .catch((error: unknown) => setMutationError(errorMessage(error)));
    };
  }

  const handleAddArm = withJob((job: CalibrationJobDetail, modelId: string) =>
    addCalibrationArm(projectId, studyId, jobId, {
      model_id: modelId,
      expected_edit_version: job.edit_version,
    }),
  );
  const handleRemoveArm = withJob((job: CalibrationJobDetail, armId: string) =>
    removeCalibrationArm(projectId, studyId, jobId, armId, job.edit_version),
  );
  const handleAddExperiment = withJob(
    (job: CalibrationJobDetail, armId: string, datasetId: string) =>
      addCalibrationExperiment(projectId, studyId, jobId, armId, {
        time_series_dataset_id: datasetId,
        expected_edit_version: job.edit_version,
      }),
  );
  const handleRemoveExperiment = withJob((job: CalibrationJobDetail, experimentId: string) =>
    removeCalibrationExperiment(projectId, studyId, jobId, experimentId, job.edit_version),
  );
  const handleSetExperimentRole = withJob(
    (
      job: CalibrationJobDetail,
      experimentId: string,
      role: CalibrationExperimentItem["role"],
    ) =>
      setCalibrationExperimentRole(projectId, studyId, jobId, experimentId, {
        role,
        expected_edit_version: job.edit_version,
      }),
  );
  const handleRepinMapping = withJob(
    (job: CalibrationJobDetail, experimentId: string, revisionNumber: number | null) =>
      setCalibrationExperimentMapping(projectId, studyId, jobId, experimentId, {
        alias_mapping_revision_number: revisionNumber,
        expected_edit_version: job.edit_version,
      }),
  );
  const handleSetInitialConditionsDataset = withJob(
    (job: CalibrationJobDetail, experimentId: string, datasetId: string | null) =>
      setCalibrationExperimentInitialConditionsDataset(projectId, studyId, jobId, experimentId, {
        initial_conditions_dataset_id: datasetId,
        expected_edit_version: job.edit_version,
      }),
  );
  const handleRepinInitialConditionsMapping = withJob(
    (job: CalibrationJobDetail, experimentId: string, revisionNumber: number | null) =>
      setCalibrationExperimentInitialConditionsMapping(
        projectId,
        studyId,
        jobId,
        experimentId,
        {
          alias_mapping_revision_number: revisionNumber,
          expected_edit_version: job.edit_version,
        },
      ),
  );
  const handleSetObjectiveWeighting = withJob(
    (
      job: CalibrationJobDetail,
      experimentId: string,
      weighting: CalibrationExperimentItem["objective_weighting"],
      notes: string,
    ) =>
      setCalibrationExperimentObjectiveWeighting(projectId, studyId, jobId, experimentId, {
        objective_weighting: weighting,
        weighting_notes: notes || null,
        expected_edit_version: job.edit_version,
      }),
  );
  const handleSetOutputWeighting = withJob(
    (
      job: CalibrationJobDetail,
      experimentId: string,
      outputColumnName: string,
      uncertaintySource: OutputWeightingItem["uncertainty_source"],
      assumedSigmaValue: string,
      assumedSigmaUnit: string,
      assumedSigmaStatisticKind: OutputWeightingItem["assumed_sigma_statistic_kind"] | "",
      relativeOutputWeight: string,
      provenanceNote: string,
    ) =>
      setCalibrationExperimentOutputWeighting(projectId, studyId, jobId, experimentId, {
        output_column_name: outputColumnName,
        uncertainty_source: uncertaintySource,
        assumed_sigma_value: uncertaintySource === "USER_ASSUMED" ? assumedSigmaValue || null : null,
        assumed_sigma_unit: uncertaintySource === "USER_ASSUMED" ? assumedSigmaUnit || null : null,
        assumed_sigma_statistic_kind:
          uncertaintySource === "USER_ASSUMED" ? assumedSigmaStatisticKind || null : null,
        relative_output_weight: relativeOutputWeight || "1",
        provenance_note: provenanceNote || null,
        expected_edit_version: job.edit_version,
      }),
  );
  const handleRemoveOutputWeighting = withJob((job: CalibrationJobDetail, weightingId: string) =>
    removeCalibrationExperimentOutputWeighting(projectId, studyId, jobId, weightingId, job.edit_version),
  );
  const handleAddBinding = withJob(
    (
      job: CalibrationJobDetail,
      experimentId: string,
      modelMeaning: CalibrationBindingModelMeaning,
      targetComponentId: string,
      valueSource: CalibrationBindingValueSource,
      constantValue: string,
      constantUnit: string,
      sourceColumnName: string,
      source: string,
      interventionTime: string,
    ) =>
      addCalibrationVariableBinding(projectId, studyId, jobId, experimentId, {
        model_meaning: modelMeaning,
        target_component_id: targetComponentId,
        value_source: valueSource,
        constant_value: valueSource === "CONSTANT" ? constantValue || null : null,
        constant_unit: valueSource === "CONSTANT" ? constantUnit || null : null,
        source_column_name:
          valueSource === "DATASET_COLUMN" || valueSource === "INITIAL_CONDITIONS_DATASET"
            ? sourceColumnName || null
            : null,
        source: source || null,
        intervention_time: modelMeaning === "INTERVENTION" ? interventionTime || null : null,
        expected_edit_version: job.edit_version,
      }),
  );
  const handleRemoveBinding = withJob((job: CalibrationJobDetail, bindingId: string) =>
    removeCalibrationVariableBinding(projectId, studyId, jobId, bindingId, job.edit_version),
  );
  const handleAddParameterRole = withJob(
    (
      job: CalibrationJobDetail,
      parameterName: string,
      role: CalibrationParameterRoleKind,
      armIds: string[],
      fixedValue: string,
      lowerBound: string,
      upperBound: string,
      unit: string,
      referenceArmId: string,
      referenceParameterName: string,
      coefficientA: string,
      coefficientAIsFixed: boolean,
      coefficientB: string,
      coefficientBIsFixed: boolean,
    ) =>
      addCalibrationParameterRole(projectId, studyId, jobId, {
        parameter_name: parameterName,
        role,
        arm_ids: armIds,
        fixed_value: fixedValue || null,
        lower_bound: lowerBound || null,
        upper_bound: upperBound || null,
        unit: unit || null,
        reference_arm_id: referenceArmId || null,
        reference_parameter_name: referenceParameterName || null,
        coefficient_a: coefficientA || null,
        coefficient_a_is_fixed: coefficientAIsFixed,
        coefficient_b: coefficientB || null,
        coefficient_b_is_fixed: coefficientBIsFixed,
        expected_edit_version: job.edit_version,
      }),
  );
  const handleRemoveParameterRole = withJob((job: CalibrationJobDetail, roleId: string) =>
    removeCalibrationParameterRole(projectId, studyId, jobId, roleId, job.edit_version),
  );
  const handleDeclareRelationship = withJob(
    (
      _job: CalibrationJobDetail,
      modelIdA: string,
      modelIdB: string,
      kind: "VARIANT_OF" | "SHARES_STRUCTURE_WITH",
      labelA: string,
      labelB: string,
    ) =>
      declareModelRelationship(projectId, studyId, {
        model_id_a: modelIdA,
        model_id_b: modelIdB,
        relationship_kind: kind,
        role_label_a: labelA || null,
        role_label_b: labelB || null,
      }).then(() => {
        reloadRelationships();
        return reloadJob();
      }),
  );

  function loadReview() {
    setReviewState({ status: "loading" });
    previewCalibrationReview(projectId, studyId, jobId)
      .then((result) => setReviewState({ status: "ready", value: result }))
      .catch((error: unknown) => setReviewState({ status: "error", message: errorMessage(error) }));
  }

  function handleCompleteReview() {
    if (jobState.status !== "ready") return;
    setMutationError(null);
    completeCalibrationReview(projectId, studyId, jobId, {
      expected_edit_version: jobState.value.edit_version,
    })
      .then((result) => {
        setJobState({ status: "ready", value: result.job });
        setReviewState({ status: "ready", value: result });
      })
      .catch((error: unknown) => {
        if (error instanceof ApiRequestError && error.status === 422) {
          const findings = (error.context?.findings as CalibrationReviewResult["findings"]) ?? [];
          reloadJob().then((job) => {
            setReviewState({
              status: "ready",
              value: {
                job,
                findings,
                execution_capability: {
                  available: false,
                  reason: "Whole-model execution is not yet available for calibration.",
                  missing_capability: "WHOLE_MODEL_EXECUTION",
                },
              },
            });
          });
          setMutationError(
            "This job cannot complete review while it has unresolved blocking findings -- see below.",
          );
        } else {
          setMutationError(errorMessage(error));
        }
      });
  }

  for (const [state, label] of [
    [projectState, "project"],
    [studyState, "Modeling Study"],
  ] as const) {
    if (state.status === "loading") {
      return (
        <div className="projects-screen">
          <p className="status-message">Loading {label}…</p>
        </div>
      );
    }
    if (state.status === "not-found" || state.status === "error") {
      return (
        <div className="projects-screen">
          <p className="status-message error" role="alert">
            {state.status === "not-found"
              ? `This ${label} could not be found.`
              : `Couldn't load this ${label}: ${state.message}`}
          </p>
          <RouterLink to="/projects" className="back-link">
            Back to All Projects
          </RouterLink>
        </div>
      );
    }
  }
  if (projectState.status !== "ready" || studyState.status !== "ready") return null;
  const project = projectState.value;
  const study = studyState.value;

  if (jobState.status === "loading") {
    return (
      <div className="projects-screen">
        <p className="status-message">Loading calibration job…</p>
      </div>
    );
  }
  if (jobState.status !== "ready") {
    return (
      <div className="projects-screen">
        <p className="status-message error" role="alert">
          {jobState.status === "not-found"
            ? "This calibration job could not be found."
            : `Couldn't load this calibration job: ${jobState.message}`}
        </p>
      </div>
    );
  }
  const job = jobState.value;
  const jobUrl = `/projects/${projectId}/studies/${studyId}/calibration-jobs/${jobId}`;

  const allExperiments: { experiment: CalibrationExperimentItem; arm: CalibrationArmItem }[] = [];
  for (const arm of job.arms) {
    for (const experiment of arm.experiments) allExperiments.push({ experiment, arm });
  }
  const canAdvanceFromModels = job.arms.every((arm) => arm.experiments.length > 0) && job.arms.length > 0;

  return (
    <div className="projects-screen">
      <p className="breadcrumb">
        <RouterLink to="/projects">Projects</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}`}>{project.title}</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}/studies/${studyId}`}>{study.title}</RouterLink> /{" "}
        <RouterLink to={`/projects/${projectId}/studies/${studyId}/calibration-jobs`}>
          Calibration jobs
        </RouterLink>{" "}
        / Job
      </p>
      <h1>Calibration job</h1>
      <p className="screen-subtitle">
        Status: {job.status} · edit version {job.edit_version} · every change is saved
        immediately -- there is nothing further to save.
      </p>

      <nav aria-label="Calibration job steps" className="card">
        <button
          type="button"
          className={step === "models" ? "primary-button" : "secondary-button"}
          onClick={() => setStep("models")}
        >
          1. Models &amp; experimental data
        </button>{" "}
        <button
          type="button"
          className={step === "variables" ? "primary-button" : "secondary-button"}
          disabled={!canAdvanceFromModels}
          onClick={() => setStep("variables")}
        >
          2. Variables, parameters &amp; experimental settings
        </button>{" "}
        <button
          type="button"
          className={step === "review" ? "primary-button" : "secondary-button"}
          disabled={!canAdvanceFromModels}
          onClick={() => {
            setStep("review");
            loadReview();
          }}
        >
          3. Review &amp; readiness
        </button>
      </nav>

      {mutationError && (
        <p className="status-message error" role="alert">
          {mutationError}
        </p>
      )}

      {step === "models" && (
        <ModelsAndDataStep
          job={job}
          models={models}
          datasets={datasets}
          relationships={relationships}
          onAddArm={handleAddArm}
          onRemoveArm={handleRemoveArm}
          onAddExperiment={handleAddExperiment}
          onRemoveExperiment={handleRemoveExperiment}
          onSetExperimentRole={handleSetExperimentRole}
          onDeclareRelationship={handleDeclareRelationship}
          projectId={projectId}
          studyId={studyId}
        />
      )}

      {step === "variables" && (
        <VariablesStep
          job={job}
          allExperiments={allExperiments}
          initialConditionsDatasets={initialConditionsDatasets}
          selectedExperimentId={selectedExperimentId}
          onSelectExperiment={setSelectedExperimentId}
          onRepinMapping={handleRepinMapping}
          onSetInitialConditionsDataset={handleSetInitialConditionsDataset}
          onRepinInitialConditionsMapping={handleRepinInitialConditionsMapping}
          onSetObjectiveWeighting={handleSetObjectiveWeighting}
          onSetOutputWeighting={handleSetOutputWeighting}
          onRemoveOutputWeighting={handleRemoveOutputWeighting}
          onAddBinding={handleAddBinding}
          onRemoveBinding={handleRemoveBinding}
          onAddParameterRole={handleAddParameterRole}
          onRemoveParameterRole={handleRemoveParameterRole}
          projectId={projectId}
          studyId={studyId}
        />
      )}

      {step === "review" && (
        <ReviewStep
          job={job}
          reviewState={reviewState}
          onRefresh={loadReview}
          onCompleteReview={handleCompleteReview}
          projectId={projectId}
          studyId={studyId}
          jobId={jobId}
        />
      )}

      <p>
        <RouterLink to={jobUrl.slice(0, jobUrl.lastIndexOf("/"))} className="back-link">
          Back to calibration jobs
        </RouterLink>
      </p>
    </div>
  );
}

// --- Screen 1: Models & experimental data -------------------------------------------------

interface ModelsAndDataStepProps {
  job: CalibrationJobDetail;
  models: ModelListItem[];
  datasets: TimeSeriesDatasetListItem[];
  relationships: ModelRelationshipItem[];
  onAddArm: (modelId: string) => void;
  onRemoveArm: (armId: string) => void;
  onAddExperiment: (armId: string, datasetId: string) => void;
  onRemoveExperiment: (experimentId: string) => void;
  onSetExperimentRole: (
    experimentId: string,
    role: CalibrationExperimentItem["role"],
  ) => void;
  onDeclareRelationship: (
    modelIdA: string,
    modelIdB: string,
    kind: "VARIANT_OF" | "SHARES_STRUCTURE_WITH",
    labelA: string,
    labelB: string,
  ) => void;
  projectId: string;
  studyId: string;
}

function ModelsAndDataStep({
  job,
  models,
  datasets,
  relationships,
  onAddArm,
  onRemoveArm,
  onAddExperiment,
  onRemoveExperiment,
  onSetExperimentRole,
  onDeclareRelationship,
  projectId,
  studyId,
}: ModelsAndDataStepProps) {
  const [newArmModelId, setNewArmModelId] = useState("");
  const [relLabelA, setRelLabelA] = useState("");
  const [relLabelB, setRelLabelB] = useState("");
  const [relKind, setRelKind] = useState<"VARIANT_OF" | "SHARES_STRUCTURE_WITH">("VARIANT_OF");
  const [mappedDatasetIds, setMappedDatasetIds] = useState<Record<string, Set<string>>>({});
  const [selectedDatasetByArm, setSelectedDatasetByArm] = useState<Record<string, string>>({});

  function checkMappedDatasets(armId: string, modelId: string, candidateIds: string[]) {
    Promise.all(
      candidateIds.map((datasetId) =>
        getCurrentAliasMapping(projectId, studyId, datasetId, modelId)
          .then((mapping) => ({
            datasetId,
            hasAssigned: mapping.assignments.some((a) => a.status === "ASSIGNED"),
          }))
          .catch(() => ({ datasetId, hasAssigned: false })),
      ),
    ).then((results) => {
      setMappedDatasetIds((prev) => ({
        ...prev,
        [armId]: new Set(results.filter((r) => r.hasAssigned).map((r) => r.datasetId)),
      }));
    });
  }

  const showRelationshipsSection = job.arms.length >= 2 || relationships.length > 0;

  return (
    <>
      <section className="card" aria-label="Whole-model versions">
        <h2>Models &amp; experimental data</h2>
        <p className="screen-subtitle">
          Select whole-model versions and assign datasets as experiments. Module selection,
          boundary review, and decomposition are a separate workflow -- never part of this one
          (docs/29 §6).
        </p>

        <p>
          <label htmlFor="new-arm-model">Add a model version as an arm</label>
          <br />
          <select
            id="new-arm-model"
            value={newArmModelId}
            onChange={(event) => setNewArmModelId(event.target.value)}
          >
            <option value="">Choose a model…</option>
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.name}
              </option>
            ))}
          </select>{" "}
          <button
            type="button"
            className="secondary-button"
            disabled={!newArmModelId}
            onClick={() => {
              onAddArm(newArmModelId);
              setNewArmModelId("");
            }}
          >
            Add arm
          </button>
        </p>

        {job.arms.length === 0 && (
          <p className="status-message">No arms yet -- add at least one model version.</p>
        )}

        {job.arms.map((arm) => {
          const unassignedDatasets = datasets.filter(
            (d) => !arm.experiments.some((e) => e.time_series_dataset_id === d.id),
          );
          const mapped = mappedDatasetIds[arm.id];
          const unambiguousPreselect =
            mapped && mapped.size === 1 ? Array.from(mapped)[0] : "";

          return (
            <div className="time-series-preview" key={arm.id}>
              <h3>
                Arm: {arm.model_name}
                {arm.role_label ? ` (${arm.role_label})` : ""}
              </h3>
              <button type="button" className="secondary-button" onClick={() => onRemoveArm(arm.id)}>
                Remove arm
              </button>

              <table className="module-sets-table">
                <thead>
                  <tr>
                    <th scope="col">Dataset</th>
                    <th scope="col">Role</th>
                    <th scope="col">Mapping</th>
                    <th scope="col"></th>
                  </tr>
                </thead>
                <tbody>
                  {arm.experiments.map((experiment) => (
                    <tr key={experiment.id}>
                      <td>{experiment.dataset_name}</td>
                      <td>
                        <select
                          aria-label={`Role for ${experiment.dataset_name}`}
                          value={experiment.role}
                          onChange={(event) =>
                            onSetExperimentRole(
                              experiment.id,
                              event.target.value as CalibrationExperimentItem["role"],
                            )
                          }
                        >
                          <option value="CALIBRATION">Calibration</option>
                          <option value="HELD_OUT_VALIDATION">Held-out validation</option>
                        </select>
                      </td>
                      <td>
                        {experiment.alias_mapping_revision_number === null
                          ? "Not mapped yet"
                          : `Revision ${experiment.alias_mapping_revision_number}${
                              experiment.mapping_is_stale ? " (stale)" : ""
                            }`}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => onRemoveExperiment(experiment.id)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {unassignedDatasets.length > 0 && (
                <p>
                  <label htmlFor={`add-experiment-${arm.id}`}>Add a dataset as an experiment</label>
                  <br />
                  <select
                    id={`add-experiment-${arm.id}`}
                    value={selectedDatasetByArm[arm.id] ?? unambiguousPreselect}
                    onChange={(event) =>
                      setSelectedDatasetByArm((prev) => ({ ...prev, [arm.id]: event.target.value }))
                    }
                    onFocus={() =>
                      checkMappedDatasets(
                        arm.id,
                        arm.model_id,
                        unassignedDatasets.map((d) => d.id),
                      )
                    }
                  >
                    <option value="">Choose a dataset…</option>
                    {unassignedDatasets.map((dataset) => (
                      <option key={dataset.id} value={dataset.id}>
                        {dataset.name}
                        {mapped?.has(dataset.id) ? " (already mapped to this model)" : ""}
                      </option>
                    ))}
                  </select>{" "}
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={!(selectedDatasetByArm[arm.id] ?? unambiguousPreselect)}
                    onClick={() => {
                      const datasetId = selectedDatasetByArm[arm.id] ?? unambiguousPreselect;
                      if (datasetId) {
                        onAddExperiment(arm.id, datasetId);
                        setSelectedDatasetByArm((prev) => ({ ...prev, [arm.id]: "" }));
                      }
                    }}
                  >
                    Add experiment
                  </button>
                </p>
              )}
            </div>
          );
        })}
      </section>

      {showRelationshipsSection && (
        <section className="card" aria-label="Model relationships">
          <h2>Model relationships</h2>
          {relationships.length === 0 && (
            <p className="status-message">
              No relationship declared yet between this job&apos;s own models.
            </p>
          )}
          {relationships.map((r) => (
            <p key={r.id}>
              {r.role_label_a ?? r.model_id_a} {r.relationship_kind} {r.role_label_b ?? r.model_id_b}
            </p>
          ))}
          {job.arms.length >= 2 && (
            <div>
              <p>
                <select
                  value={relKind}
                  onChange={(event) =>
                    setRelKind(event.target.value as "VARIANT_OF" | "SHARES_STRUCTURE_WITH")
                  }
                >
                  <option value="VARIANT_OF">Variant of</option>
                  <option value="SHARES_STRUCTURE_WITH">Shares structure with</option>
                </select>
              </p>
              <p>
                <input
                  type="text"
                  placeholder="Role label for first model (e.g. no_drug)"
                  value={relLabelA}
                  onChange={(event) => setRelLabelA(event.target.value)}
                />{" "}
                <input
                  type="text"
                  placeholder="Role label for second model (e.g. drug_treated)"
                  value={relLabelB}
                  onChange={(event) => setRelLabelB(event.target.value)}
                />
              </p>
              <button
                type="button"
                className="secondary-button"
                onClick={() =>
                  onDeclareRelationship(
                    job.arms[0].model_id,
                    job.arms[1].model_id,
                    relKind,
                    relLabelA,
                    relLabelB,
                  )
                }
              >
                Declare relationship between {job.arms[0].model_name} and {job.arms[1].model_name}
              </button>
            </div>
          )}
        </section>
      )}
    </>
  );
}

// --- Screen 2: Variables, parameters & experimental settings ------------------------------

interface VariablesStepProps {
  job: CalibrationJobDetail;
  allExperiments: { experiment: CalibrationExperimentItem; arm: CalibrationArmItem }[];
  initialConditionsDatasets: InitialConditionsDatasetListItem[];
  selectedExperimentId: string | null;
  onSelectExperiment: (id: string | null) => void;
  onRepinMapping: (experimentId: string, revisionNumber: number | null) => void;
  onSetInitialConditionsDataset: (experimentId: string, datasetId: string | null) => void;
  onRepinInitialConditionsMapping: (
    experimentId: string,
    revisionNumber: number | null,
  ) => void;
  onSetObjectiveWeighting: (
    experimentId: string,
    weighting: CalibrationExperimentItem["objective_weighting"],
    notes: string,
  ) => void;
  onSetOutputWeighting: (
    experimentId: string,
    outputColumnName: string,
    uncertaintySource: OutputWeightingItem["uncertainty_source"],
    assumedSigmaValue: string,
    assumedSigmaUnit: string,
    assumedSigmaStatisticKind: OutputWeightingItem["assumed_sigma_statistic_kind"] | "",
    relativeOutputWeight: string,
    provenanceNote: string,
  ) => void;
  onRemoveOutputWeighting: (weightingId: string) => void;
  onAddBinding: (
    experimentId: string,
    modelMeaning: CalibrationBindingModelMeaning,
    targetComponentId: string,
    valueSource: CalibrationBindingValueSource,
    constantValue: string,
    constantUnit: string,
    sourceColumnName: string,
    source: string,
    interventionTime: string,
  ) => void;
  onRemoveBinding: (bindingId: string) => void;
  onAddParameterRole: (
    parameterName: string,
    role: CalibrationParameterRoleKind,
    armIds: string[],
    fixedValue: string,
    lowerBound: string,
    upperBound: string,
    unit: string,
    referenceArmId: string,
    referenceParameterName: string,
    coefficientA: string,
    coefficientAIsFixed: boolean,
    coefficientB: string,
    coefficientBIsFixed: boolean,
  ) => void;
  onRemoveParameterRole: (roleId: string) => void;
  projectId: string;
  studyId: string;
}

function VariablesStep({
  job,
  allExperiments,
  initialConditionsDatasets,
  selectedExperimentId,
  onSelectExperiment,
  onRepinMapping,
  onSetInitialConditionsDataset,
  onRepinInitialConditionsMapping,
  onSetObjectiveWeighting,
  onSetOutputWeighting,
  onRemoveOutputWeighting,
  onAddBinding,
  onRemoveBinding,
  onAddParameterRole,
  onRemoveParameterRole,
  projectId,
  studyId,
}: VariablesStepProps) {
  const current =
    allExperiments.find((e) => e.experiment.id === selectedExperimentId) ?? allExperiments[0];

  const [bindingMeaning, setBindingMeaning] = useState<CalibrationBindingModelMeaning>(
    "INITIAL_VALUE",
  );
  const [bindingValueSource, setBindingValueSource] =
    useState<CalibrationBindingValueSource>("CONSTANT");
  const [bindingComponent, setBindingComponent] = useState("");
  const [bindingConstantValue, setBindingConstantValue] = useState("");
  const [bindingConstantUnit, setBindingConstantUnit] = useState("");
  const [bindingSourceColumn, setBindingSourceColumn] = useState("");
  const [bindingInterventionTime, setBindingInterventionTime] = useState("");
  const [weightingNotes, setWeightingNotes] = useState("");
  const [selectedIcDatasetId, setSelectedIcDatasetId] = useState("");

  const [outputColumnName, setOutputColumnName] = useState("");
  const [outputUncertaintySource, setOutputUncertaintySource] =
    useState<OutputWeightingItem["uncertainty_source"]>("UNKNOWN");
  const [outputSigmaValue, setOutputSigmaValue] = useState("");
  const [outputSigmaUnit, setOutputSigmaUnit] = useState("");
  const [outputSigmaStatisticKind, setOutputSigmaStatisticKind] = useState<
    OutputWeightingItem["assumed_sigma_statistic_kind"] | ""
  >("");
  const [outputRelativeWeight, setOutputRelativeWeight] = useState("1");
  const [outputProvenanceNote, setOutputProvenanceNote] = useState("");

  const [roleName, setRoleName] = useState("");
  const [roleKind, setRoleKind] = useState<CalibrationParameterRoleKind>("MODEL_SPECIFIC");
  const [roleArmIds, setRoleArmIds] = useState<string[]>([]);
  const [roleFixedValue, setRoleFixedValue] = useState("");
  const [roleLowerBound, setRoleLowerBound] = useState("");
  const [roleUpperBound, setRoleUpperBound] = useState("");
  const [roleUnit, setRoleUnit] = useState("");
  const [roleReferenceArmId, setRoleReferenceArmId] = useState("");
  const [roleReferenceParamName, setRoleReferenceParamName] = useState("");
  const [coefficientA, setCoefficientA] = useState("");
  const [coefficientB, setCoefficientB] = useState("");

  const isLinkRole =
    roleKind === "EXACT_EQUALITY" ||
    roleKind === "EXACT_AFFINE_LINK" ||
    roleKind === "SOFT_PRIOR_LINK";

  return (
    <>
      <section className="card" aria-label="Variables and experimental settings">
        <h2>Variables, parameters &amp; experimental settings</h2>

        {allExperiments.length === 0 && (
          <p className="status-message">Add at least one experiment on Screen 1 first.</p>
        )}

        {allExperiments.length > 1 && (
          <p>
            <label htmlFor="experiment-selector">Experiment</label>
            <br />
            <select
              id="experiment-selector"
              value={current?.experiment.id ?? ""}
              onChange={(event) => onSelectExperiment(event.target.value)}
            >
              {allExperiments.map(({ experiment, arm }) => (
                <option key={experiment.id} value={experiment.id}>
                  {arm.model_name} — {experiment.dataset_name}
                </option>
              ))}
            </select>
          </p>
        )}

        {current && (
          <>
            <h3>
              {current.arm.model_name} — {current.experiment.dataset_name}
            </h3>

            <h4>Independent variables</h4>
            <p className="screen-subtitle">
              <code>time</code> is always mapped to the model&apos;s own simulated time axis.
              Any other independent-variable column this dataset declares (dose, an arbitrary
              intervention level, …) is bound below as a per-experiment variable binding with
              value_source=DATASET_COLUMN, preserving the original per-row data and units
              (docs/31) -- never collapsed to a single curator-typed constant.
              {current.experiment.available_dataset_columns.length > 0
                ? ` Declared columns on this dataset: ${current.experiment.available_dataset_columns.join(", ")}.`
                : " This dataset has no declared independent-variable columns."}
            </p>

            <h4>Dependent measurements</h4>
            <p>
              Current mapping:{" "}
              {current.experiment.alias_mapping_revision_number === null
                ? "none yet"
                : `revision ${current.experiment.alias_mapping_revision_number}${
                    current.experiment.mapping_is_stale ? " -- a newer revision now exists" : ""
                  }`}
              {" — "}
              <RouterLink
                to={`/projects/${projectId}/studies/${studyId}/datasets/time-series/${current.experiment.time_series_dataset_id}/alias-mapping/${current.arm.model_id}`}
              >
                Open alias mapping
              </RouterLink>
            </p>
            {current.experiment.mapping_is_stale && (
              <button
                type="button"
                className="secondary-button"
                onClick={() =>
                  getCurrentAliasMapping(
                    projectId,
                    studyId,
                    current.experiment.time_series_dataset_id,
                    current.arm.model_id,
                  ).then((mapping) =>
                    onRepinMapping(current.experiment.id, mapping.revision_number),
                  )
                }
              >
                Re-pin to the current mapping
              </button>
            )}

            <h4>Initial-conditions dataset</h4>
            <p className="screen-subtitle">
              Optional. Entirely separate from the calibration-target dataset above -- e.g. one
              cell type&apos;s own protein/metabolite abundance profile, giving a
              value_source=INITIAL_CONDITIONS_DATASET binding something real to read from
              (docs/36). Pinning a different initial-conditions dataset per experiment is how
              one model can be evaluated against different cell types.
            </p>
            {current.experiment.initial_conditions_dataset_id === null ? (
              <p>
                <select
                  aria-label="Choose an initial-conditions dataset"
                  value={selectedIcDatasetId}
                  onChange={(event) => setSelectedIcDatasetId(event.target.value)}
                >
                  <option value="">Choose a dataset…</option>
                  {initialConditionsDatasets.map((dataset) => (
                    <option key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </option>
                  ))}
                </select>{" "}
                <button
                  type="button"
                  className="secondary-button"
                  disabled={!selectedIcDatasetId}
                  onClick={() => {
                    if (selectedIcDatasetId) {
                      onSetInitialConditionsDataset(current.experiment.id, selectedIcDatasetId);
                      setSelectedIcDatasetId("");
                    }
                  }}
                >
                  Pin dataset
                </button>
              </p>
            ) : (
              <>
                <p>
                  {current.experiment.initial_conditions_dataset_name} — mapping:{" "}
                  {current.experiment.initial_conditions_alias_mapping_revision_number === null
                    ? "none yet"
                    : `revision ${current.experiment.initial_conditions_alias_mapping_revision_number}${
                        current.experiment.initial_conditions_mapping_is_stale
                          ? " -- a newer revision now exists"
                          : ""
                      }`}
                  {" — "}
                  <RouterLink
                    to={`/projects/${projectId}/studies/${studyId}/datasets/initial-conditions/${current.experiment.initial_conditions_dataset_id}/alias-mapping/${current.arm.model_id}`}
                  >
                    Open alias mapping
                  </RouterLink>
                </p>
                {current.experiment.initial_conditions_mapping_is_stale && (
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() =>
                      getCurrentInitialConditionsAliasMapping(
                        projectId,
                        studyId,
                        current.experiment.initial_conditions_dataset_id as string,
                        current.arm.model_id,
                      ).then((mapping) =>
                        onRepinInitialConditionsMapping(
                          current.experiment.id,
                          mapping.revision_number,
                        ),
                      )
                    }
                  >
                    Re-pin to the current mapping
                  </button>
                )}{" "}
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onSetInitialConditionsDataset(current.experiment.id, null)}
                >
                  Unpin dataset
                </button>
              </>
            )}

            <h4>Initial conditions, interventions &amp; experiment-specific settings</h4>
            <p className="screen-subtitle">
              Every binding states its own explicit model meaning and is validated server-side
              against the model&apos;s own real species/parameter catalog where one exists and is
              relevant -- a 422 names a target confirmed absent, or confirmed a DERIVED
              (assignment-rule) parameter, which is never an independent target (docs/31). No
              catalog yet for a relevant kind means the target stays curator-declared, never
              silently rejected.
            </p>
            <table className="module-sets-table">
              <thead>
                <tr>
                  <th scope="col">Model meaning</th>
                  <th scope="col">Component</th>
                  <th scope="col">Value source</th>
                  <th scope="col">Value</th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {current.experiment.variable_bindings.map((binding) => (
                  <tr key={binding.id}>
                    <td>{binding.model_meaning}</td>
                    <td>{binding.target_component_id}</td>
                    <td>{binding.value_source}</td>
                    <td
                      title={
                        [
                          binding.value_source === "CONSTANT" ? binding.constant_value : null,
                          binding.intervention_time,
                        ]
                          .filter((v): v is string => v !== null)
                          .map((v) => fullPrecisionTitle(v))
                          .join(" / ") || undefined
                      }
                    >
                      {binding.value_source === "CONSTANT"
                        ? `${binding.constant_value !== null ? formatScientific(binding.constant_value) : ""} ${
                            binding.constant_unit ?? ""
                          }`.trim()
                        : `column: ${binding.source_column_name ?? ""}`}
                      {binding.intervention_time !== null
                        ? ` @ t=${formatScientific(binding.intervention_time)}`
                        : ""}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => onRemoveBinding(binding.id)}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              <select
                value={bindingMeaning}
                onChange={(event) =>
                  setBindingMeaning(event.target.value as CalibrationBindingModelMeaning)
                }
              >
                <option value="INITIAL_VALUE">Initial value (real species)</option>
                <option value="PARAMETER_OVERRIDE">Parameter override (real parameter)</option>
                <option value="INTERVENTION">Intervention (species or parameter)</option>
              </select>{" "}
              <input
                type="text"
                placeholder={
                  bindingMeaning === "PARAMETER_OVERRIDE" ? "parameter name" : "species id"
                }
                value={bindingComponent}
                onChange={(event) => setBindingComponent(event.target.value)}
              />{" "}
              <select
                value={bindingValueSource}
                onChange={(event) =>
                  setBindingValueSource(event.target.value as CalibrationBindingValueSource)
                }
              >
                <option value="CONSTANT">Constant value</option>
                <option value="DATASET_COLUMN">Dataset column</option>
                <option value="INITIAL_CONDITIONS_DATASET">Initial-conditions dataset</option>
              </select>{" "}
              {bindingValueSource === "CONSTANT" ? (
                <>
                  <input
                    type="text"
                    placeholder="value"
                    value={bindingConstantValue}
                    onChange={(event) => setBindingConstantValue(event.target.value)}
                  />{" "}
                  <input
                    type="text"
                    placeholder="unit (optional)"
                    value={bindingConstantUnit}
                    onChange={(event) => setBindingConstantUnit(event.target.value)}
                  />{" "}
                </>
              ) : (
                <select
                  value={bindingSourceColumn}
                  onChange={(event) => setBindingSourceColumn(event.target.value)}
                >
                  <option value="">column…</option>
                  {(bindingValueSource === "INITIAL_CONDITIONS_DATASET"
                    ? current.experiment.available_initial_conditions_columns
                    : current.experiment.available_dataset_columns
                  ).map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              )}{" "}
              {bindingMeaning === "INTERVENTION" ? (
                <input
                  type="text"
                  placeholder="intervention time"
                  value={bindingInterventionTime}
                  onChange={(event) => setBindingInterventionTime(event.target.value)}
                />
              ) : null}{" "}
              <button
                type="button"
                className="secondary-button"
                disabled={
                  !bindingComponent ||
                  (bindingValueSource === "CONSTANT" ? !bindingConstantValue : !bindingSourceColumn) ||
                  (bindingMeaning === "INTERVENTION" && !bindingInterventionTime)
                }
                onClick={() => {
                  onAddBinding(
                    current.experiment.id,
                    bindingMeaning,
                    bindingComponent,
                    bindingValueSource,
                    bindingConstantValue,
                    bindingConstantUnit,
                    bindingSourceColumn,
                    "manual",
                    bindingInterventionTime,
                  );
                  setBindingComponent("");
                  setBindingConstantValue("");
                  setBindingConstantUnit("");
                  setBindingSourceColumn("");
                  setBindingInterventionTime("");
                }}
              >
                Add binding
              </button>
            </p>

            <h4>Objective weighting / error assumption</h4>
            <p className="field-hint">
              Unweighted counts every residual equally (ordinary least squares) -- a real,
              named policy choice, never a silent default. Inverse-variance scales each
              output&apos;s own residuals by 1/sigma², using that output&apos;s own declared
              uncertainty below; every output of this experiment must have a known
              (measured or assumed) uncertainty before this policy can pass review.
            </p>
            <p>
              <select
                value={current.experiment.objective_weighting}
                onChange={(event) =>
                  onSetObjectiveWeighting(
                    current.experiment.id,
                    event.target.value as CalibrationExperimentItem["objective_weighting"],
                    weightingNotes,
                  )
                }
              >
                <option value="UNWEIGHTED">Unweighted (ordinary least squares)</option>
                <option value="INVERSE_VARIANCE">Inverse-variance (scaled by declared uncertainty)</option>
              </select>
            </p>
            <p>
              <textarea
                placeholder="General notes on this experiment's own weighting/error assumptions (optional, curator-declared text)."
                defaultValue={current.experiment.weighting_notes ?? ""}
                onChange={(event) => setWeightingNotes(event.target.value)}
                onBlur={() =>
                  onSetObjectiveWeighting(
                    current.experiment.id,
                    current.experiment.objective_weighting,
                    weightingNotes,
                  )
                }
              />
            </p>

            <h4>Per-output uncertainty &amp; relative weight</h4>
            <p className="field-hint">
              Measured uses this output&apos;s own already-computed, per-row uncertainty from
              the uploaded workbook. User-assumed is a single curator-typed value applied to
              every observation of this output in this experiment -- never fabricated, never
              inferred from replicates. Unknown is a real, disclosed state, never silently
              treated as if uncertainty were known. The relative weight is independent of
              uncertainty scaling and multiplies with it -- combining both is disclosed as a
              finding on Screen 3, never applied silently.
            </p>
            {current.experiment.output_weightings.length > 0 && (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Output</th>
                    <th>Uncertainty source</th>
                    <th>Statistic</th>
                    <th>Assumed sigma</th>
                    <th>Relative weight</th>
                    <th>Provenance</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {current.experiment.output_weightings.map((weighting) => (
                    <tr key={weighting.id}>
                      <td>{weighting.output_column_name}</td>
                      <td>{weighting.uncertainty_source}</td>
                      <td>{weighting.effective_statistic_kind ?? "—"}</td>
                      <td
                        title={
                          weighting.assumed_sigma_value
                            ? fullPrecisionTitle(weighting.assumed_sigma_value)
                            : undefined
                        }
                      >
                        {weighting.assumed_sigma_value
                          ? `${formatScientific(weighting.assumed_sigma_value)}${
                              weighting.assumed_sigma_unit ? ` ${weighting.assumed_sigma_unit}` : ""
                            }`
                          : "—"}
                      </td>
                      <td title={fullPrecisionTitle(weighting.relative_output_weight)}>
                        {formatScientific(weighting.relative_output_weight)}
                      </td>
                      <td>{weighting.provenance_note ?? "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => onRemoveOutputWeighting(weighting.id)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p>
              <select
                value={outputColumnName}
                onChange={(event) => setOutputColumnName(event.target.value)}
              >
                <option value="">output…</option>
                {current.experiment.available_output_columns.map((column) => (
                  <option key={column} value={column}>
                    {column}
                  </option>
                ))}
              </select>{" "}
              <select
                value={outputUncertaintySource}
                onChange={(event) =>
                  setOutputUncertaintySource(
                    event.target.value as OutputWeightingItem["uncertainty_source"],
                  )
                }
              >
                <option value="UNKNOWN">Unknown</option>
                <option
                  value="MEASURED"
                  disabled={
                    !current.experiment.outputs_with_measured_uncertainty.includes(
                      outputColumnName,
                    )
                  }
                >
                  Measured (from workbook)
                </option>
                <option value="USER_ASSUMED">User-assumed</option>
              </select>{" "}
              {outputUncertaintySource === "USER_ASSUMED" && (
                <>
                  <input
                    type="text"
                    placeholder="sigma value"
                    value={outputSigmaValue}
                    onChange={(event) => setOutputSigmaValue(event.target.value)}
                  />{" "}
                  <select
                    value={outputSigmaStatisticKind ?? ""}
                    onChange={(event) =>
                      setOutputSigmaStatisticKind(
                        event.target.value as OutputWeightingItem["assumed_sigma_statistic_kind"],
                      )
                    }
                  >
                    <option value="">statistic…</option>
                    <option value="STANDARD_DEVIATION">Standard deviation</option>
                    <option value="VARIANCE">Variance</option>
                    <option value="STANDARD_ERROR">Standard error</option>
                  </select>{" "}
                  <input
                    type="text"
                    placeholder="sigma unit"
                    value={outputSigmaUnit}
                    onChange={(event) => setOutputSigmaUnit(event.target.value)}
                  />{" "}
                </>
              )}
              <input
                type="text"
                placeholder="relative weight (default 1)"
                value={outputRelativeWeight}
                onChange={(event) => setOutputRelativeWeight(event.target.value)}
              />{" "}
              <input
                type="text"
                placeholder="provenance note (optional)"
                value={outputProvenanceNote}
                onChange={(event) => setOutputProvenanceNote(event.target.value)}
              />{" "}
              <button
                type="button"
                className="secondary-button"
                disabled={
                  !outputColumnName ||
                  (outputUncertaintySource === "USER_ASSUMED" &&
                    (!outputSigmaValue || !outputSigmaStatisticKind))
                }
                onClick={() => {
                  onSetOutputWeighting(
                    current.experiment.id,
                    outputColumnName,
                    outputUncertaintySource,
                    outputSigmaValue,
                    outputSigmaUnit,
                    outputSigmaStatisticKind,
                    outputRelativeWeight,
                    outputProvenanceNote,
                  );
                  setOutputColumnName("");
                  setOutputUncertaintySource("UNKNOWN");
                  setOutputSigmaValue("");
                  setOutputSigmaUnit("");
                  setOutputSigmaStatisticKind("");
                  setOutputRelativeWeight("1");
                  setOutputProvenanceNote("");
                }}
              >
                Save output weighting
              </button>
            </p>
          </>
        )}
      </section>

      <section className="card" aria-label="Parameter roles">
        <h2>Parameter roles</h2>
        <p className="screen-subtitle">
          Collected even for a single arm -- which parameters are free to fit, which are fixed,
          and within what bounds. Validated server-side against each covering arm&apos;s own
          real, whole-model parameter catalog where one is AVAILABLE (never against a DERIVED,
          assignment-rule parameter); a parameter name declared before that model&apos;s own
          catalog existed stays curator-declared and unvalidated, shown honestly below, and is
          never silently re-checked against a catalog captured later (docs/31).
        </p>

        <table className="module-sets-table">
          <thead>
            <tr>
              <th scope="col">Parameter</th>
              <th scope="col">Role</th>
              <th scope="col">Bounds / coefficients</th>
              <th scope="col">Arms</th>
              <th scope="col">Catalog</th>
              <th scope="col"></th>
            </tr>
          </thead>
          <tbody>
            {job.parameter_roles.map((role) => (
              <tr key={role.id}>
                <td>{role.parameter_name}</td>
                <td>{role.role}</td>
                <td
                  title={
                    [role.fixed_value, role.coefficient_a, role.coefficient_b, role.lower_bound, role.upper_bound]
                      .filter((v): v is string => v !== null)
                      .map((v) => fullPrecisionTitle(v))
                      .join(" / ") || undefined
                  }
                >
                  {role.role === "FIXED" && `= ${formatScientific(role.fixed_value)}`}
                  {role.role === "EXACT_AFFINE_LINK" &&
                    `${role.reference_parameter_name} * ${
                      role.coefficient_a !== null ? formatScientific(role.coefficient_a) : "?"
                    } + ${role.coefficient_b !== null ? formatScientific(role.coefficient_b) : "?"}`}
                  {(role.role === "EXACT_EQUALITY" || role.role === "SOFT_PRIOR_LINK") &&
                    `= ${role.reference_parameter_name}`}
                  {role.role === "MODEL_SPECIFIC" &&
                    (role.lower_bound || role.upper_bound
                      ? `[${role.lower_bound !== null ? formatScientific(role.lower_bound) : "-inf"}, ${
                          role.upper_bound !== null ? formatScientific(role.upper_bound) : "inf"
                        }]`
                      : "free")}
                </td>
                <td>{role.arm_ids.length}</td>
                <td>{role.catalog_validated ? "validated" : "curator-declared"}</td>
                <td>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => onRemoveParameterRole(role.id)}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3>Add a parameter role</h3>
        <p>
          <input
            type="text"
            placeholder="parameter name"
            value={roleName}
            onChange={(event) => setRoleName(event.target.value)}
          />{" "}
          <select
            value={roleKind}
            onChange={(event) => setRoleKind(event.target.value as CalibrationParameterRoleKind)}
          >
            <option value="MODEL_SPECIFIC">Model-specific (free to fit)</option>
            <option value="FIXED">Fixed</option>
            {job.arms.length >= 2 && (
              <>
                <option value="EXACT_EQUALITY">Exact equality (shared across arms)</option>
                <option value="EXACT_AFFINE_LINK">Exact affine link</option>
                <option value="SOFT_PRIOR_LINK">Soft prior link</option>
              </>
            )}
          </select>
        </p>
        <p>
          Covers arms:{" "}
          {job.arms.map((arm) => (
            <label key={arm.id} style={{ marginRight: "1em" }}>
              <input
                type="checkbox"
                checked={roleArmIds.includes(arm.id)}
                onChange={(event) =>
                  setRoleArmIds((prev) =>
                    event.target.checked ? [...prev, arm.id] : prev.filter((id) => id !== arm.id),
                  )
                }
              />{" "}
              {arm.model_name}
            </label>
          ))}
        </p>
        {roleKind === "FIXED" && (
          <p>
            <input
              type="text"
              placeholder="fixed value"
              value={roleFixedValue}
              onChange={(event) => setRoleFixedValue(event.target.value)}
            />
          </p>
        )}
        {roleKind === "MODEL_SPECIFIC" && (
          <p>
            <input
              type="text"
              placeholder="lower bound (optional)"
              value={roleLowerBound}
              onChange={(event) => setRoleLowerBound(event.target.value)}
            />{" "}
            <input
              type="text"
              placeholder="upper bound (optional)"
              value={roleUpperBound}
              onChange={(event) => setRoleUpperBound(event.target.value)}
            />{" "}
            <input
              type="text"
              placeholder="unit (optional)"
              value={roleUnit}
              onChange={(event) => setRoleUnit(event.target.value)}
            />
          </p>
        )}
        {isLinkRole && (
          <p>
            <select
              value={roleReferenceArmId}
              onChange={(event) => setRoleReferenceArmId(event.target.value)}
            >
              <option value="">Reference arm…</option>
              {job.arms.map((arm) => (
                <option key={arm.id} value={arm.id}>
                  {arm.model_name}
                </option>
              ))}
            </select>{" "}
            <input
              type="text"
              placeholder="reference parameter name"
              value={roleReferenceParamName}
              onChange={(event) => setRoleReferenceParamName(event.target.value)}
            />
            {roleKind === "EXACT_AFFINE_LINK" && (
              <>
                {" "}
                <input
                  type="text"
                  placeholder="coefficient a (fixed)"
                  value={coefficientA}
                  onChange={(event) => setCoefficientA(event.target.value)}
                />{" "}
                <input
                  type="text"
                  placeholder="coefficient b (fixed)"
                  value={coefficientB}
                  onChange={(event) => setCoefficientB(event.target.value)}
                />
              </>
            )}
          </p>
        )}
        <button
          type="button"
          className="secondary-button"
          disabled={!roleName || roleArmIds.length === 0}
          onClick={() => {
            onAddParameterRole(
              roleName,
              roleKind,
              roleArmIds,
              roleFixedValue,
              roleLowerBound,
              roleUpperBound,
              roleUnit,
              roleReferenceArmId,
              roleReferenceParamName,
              coefficientA,
              true,
              coefficientB,
              true,
            );
            setRoleName("");
            setRoleArmIds([]);
            setRoleFixedValue("");
            setRoleLowerBound("");
            setRoleUpperBound("");
            setRoleUnit("");
            setRoleReferenceArmId("");
            setRoleReferenceParamName("");
            setCoefficientA("");
            setCoefficientB("");
          }}
        >
          Add parameter role
        </button>
      </section>
    </>
  );
}

// --- Screen 3: Review & readiness -----------------------------------------------------------

interface ReviewStepProps {
  job: CalibrationJobDetail;
  reviewState: LoadState<CalibrationReviewResult>;
  onRefresh: () => void;
  onCompleteReview: () => void;
  projectId: string;
  studyId: string;
  jobId: string;
}

function armLabel(job: CalibrationJobDetail, armId: string): string {
  return job.arms.find((a) => a.id === armId)?.model_name ?? armId;
}

function RevisionsPanel({
  projectId,
  studyId,
  jobId,
  job,
}: {
  projectId: string;
  studyId: string;
  jobId: string;
  job: CalibrationJobDetail;
}) {
  const [revisions, setRevisions] = useState<CalibrationJobRevisionSummary[]>([]);
  const [selected, setSelected] = useState<CalibrationJobRevisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    listCalibrationJobRevisions(projectId, studyId, jobId)
      .then(setRevisions)
      .catch((err: unknown) => setError(errorMessage(err)));
  }, [projectId, studyId, jobId]);

  useEffect(() => {
    reload();
    setSelected(null);
  }, [reload, job.status, job.edit_version]);

  return (
    <>
      <h3>Revisions</h3>
      <p className="screen-subtitle">
        An immutable, versioned snapshot of this job&apos;s own complete configuration, captured
        each time &quot;Complete review&quot; succeeds. A later draft edit never changes an
        earlier revision (docs/31).
      </p>
      {error && (
        <p className="status-message error" role="alert">
          {error}
        </p>
      )}
      {revisions.length === 0 && (
        <p className="status-message">No revision has been captured yet.</p>
      )}
      <ul>
        {revisions.map((revision) => (
          <li key={revision.revision_number}>
            Revision {revision.revision_number} — {revision.arm_count} arm(s),{" "}
            {revision.finding_count} finding(s) — captured{" "}
            {new Date(revision.created_at).toLocaleString()}{" "}
            <button
              type="button"
              className="secondary-button"
              onClick={() =>
                getCalibrationJobRevision(projectId, studyId, jobId, revision.revision_number).then(
                  setSelected,
                )
              }
            >
              View snapshot
            </button>
          </li>
        ))}
      </ul>
      {selected && (
        <>
          <pre className="time-series-preview">
            {JSON.stringify(selected.snapshot, null, 2)}
          </pre>
          <ScenarioEvaluationPanel
            projectId={projectId}
            studyId={studyId}
            jobId={jobId}
            revisionNumber={selected.revision_number}
            snapshot={selected.snapshot}
          />
        </>
      )}
    </>
  );
}

const SCENARIO_EVALUATION_POLL_INTERVAL_MS = 3000;

/** "Evaluate scenario" (Whole-Model Experimental-Scenario Evaluation increment, docs/33):
 * given one saved revision's own experiment, explicit candidate parameter values, and an
 * optional condition, submit a background prediction run against Agent 3 directly -- never
 * calibration (fitting), which stays unavailable regardless (see Execution capability above).
 * There is no Figma reference for this screen -- this layout follows
 * ModuleSetMemberExecutionScreen's own established submit/poll/display structure. */
function ScenarioEvaluationPanel({
  projectId,
  studyId,
  jobId,
  revisionNumber,
  snapshot,
}: {
  projectId: string;
  studyId: string;
  jobId: string;
  revisionNumber: number;
  snapshot: Record<string, any>;
}) {
  const experiments: { id: string; dataset_label: string }[] = (snapshot.arms ?? []).flatMap(
    (arm: any) =>
      (arm.experiments ?? []).map((experiment: any) => ({
        id: experiment.id,
        dataset_label: `${arm.model_name} / experiment ${experiment.id.slice(0, 8)}`,
      })),
  );

  const [experimentId, setExperimentId] = useState(experiments[0]?.id ?? "");
  const [conditionId, setConditionId] = useState("");
  const [candidateValuesText, setCandidateValuesText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [runs, setRuns] = useState<ScenarioEvaluationRunItem[]>([]);
  const [runsError, setRunsError] = useState<string | null>(null);

  const reloadRuns = useCallback(() => {
    if (!experimentId) return;
    listCalibrationScenarioEvaluations(projectId, studyId, jobId, revisionNumber, experimentId)
      .then(setRuns)
      .catch((err: unknown) => setRunsError(errorMessage(err)));
  }, [projectId, studyId, jobId, revisionNumber, experimentId]);

  useEffect(() => {
    setRuns([]);
    setRunsError(null);
    reloadRuns();
  }, [reloadRuns]);

  // Poll any non-terminal run until it reaches a terminal status -- the background worker
  // (scripts/calibration_scenario_evaluation_worker.py) runs out-of-process.
  useEffect(() => {
    const activeRuns = runs.filter((run) => run.status === "PENDING" || run.status === "RUNNING");
    if (activeRuns.length === 0) return;
    const interval = window.setInterval(() => {
      Promise.all(
        activeRuns.map((run) =>
          getCalibrationScenarioEvaluation(
            projectId,
            studyId,
            jobId,
            revisionNumber,
            experimentId,
            run.id,
          ),
        ),
      )
        .then((refreshed) => {
          setRuns((prev) => {
            const byId = new Map(refreshed.map((run) => [run.id, run]));
            return prev.map((run) => byId.get(run.id) ?? run);
          });
        })
        .catch(() => {
          // A transient poll failure is not surfaced as a page-level error -- the next poll,
          // or a manual reload, simply tries again.
        });
    }, SCENARIO_EVALUATION_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [runs, projectId, studyId, jobId, revisionNumber, experimentId]);

  function parseCandidateValues(): Record<string, string> {
    const result: Record<string, string> = {};
    for (const line of candidateValuesText.split(/[\n,]/)) {
      const [name, value] = line.split("=").map((part) => part.trim());
      if (name && value) result[name] = value;
    }
    return result;
  }

  function handleSubmit() {
    if (!experimentId) return;
    setSubmitError(null);
    setSubmitting(true);
    submitCalibrationScenarioEvaluation(projectId, studyId, jobId, revisionNumber, experimentId, {
      condition_id: conditionId.trim() === "" ? null : conditionId.trim(),
      candidate_parameter_values: parseCandidateValues(),
    })
      .then(() => reloadRuns())
      .catch((err: unknown) => {
        if (err instanceof ApiRequestError && err.status === 409) {
          setSubmitError("An identical scenario evaluation is already active.");
          reloadRuns();
          return;
        }
        setSubmitError(errorMessage(err));
      })
      .finally(() => setSubmitting(false));
  }

  if (experiments.length === 0) {
    return null;
  }

  return (
    <section aria-label="Evaluate scenario" className="time-series-preview">
      <h4>Evaluate scenario</h4>
      <p className="screen-subtitle">
        Given explicit candidate parameter values, predict this experiment&apos;s own trajectory
        against the model pinned in this revision -- prediction only, never fitting.
      </p>
      <p>
        <select value={experimentId} onChange={(event) => setExperimentId(event.target.value)}>
          {experiments.map((experiment) => (
            <option key={experiment.id} value={experiment.id}>
              {experiment.dataset_label}
            </option>
          ))}
        </select>{" "}
        <input
          type="text"
          placeholder="condition_id (optional)"
          value={conditionId}
          onChange={(event) => setConditionId(event.target.value)}
        />
      </p>
      <p>
        <textarea
          placeholder={"candidate parameter values, one per line, e.g.\nk1=0.5\nk2=2.0"}
          value={candidateValuesText}
          onChange={(event) => setCandidateValuesText(event.target.value)}
          rows={3}
        />
      </p>
      <button
        type="button"
        className="primary-button"
        disabled={submitting || !experimentId}
        onClick={handleSubmit}
      >
        {submitting ? "Submitting…" : "Evaluate scenario"}
      </button>{" "}
      <button type="button" className="secondary-button" onClick={reloadRuns}>
        Refresh
      </button>
      {submitError && (
        <p className="status-message error" role="alert">
          {submitError}
        </p>
      )}
      {runsError && (
        <p className="status-message error" role="alert">
          {runsError}
        </p>
      )}
      <h5>Runs</h5>
      {runs.length === 0 && <p className="status-message">No evaluation has been submitted yet.</p>}
      <ul>
        {runs.map((run) => (
          <li key={run.id}>
            {formatRunStatus(run.status)}
            {run.evaluation_status && ` — ${run.evaluation_status}`}
            {run.error_summary && ` — ${run.error_summary}`}
            {run.validation_errors && run.validation_errors.length > 0 && (
              <ul>
                {run.validation_errors.map((message, index) => (
                  <li key={index}>{message}</li>
                ))}
              </ul>
            )}
            {run.observed_vs_predicted && run.observed_vs_predicted.length > 0 && (
              <table>
                <thead>
                  <tr>
                    <th scope="col">Output</th>
                    <th scope="col">Row</th>
                    <th scope="col">Observed</th>
                    <th scope="col">Predicted</th>
                    <th scope="col">Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {run.observed_vs_predicted.map((row, index) => (
                    <tr key={index}>
                      <td>{row.column_name ?? row.output_id}</td>
                      <td>{row.row_id.slice(0, 8)}</td>
                      <td title={row.observed !== null ? fullPrecisionTitle(row.observed) : undefined}>
                        {row.observed !== null ? formatScientific(row.observed) : "—"}
                      </td>
                      <td title={fullPrecisionTitle(row.predicted)}>
                        {formatScientific(row.predicted)}
                      </td>
                      <td>{row.unit ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ReviewStep({
  job,
  reviewState,
  onRefresh,
  onCompleteReview,
  projectId,
  studyId,
  jobId,
}: ReviewStepProps) {
  return (
    <section className="card" aria-label="Review and readiness">
      <h2>Review &amp; readiness</h2>
      <p className="screen-subtitle">
        A summary only -- no new required input here. Configuration completeness and execution
        capability are reported separately and never conflated (docs/29 §5 rule 5).
      </p>

      <button type="button" className="secondary-button" onClick={onRefresh}>
        Refresh
      </button>

      {reviewState.status === "loading" && <p className="status-message">Loading review…</p>}
      {reviewState.status === "error" && (
        <p className="status-message error" role="alert">
          Couldn&apos;t load the review: {reviewState.message}
        </p>
      )}

      {reviewState.status === "ready" && (
        <>
          <h3>Arms</h3>
          {job.arms.map((arm) => (
            <div key={arm.id} className="time-series-preview">
              <h4>{arm.model_name}</h4>
              <ul>
                {arm.experiments.map((experiment) => (
                  <li key={experiment.id}>
                    {experiment.dataset_name} — {experiment.role} —{" "}
                    {experiment.alias_mapping_revision_number === null
                      ? "not mapped"
                      : `revision ${experiment.alias_mapping_revision_number}`}{" "}
                    — objective: {experiment.objective_weighting} —{" "}
                    {experiment.variable_bindings.length} variable binding(s)
                    {experiment.output_weightings.length > 0 && (
                      <ul>
                        {experiment.output_weightings.map((weighting) => (
                          <li
                            key={weighting.id}
                            title={
                              [
                                weighting.assumed_sigma_value,
                                weighting.relative_output_weight !== "1"
                                  ? weighting.relative_output_weight
                                  : null,
                              ]
                                .filter((v): v is string => v !== null)
                                .map((v) => fullPrecisionTitle(v))
                                .join(" / ") || undefined
                            }
                          >
                            {weighting.output_column_name}: {weighting.uncertainty_source}
                            {weighting.effective_statistic_kind &&
                              ` (${weighting.effective_statistic_kind})`}
                            {weighting.assumed_sigma_value &&
                              ` (sigma ${formatScientific(weighting.assumed_sigma_value)}${
                                weighting.assumed_sigma_unit ? ` ${weighting.assumed_sigma_unit}` : ""
                              })`}
                            {weighting.relative_output_weight !== "1" &&
                              ` — relative weight ${formatScientific(weighting.relative_output_weight)}`}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          <h3>Parameter roles</h3>
          <ul>
            {job.parameter_roles.map((role) => (
              <li key={role.id}>
                {role.parameter_name} — {role.role} — covers{" "}
                {role.arm_ids.map((id) => armLabel(job, id)).join(", ")} —{" "}
                {role.catalog_validated ? "catalog-validated" : "curator-declared (no catalog yet)"}
              </li>
            ))}
          </ul>

          <h3>Findings ({reviewState.value.findings.length})</h3>
          {reviewState.value.findings.length === 0 && (
            <p className="status-message">No findings -- vacuously satisfied.</p>
          )}
          <ul className="time-series-findings-list">
            {reviewState.value.findings.map((finding, index) => (
              <li key={index} className={finding.severity === "ERROR" ? "error" : undefined}>
                [{finding.severity}] {finding.category}: {finding.message}
                {finding.involved_arm_ids.length > 0 &&
                  ` (arms: ${finding.involved_arm_ids.map((id) => armLabel(job, id)).join(", ")})`}
              </li>
            ))}
          </ul>

          <h3>Execution capability</h3>
          <p className="status-message">
            {reviewState.value.execution_capability.available
              ? "Executable."
              : `Not yet execution-ready: ${reviewState.value.execution_capability.reason ?? ""}`}
          </p>

          <p>
            Status: {job.status}
            {job.reviewed_at ? ` (reviewed at ${new Date(job.reviewed_at).toLocaleString()})` : ""}
          </p>
          <button type="button" className="primary-button" onClick={onCompleteReview}>
            Complete review
          </button>

          <RevisionsPanel projectId={projectId} studyId={studyId} jobId={jobId} job={job} />
        </>
      )}
    </section>
  );
}
