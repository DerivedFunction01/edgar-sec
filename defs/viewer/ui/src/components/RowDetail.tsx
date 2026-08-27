import { useState } from "react";

function Scalar({ value }: { value: unknown }) {
  if (typeof value === "string") {
    return <span className="json-string">"{value}"</span>;
  }
  if (typeof value === "number") {
    return <span className="json-number">{String(value)}</span>;
  }
  if (typeof value === "boolean" || value === null) {
    return <span className="json-boolean">{String(value)}</span>;
  }
  return <span className="json-number">{String(value)}</span>;
}

export function JsonValue({
  value,
  depth = 0,
  collapseDepth = Infinity,
}: {
  value: unknown;
  depth?: number;
  collapseDepth?: number;
}) {
  const [open, setOpen] = useState(depth < collapseDepth);
  const indent = "  ".repeat(depth);

  if (value === null || typeof value !== "object") {
    return <Scalar value={value} />;
  }

  const is_array = Array.isArray(value);
  const entries: [string, unknown][] = is_array
    ? (value as unknown[]).map((item, index) => [String(index), item])
    : Object.entries(value as Record<string, unknown>);
  const brackets = is_array ? ["[", "]"] : ["{", "}"];

  if (entries.length === 0) {
    return (
      <span className="json-punctuation">
        {brackets[0]}
        {brackets[1]}
      </span>
    );
  }

  return (
    <span className="mono">
      <span
        className="json-punctuation"
        style={{ cursor: "pointer" }}
        onClick={() => setOpen(!open)}
      >
        {open ? "▾" : "▸"} {brackets[0]}
      </span>
      {open ? (
        <span>
          {entries.map(([key, child], index) => (
            <span key={key}>
              {"\n"}
              {`${indent}  `}
              {!is_array && <span className="json-key">"{key}"</span>}
              {!is_array && <span className="json-punctuation">: </span>}
              <JsonValue value={child} depth={depth + 1} collapseDepth={collapseDepth} />
              {index < entries.length - 1 && <span className="json-punctuation">,</span>}
            </span>
          ))}
          {"\n"}
          {indent}
          <span className="json-punctuation">{brackets[1]}</span>
        </span>
      ) : (
        <span className="json-punctuation">…{brackets[1]}</span>
      )}
    </span>
  );
}

export function JsonDocument({ content }: { content: unknown }) {
  const [raw, setRaw] = useState(false);
  const pretty = JSON.stringify(content, null, 2);
  return (
    <>
      <div className="detail-actions">
        <button className="btn btn-secondary" onClick={() => setRaw((value) => !value)}>
          {raw ? "Tree" : "Raw"}
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => void navigator.clipboard?.writeText(pretty)}
        >
          Copy JSON
        </button>
      </div>
      {raw ? (
        <pre className="detail-json mono">{pretty}</pre>
      ) : (
        <div className="detail-json">
          <JsonValue value={content} collapseDepth={3} />
        </div>
      )}
    </>
  );
}

interface Props {
  row: Record<string, unknown> | null;
  onClose: () => void;
}

export default function RowDetail({ row, onClose }: Props) {
  if (!row) return null;
  return (
    <div className="detail">
      <div className="detail-header">
        <span className="panel-title">Row detail</span>
        <button className="btn btn-ghost" onClick={onClose}>
          ✕
        </button>
      </div>
      <div className="detail-json">
        <JsonValue value={row} />
      </div>
    </div>
  );
}
