import { type ReactNode, useEffect, useState } from "react";
import { fetchTreeChildren, type TreeEntry } from "../api";

interface Props {
  selectedId: string | null;
  onSelect: (entry: TreeEntry) => void;
  collapsed: boolean;
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function badge(entry: TreeEntry): string {
  if (entry.kind) return entry.kind.replaceAll("_", " ");
  if (entry.node_type === "directory") return "directory";
  if (entry.node_type === "database") return `${entry.format} database`;
  if (entry.node_type === "table") return "table";
  return entry.format ?? "file";
}

export default function ArtifactSidebar({ selectedId, onSelect, collapsed }: Props) {
  const [root, setRoot] = useState<TreeEntry[]>([]);
  const [children, setChildren] = useState<Record<string, TreeEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [rootLoaded, setRootLoaded] = useState(false);

  const loadRoot = async () => {
    setError(null);
    try {
      const entries = await fetchTreeChildren();
      setRoot(entries);
      setChildren({ root: entries });
      setRootLoaded(true);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      setRootLoaded(true);
    }
  };

  useEffect(() => {
    void loadRoot();
  }, []);

  const refresh = async () => {
    setChildren({});
    setExpanded(new Set());
    await loadRoot();
  };

  const toggle = async (entry: TreeEntry) => {
    if (expanded.has(entry.id)) {
      setExpanded((current) => {
        const next = new Set(current);
        next.delete(entry.id);
        return next;
      });
      return;
    }
    setExpanded((current) => new Set(current).add(entry.id));
    if (Object.hasOwn(children, entry.id)) return;
    setLoading((current) => new Set(current).add(entry.id));
    try {
      const entries = await fetchTreeChildren(entry.id);
      setChildren((current) => ({ ...current, [entry.id]: entries }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading((current) => {
        const next = new Set(current);
        next.delete(entry.id);
        return next;
      });
    }
  };

  if (collapsed) {
    return (
      <nav className="sidebar shell-sidebar" data-collapsed={collapsed}>
        <div className="sidebar-collapsed">FS</div>
      </nav>
    );
  }

  const needle = query.trim().toLowerCase();
  const renderNodes = (nodes: TreeEntry[], depth: number): ReactNode =>
    nodes
      .filter(
        (entry) => !needle || `${entry.name} ${entry.relative_path}`.toLowerCase().includes(needle),
      )
      .map((entry) => {
        const isExpanded = expanded.has(entry.id);
        const canExpand = entry.has_children;
        const isActive = entry.id === selectedId;
        return (
          <div key={entry.id}>
            <button
              className="sidebar-item tree-item"
              style={{ paddingLeft: `${8 + depth * 13}px` }}
              data-active={isActive}
              title={`${entry.relative_path} (${formatBytes(entry.size_bytes)})`}
              onClick={() => {
                if (canExpand) void toggle(entry);
                else onSelect(entry);
              }}
            >
              <span className="tree-item-main">
                {canExpand ? (
                  <span className="tree-chevron">{isExpanded ? "▾" : "▸"}</span>
                ) : (
                  <span className="tree-chevron" />
                )}
                <span className="sidebar-item-label">{entry.name}</span>
              </span>
              <span className="badge badge-kind tree-badge">{badge(entry)}</span>
            </button>
            {isExpanded && loading.has(entry.id) && (
              <div className="tree-message" style={{ paddingLeft: `${18 + depth * 13}px` }}>
                loading…
              </div>
            )}
            {isExpanded && children[entry.id]?.length === 0 && !loading.has(entry.id) && (
              <div className="tree-message" style={{ paddingLeft: `${18 + depth * 13}px` }}>
                no tables or supported files
              </div>
            )}
            {isExpanded && children[entry.id]?.length
              ? renderNodes(children[entry.id], depth + 1)
              : null}
          </div>
        );
      });

  return (
    <nav className="sidebar shell-sidebar" data-collapsed={collapsed}>
      <div className="sidebar-filter">
        <input
          className="input"
          placeholder="Filter loaded files…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button
          className="btn btn-secondary sidebar-refresh"
          onClick={() => void refresh()}
          title="Refresh explorer"
        >
          ⟳
        </button>
      </div>
      <div className="sidebar-group-header">Artifacts root · {root.length}</div>
      {error && <div className="tree-message console-error">{error}</div>}
      {root.length === 0 && !rootLoaded && !error ? (
        <div className="tree-message">loading artifacts…</div>
      ) : root.length === 0 ? (
        <div className="tree-message">no supported files found</div>
      ) : (
        renderNodes(root, 0)
      )}
    </nav>
  );
}
