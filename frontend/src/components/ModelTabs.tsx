export type ModelTab = "overview" | "history";

interface ModelTabsProps {
  activeTab: ModelTab;
  onSelectTab: (tab: ModelTab) => void;
}

/** Figma's own tab order, between the two real tabs: structural/scientific
 * content this system never persists for a `Model` at all (no species,
 * reaction, parameter, or Antimony-text content, and no durably-available,
 * correctly-scoped module listing is wired up here -- see
 * docs/19_model_overview_increment.md's "durability audit" for why
 * "Modules" is deferred too, even though `ModelModule` rows themselves are
 * technically durable). Each renders disabled, never silently dropped. */
const DISABLED_TABS = ["Compartments", "Species", "Reactions", "Parameters", "Antimony", "Modules"];

/** "Model context tabs" on "05 — Model Overview" (Figma node 46:564).
 * "Overview" and "History" are the only tabs with real, durably-available
 * content; both live on the same route (no sub-navigation needed), so this
 * is plain component state, not a router concern. */
export function ModelTabs({ activeTab, onSelectTab }: ModelTabsProps) {
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
      {DISABLED_TABS.map((label) => (
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
