import { useEffect, useMemo, useState } from "react";
import type { DatasetSummary } from "../api";

const KIND_LABELS: Record<string, string> = {
  run_plan: "plan",
  partition_manifest: "manifest",
  partition_chunk: "partition",
  preview: "preview",
  published_dataset: "dataset",
  published_manifest: "manifest",
  merge_report: "merge",
  worker_fragment: "worker",
  run_union: "all",
  unknown: "artifact",
};

function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

const OPEN_GROUPS_KEY = "viewer-open-groups";

function loadOpenGroups(): Set<string> {
  try {
    const raw = localStorage.getItem(OPEN_GROUPS_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

interface Group {
  phase: string;
  runs: Map<string, DatasetSummary[]>;
}

function groupDatasets(datasets: DatasetSummary[]): Group[] {
  const groups = new Map<string, Group>();
  for (const dataset of datasets) {
    const phase = dataset.phase ?? "(unclassified)";
    let group = groups.get(phase);
    if (!group) {
      group = { phase, runs: new Map() };
      groups.set(phase, group);
    }
    const run = dataset.run_id ?? "(no run)";
    const existing = group.runs.get(run);
    if (existing) {
      existing.push(dataset);
    } else {
      group.runs.set(run, [dataset]);
    }
  }
  return [...groups.values()].sort((a, b) => a.phase.localeCompare(b.phase));
}

interface Props {
  datasets: DatasetSummary[];
  documents: DatasetSummary[];
  selectedId: string | null;
  onSelect: (dataset: DatasetSummary) => void;
  onRefresh: () => void;
  collapsed: boolean;
}

export default function ArtifactSidebar({
  datasets,
  documents,
  selectedId,
  onSelect,
  onRefresh,
  collapsed,
}: Props) {
  const [query, setQuery] = useState("");
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => loadOpenGroups());

  useEffect(() => {
    localStorage.setItem(OPEN_GROUPS_KEY, JSON.stringify([...openGroups]));
  }, [openGroups]);

  const needle = query.trim().toLowerCase();
  const matches = (item: DatasetSummary) =>
    needle === "" || item.relative_path.toLowerCase().includes(needle);

  const groups = useMemo(
    () => groupDatasets(datasets.filter(matches)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [datasets, needle],
  );
  const filteredDocuments = useMemo(
    () => documents.filter(matches),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [documents, needle],
  );

  const toggle = (key: string) =>
    setOpenGroups((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });

  if (collapsed) {
    return (
      <nav className="sidebar shell-sidebar" data-collapsed={collapsed}>
        <div className="sidebar-collapsed">DS</div>
      </nav>
    );
  }

  return (
    <nav className="sidebar shell-sidebar" data-collapsed={collapsed}>
      <div className="sidebar-filter">
        <input
          className="input"
          placeholder="Filter artifacts…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button
          className="btn btn-secondary sidebar-refresh"
          onClick={onRefresh}
          title="Refresh listings (re-check for new chunks)"
        >
          ⟳
        </button>
      </div>
      <div className="sidebar-group">
        <div className="sidebar-group-header">Datasets · {datasets.length}</div>
        {groups.length === 0 && (
          <div className="sidebar-item">
            <span className="sidebar-item-label u-muted">
              {datasets.length === 0 ? "no artifacts found" : "no matches"}
            </span>
          </div>
        )}
        {groups.map((group) => {
          const phaseKey = `phase:${group.phase}`;
          const phaseOpen = !openGroups.has(phaseKey);
          const phaseItems = [...group.runs.values()].flat();
          return (
            <div key={group.phase}>
              <button
                className="sidebar-group-header sidebar-toggle"
                data-open={phaseOpen}
                onClick={() => toggle(phaseKey)}
                title={`artifacts/${group.phase}`}
              >
                <span className="chevron">{phaseOpen ? "▾" : "▸"}</span>
                <span className="sidebar-toggle-label">artifacts/{group.phase}</span>
                <span className="badge badge-kind">{phaseItems.length}</span>
              </button>
              {phaseOpen &&
                [...group.runs.entries()].map(([run, items]) => {
                  const runKey = `run:${group.phase}:${run}`;
                  const runOpen = !openGroups.has(runKey);
                  return (
                    <div key={run}>
                      <button
                        className="sidebar-item sidebar-toggle sidebar-run"
                        data-open={runOpen}
                        onClick={() => toggle(runKey)}
                      >
                        <span className="chevron">{runOpen ? "▾" : "▸"}</span>
                        <span className="sidebar-item-label u-muted">{run}</span>
                        <span className="badge badge-kind">{items.length}</span>
                      </button>
                      {runOpen &&
                        items.map((item) => (
                          <button
                            key={item.id}
                            className="sidebar-item sidebar-leaf"
                            data-active={item.id === selectedId}
                            onClick={() => onSelect(item)}
                            title={`${item.relative_path} (${formatBytes(item.size_bytes)})`}
                          >
                            <span className="sidebar-item-label">
                              {item.relative_path.split("/").pop()}
                            </span>
                            <span className={`badge badge-${item.kind}`}>
                              {kindLabel(item.kind)}
                            </span>
                          </button>
                        ))}
                    </div>
                  );
                })}
            </div>
          );
        })}
      </div>
      <div className="sidebar-group">
        <div className="sidebar-group-header">Documents · {filteredDocuments.length}</div>
        {filteredDocuments.map((item) => (
          <button
            key={item.id}
            className="sidebar-item"
            data-active={item.id === selectedId}
            onClick={() => onSelect(item)}
            title={`${item.relative_path} (${formatBytes(item.size_bytes)})`}
          >
            <span className="sidebar-item-label">{item.relative_path.split("/").pop()}</span>
            <span className="badge badge-kind">json</span>
          </button>
        ))}
      </div>
    </nav>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}
