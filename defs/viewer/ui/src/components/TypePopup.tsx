import { createPortal } from "react-dom";
import { prettyType } from "../lib/duckTypes";

interface Props {
  name: string;
  type: string;
  anchor: DOMRect;
  onClose: () => void;
}

export default function TypePopup({ name, type, anchor, onClose }: Props) {
  const left = Math.min(anchor.left, Math.max(8, window.innerWidth - 540));
  const top = anchor.bottom + 6;
  return createPortal(
    <>
      <div className="pop-backdrop" onClick={onClose} />
      <div className="type-pop" style={{ left, top }} onClick={(event) => event.stopPropagation()}>
        <div className="filter-pop-head">
          <span className="mono filter-pop-name">{name}</span>
          <button className="btn btn-ghost" onClick={onClose} title="close">
            ✕
          </button>
        </div>
        <pre className="mono type-pop-pre">{prettyType(type)}</pre>
      </div>
    </>,
    document.body,
  );
}
