import { useCallback, useEffect, useRef, useState } from "react";
import { runSql, type SqlResult } from "../api";
import { tokenizeSql } from "../lib/sqlHighlight";

const HISTORY_KEY = "viewer-sql-history";
const MAX_HISTORY = 10;

interface Props {
  datasetId: string | null;
  datasetName: string | null;
  onResult: (result: SqlResult, query: string) => void;
}

function loadHistory(): string[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(history: string[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, MAX_HISTORY)));
  } catch {
    // ignore quota / unavailable storage
  }
}

export default function SqlConsole({ datasetId, datasetName, onResult }: Props) {
  const [query, setQuery] = useState("SELECT * FROM dataset LIMIT 10;");
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const tokens = tokenizeSql(query);
  const initialized = useRef(false);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    const stored = loadHistory();
    setHistory(stored);
    if (stored.length > 0) setQuery(stored[0]);
  }, []);

  const run = useCallback(async () => {
    if (!datasetId) {
      setError("Select a dataset first — console queries run against `dataset`.");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const next = await runSql(datasetId, query);
      onResult(next, query);
      setHistory((current) => {
        const trimmed = query.trim();
        if (current[0] === trimmed) return current;
        const nextHistory = [trimmed, ...current.filter((item) => item !== trimmed)];
        saveHistory(nextHistory);
        return nextHistory;
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRunning(false);
    }
  }, [datasetId, query]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        void run();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [run]);

  return (
    <div className="console">
      <div className="panel-header">
        <span className="panel-title">SQL Console</span>
        <span className="u-muted">{datasetName ?? "no dataset"}</span>
      </div>
      <div
        style={{
          padding: 10,
          display: "flex",
          flexDirection: "column",
          flex: 1,
          minHeight: 0,
        }}
      >
        <div className="console-editor-wrap">
          <pre className="console-highlight mono" aria-hidden="true">
            {tokens.map((token, index) => (
              <span
                key={index}
                className={token.kind === "plain" ? undefined : `tok-${token.kind}`}
              >
                {token.text}
              </span>
            ))}
          </pre>
          <textarea
            className="console-editor console-editor-input mono"
            value={query}
            spellCheck={false}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="console-actions">
          <span className="console-meta mono">{tokens.length} tokens</span>
          <button
            className="btn btn-secondary"
            onClick={() => setShowHistory((open) => !open)}
            title="Query history"
          >
            History
          </button>
          <button className="btn btn-secondary" onClick={() => setError(null)}>
            Clear
          </button>
          <button className="btn btn-primary" onClick={() => void run()} disabled={running}>
            {running ? "Running…" : "Run Query (Ctrl+↵)"}
          </button>
        </div>
        {showHistory && history.length > 0 && (
          <ul className="console-history">
            {history.map((item) => (
              <li key={item}>
                <button
                  className="console-history-item"
                  onClick={() => {
                    setQuery(item);
                    setShowHistory(false);
                  }}
                >
                  {item}
                </button>
              </li>
            ))}
          </ul>
        )}
        {error && <div className="console-error">{error}</div>}
      </div>
    </div>
  );
}
