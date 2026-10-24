export type ModelTab = "overview" | "antimony" | "history";

interface ModelTabsProps {
  activeTab: ModelTab;
  onSelectTab: (tab: ModelTab) => void;
  /** Whether this model has a captured species catalog at all (and therefore real,
   * durably-available Antimony source to show) -- the "Antimony" tab renders disabled,
   * never silently dropped, when there is nothing to show. */
  antimonySourceAvailable: boolean;
}

/** Figma's own tab order, between the three real tabs: structural/scientific content this
 * system never persists for a `Model` at all beyond its species/parameter/compartment catalog
 * and (Whole-Model Antimony Import increment, docs/34) its own read-only Antimony source --
 * no per-reaction, per-rule, or module listing is durably available here. Each renders
 * disabled, never silently dropped. */
const DISABLED_TABS = ["Compartments", "Species", "Reactions", "Parameters", "Modules"];

/** "Model context tabs" on "05 — Model Overview" (Figma node 46:564).
 * "Overview", "Antimony", and "History" are the tabs with real, durably-available content;
 * all three live on the same route (no sub-navigation needed), so this is plain component
 * state, not a router concern. */
export function ModelTabs({ activeTab, onSelectTab, antimonySourceAvailable }: ModelTabsProps) {
  return (
    <div className="model-tabs" role="tablist" aria-label="This model">
      <span className="model-tabs-label">This model</span>
      <button
        type="button"
        role="tab"
        aria-selected={activeTab === "overview"}
        className={activeTab === "overview" ? "model-tab active" : "model-tab"}
        onClick={() => onSelectTab("overview")}
      >
        Overview
      </button>
      {DISABLED_TABS.slice(0, 2).map((label) => (
        <span
          key={label}
          className="model-tab disabled"
          aria-disabled="true"
          title="Not available in this increment"
        >
          {label}
        </span>
      ))}
      {antimonySourceAvailable ? (
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "antimony"}
          className={activeTab === "antimony" ? "model-tab active" : "model-tab"}
          onClick={() => onSelectTab("antimony")}
        >
          Antimony
        </button>
      ) : (
        <span
          className="model-tab disabled"
          aria-disabled="true"
          title="No Antimony source is available for this model"
        >
          Antimony
        </span>
      )}
      {DISABLED_TABS.slice(2).map((label) => (
        <span
          key={label}
          className="model-tab disabled"
          aria-disabled="true"
          title="Not available in this increment"
        >
          {label}
        </span>
      ))}
      <button
        type="button"
        role="tab"
        aria-selected={activeTab === "history"}
        className={activeTab === "history" ? "model-tab active" : "model-tab"}
        onClick={() => onSelectTab("history")}
      >
        History
      </button>
    </div>
  );
}
