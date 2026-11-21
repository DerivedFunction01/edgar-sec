import { useEffect, useState } from "react";
import { fetchText, type TextPage } from "../api";

interface Props {
  id: string;
  path: string;
}

export default function TextFileView({ id, path }: Props) {
  const [page, setPage] = useState<TextPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPage(null);
    setError(null);
    setLoading(true);
    void fetchText(id)
      .then((first) => {
        if (!cancelled) setPage(first);
      })
      .catch((exc) => {
        if (!cancelled) setError(exc instanceof Error ? exc.message : String(exc));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const loadMore = async () => {
    if (!page?.next_offset || loading) return;
    setLoading(true);
    setError(null);
    try {
      const next = await fetchText(id, page.next_offset);
      setPage((current) =>
        current
          ? {
              ...next,
              text: current.text + next.text,
            }
          : next,
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="detail text-file-view">
      <div className="detail-header">
        <span className="panel-title mono">{path}</span>
        {page && (
          <span className="u-muted">
            {page.text.length.toLocaleString()} chars · {formatBytes(page.size_bytes)}
          </span>
        )}
      </div>
      {error ? (
        <div className="table-empty console-error">{error}</div>
      ) : (
        <pre className="detail-json mono text-file-content">
          {page?.text ?? (loading ? "Loading…" : "")}
        </pre>
      )}
      {page?.has_more && (
        <div className="pagination">
          <span className="u-muted">More text is available</span>
          <span className="u-spacer" />
          <button className="btn btn-secondary" disabled={loading} onClick={() => void loadMore()}>
            {loading ? "Loading…" : "Load next chunk"}
          </button>
        </div>
      )}
    </section>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}
