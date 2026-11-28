"""Imposter-census assembly over the harvested census inputs.

Joins the register falses and the per-family adjudicated trues
(bases of record, precedence per the census bound) to packet text
from every preserved store, and emits the census population, the
assembly account, and the pricing record's residual lists.
"""

from __future__ import annotations

import argparse
import ast
import gzip
import json
import pickle
import re
import tarfile
from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_text

_SID_RE = re.compile(r"^\d{10}-\d{2}-\d{6}:\d+$")
_HOST_LABELS = {"LI", "LINE-ITEM", "LINE_ITEM", "HOST-CONTENT", "HOST_CONTENT"}
_SEAT_BASES = [
    ("s4.jsonl", "goodwill"),
    ("s5.jsonl", "credit_losses_rollforward"),
    ("aro.jsonl", "aro_rollforward"),
    ("restr.jsonl", "restructuring"),
    ("warr.jsonl", "warranty"),
]
_LANE_POPULATIONS = [
    ("true_pen_grouped", "pension"),
    ("true_pen_sweep", "pension"),
    ("true_aoci_grouped", "aoci_rollforward"),
    ("true_aoci_sweep", "aoci_rollforward"),
]


def _is_sid(s: object) -> bool:
    return isinstance(s, str) and bool(_SID_RE.match(s))


def _row_sid(row: dict) -> str | None:
    sid = row.get("specimen_id") or row.get("sid")
    if _is_sid(sid):
        return sid
    acc = row.get("accession")
    idx = row.get("table_index_in_profile", row.get("table_index"))
    if acc and idx is not None:
        return f"{acc}:{idx}"
    return None


def _load_json(path: Path) -> object:
    with open(path) as fh:
        return json.load(fh)


def _iter_jsonl(path: Path):
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


class _CensusAssembly:
    """One assembly over a harvested inputs tree, state per leg."""

    def __init__(self, inputs: Path) -> None:
        self.inputs = inputs
        self.errors: list[str] = []
        self.store_hits: dict[str, int] = {}
        self.falses: dict[tuple[str, str], dict] = {}
        self.trues: dict[tuple[str, str], set] = {}
        self.text: dict[str, dict] = {}
        self.label_dist: dict[str, dict] = {}
        self.unjoinable: dict[str, dict] = {}
        self.gold_families: dict[str, list] = {}

    def _note_error(self, where: str, exc: Exception) -> None:
        self.errors.append(f"{where}: {type(exc).__name__}: {exc}")

    # ---------------------------------------------------------- falses
    def _add_false(
        self,
        sid: str,
        family: str,
        source: str,
        final_class=None,
        true_family=None,
        mechanism=None,
        stratum=None,
        label=None,
    ) -> None:
        if (family, sid) in self.falses:
            return
        self.falses[(family, sid)] = {
            "sid": sid,
            "family": family,
            "source": source,
            "final_class": final_class,
            "true_family": true_family,
            "mechanism": mechanism,
            "stratum": stratum,
            "label": label,
        }

    def _register_falses(self) -> None:
        try:
            reg = _load_json(self.inputs / "step1" / "register-step1.json")
            for row in reg.get("false_claims", []):
                self._add_false(
                    row["specimen_id"],
                    row["family"],
                    "step1-register",
                    final_class=row.get("final_class"),
                    true_family=row.get("true_family"),
                    mechanism=row.get("mechanism"),
                    stratum=row.get("stratum"),
                )
        except Exception as exc:  # noqa: BLE001
            self._note_error("register-step1", exc)

    # ----------------------------------------------------------- trues
    def _add_true(self, family, sid, source: str) -> None:
        if not _is_sid(sid) or family in (None, "", "none"):
            return
        self.trues.setdefault((family, sid), set()).add(source)

    def _base_rows(self, name: str) -> list:
        try:
            return list(_iter_jsonl(self.inputs / "bases" / name))
        except Exception as exc:  # noqa: BLE001
            self._note_error(f"base {name}", exc)
            return []

    def _dist_record(self, base: str, label) -> None:
        self.label_dist.setdefault(base, {})
        key = str(label)
        self.label_dist[base][key] = self.label_dist[base].get(key, 0) + 1

    def _seat_bases(self) -> None:
        for fname, family in _SEAT_BASES:
            for row in self._base_rows(fname):
                sid = _row_sid(row)
                label0 = (
                    row.get("label")
                    or row.get("base_label")
                    or row.get("combination_verdict")
                )
                if not sid:
                    # hash-form or missing specimen identity: counted
                    self._dist_record(fname, label0)
                    self.unjoinable.setdefault(fname, {})
                    key = str(label0)
                    self.unjoinable[fname][key] = (
                        self.unjoinable[fname].get(key, 0) + 1
                    )
                    continue
                label = label0
                cverdict = row.get("combination_verdict")
                self._dist_record(fname, label if label is not None else cverdict)
                is_true = (label == "TRUE") or (cverdict == "TRUE")
                if is_true:
                    self._add_true(family, sid, f"base:{fname}")
                else:
                    lab = label if label is not None else cverdict
                    if str(lab) not in _HOST_LABELS:
                        self._add_false(
                            sid,
                            family,
                            f"base:{fname}",
                            final_class=f"base-label:{lab}",
                            label=lab,
                        )

    def _grouped_populations(self) -> None:
        try:
            laneb = _load_json(self.inputs / "step9" / "core-populations.json")
            pops = laneb.get("pops", {})
            for key, family in _LANE_POPULATIONS:
                for sid in pops.get(key, []):
                    self._add_true(family, sid, "step9-lane-b")
        except Exception as exc:  # noqa: BLE001
            self._note_error("step9 lane-b populations", exc)

    def _sweep_populations(self) -> None:
        try:
            laned = _load_json(self.inputs / "step9" / "pops.json")
            for family, sides in laned.items():
                for entry in sides.get("true", []):
                    self._add_true(family, entry.get("sid"), "step9-lane-d")
        except Exception as exc:  # noqa: BLE001
            self._note_error("step9 lane-d pops", exc)

    def _gold_lists(self) -> None:
        try:
            for txt in sorted((self.inputs / "step8").glob("*.txt")):
                family = txt.stem
                sids = re.findall(
                    r"^===== (\d{10}-\d{2}-\d{6}:\d+)", txt.read_text(), flags=re.M
                )
                self.gold_families[family] = sids
                for sid in sids:
                    self._add_true(family, sid, "step8-golds")
        except Exception as exc:  # noqa: BLE001
            self._note_error("step8 gold dumps (lists)", exc)

    def _verdicts_fallback(self) -> None:
        # Families covered by a named base above keep precedence;
        # this fallback fills members and sweep golds for the rest.
        covered = {fam for (fam, _sid) in self.trues}
        for strat in ("b", "d"):
            try:
                for row in _iter_jsonl(self.inputs / "run2" / f"grouped-{strat}.jsonl"):
                    fam = row.get("family")
                    if row.get("verdict") == "member" and fam not in covered:
                        self._add_true(fam, row.get("specimen_id"), "run2-verdicts")
            except Exception as exc:  # noqa: BLE001
                self._note_error(f"run2 grouped-{strat}", exc)
            try:
                for row in _iter_jsonl(self.inputs / "run2" / f"sweep-{strat}.jsonl"):
                    fam = row.get("true_family")
                    if fam and fam not in covered:
                        self._add_true(fam, row.get("specimen_id"), "run2-verdicts")
            except Exception as exc:  # noqa: BLE001
                self._note_error(f"run2 sweep-{strat}", exc)

    def _population_supplement(self) -> None:
        for strat in ("b", "d"):
            for kind in ("grouped", "sweep"):
                try:
                    rows = _iter_jsonl(
                        self.inputs
                        / "step1pk"
                        / "verdicts-final"
                        / f"{kind}-{strat}.jsonl"
                    )
                    for row in rows:
                        if kind == "grouped" and row.get("verdict") == "member":
                            self._add_true(
                                row.get("family"),
                                row.get("specimen_id"),
                                "step1-verdicts",
                            )
                        elif kind == "sweep" and row.get("true_family"):
                            self._add_true(
                                row.get("true_family"),
                                row.get("specimen_id"),
                                "step1-verdicts",
                            )
                except Exception as exc:  # noqa: BLE001
                    self._note_error(f"step1 {kind}-{strat}", exc)

    # ------------------------------------------------------------ text
    def _put_text(
        self, sid, store, caption_stack, prose_before, prose_after, table_text
    ) -> None:
        if not _is_sid(sid) or sid in self.text:
            return
        self.text[sid] = {
            "caption_stack": caption_stack or [],
            "prose_before": prose_before or "",
            "prose_after": prose_after or "",
            "table_text": table_text or "",
            "store": store,
        }
        self.store_hits[store] = self.store_hits.get(store, 0) + 1

    def _packet_row(self, row: dict, store: str) -> None:
        self._put_text(
            row.get("specimen_id"),
            store,
            row.get("caption_stack"),
            row.get("prose_before"),
            row.get("prose_after"),
            row.get("table_text"),
        )

    def _baseline_packets(self) -> None:
        for name in ("packets-b.jsonl", "packets-d.jsonl", "packets-supplement.jsonl"):
            try:
                for row in _iter_jsonl(self.inputs / "step1pk" / name):
                    self._packet_row(row, "step1-packets")
            except Exception as exc:  # noqa: BLE001
                self._note_error(f"step1pk {name}", exc)

    def _slice_packets(self) -> None:
        try:
            for path in sorted((self.inputs / "step1slices").glob("*.jsonl")):
                for row in _iter_jsonl(path):
                    self._packet_row(row, "step1-slices")
        except Exception as exc:  # noqa: BLE001
            self._note_error("step1 slices", exc)

    def _lane_packets(self) -> None:
        try:
            data = _load_json(self.inputs / "step9" / "core-populations.json")
            pk = data.get("packets", {})
            if isinstance(pk, dict):
                for sid, row in pk.items():
                    if isinstance(row, dict):
                        self._put_text(
                            sid,
                            "step9-lane-b-packets",
                            row.get("caption_stack"),
                            row.get("prose_before"),
                            row.get("prose_after"),
                            row.get("table_text"),
                        )
        except Exception as exc:  # noqa: BLE001
            self._note_error("lane-b packets", exc)
        try:
            cache = _load_json(self.inputs / "step9" / "cache.json")
            pk = cache.get("packets", {})
            if isinstance(pk, dict):
                for sid, row in pk.items():
                    if isinstance(row, dict):
                        self._put_text(
                            sid,
                            "step9-lane-d-cache",
                            row.get("caption_stack"),
                            row.get("prose_before"),
                            row.get("prose_after"),
                            row.get("table_text"),
                        )
        except Exception as exc:  # noqa: BLE001
            self._note_error("lane-d cache packets", exc)

    def _gold_text(self) -> None:
        try:
            for txt in sorted((self.inputs / "step8").glob("*.txt")):
                body = txt.read_text()
                blocks = re.split(r"^===== ", body, flags=re.M)
                for block in blocks:
                    m = re.match(r"(\d{10}-\d{2}-\d{6}:\d+)", block)
                    if not m:
                        continue
                    sid = m.group(1)
                    cap = re.search(r"caption_stack: (\[.*?\])\n", block, flags=re.S)
                    pro = re.search(
                        r"prose_before: (.*?)\ntable_text:\n", block, flags=re.S
                    )
                    tab = re.search(r"table_text:\n(.*)$", block, flags=re.S)
                    caption = []
                    if cap:
                        try:
                            caption = ast.literal_eval(cap.group(1))
                        except Exception:  # noqa: BLE001
                            caption = []
                    prose = ""
                    if pro:
                        raw = pro.group(1).strip()
                        try:
                            prose = ast.literal_eval(raw)
                        except Exception:  # noqa: BLE001
                            prose = raw
                    self._put_text(
                        sid,
                        "step8-gold-dumps",
                        caption,
                        prose,
                        "",
                        tab.group(1) if tab else "",
                    )
        except Exception as exc:  # noqa: BLE001
            self._note_error("step8 gold dumps (text)", exc)

    def _stratum_dump(self) -> None:
        try:
            body = (self.inputs / "bases" / "s4-packets.txt").read_text()
            blocks = re.split(r"^={10,} ", body, flags=re.M)
            for block in blocks:
                m = re.match(r"(\d{10}-\d{2}-\d{6}:\d+)", block)
                if not m:
                    continue
                sid = m.group(1)
                cap = re.search(r"CAPSTACK: (\[.*?\])\n", block, flags=re.S)
                pro = re.search(r"PROSE: (.*?)\nTABLE: ", block, flags=re.S)
                tab = re.search(r"TABLE: (.*)$", block, flags=re.S)
                caption = []
                if cap:
                    try:
                        caption = ast.literal_eval(cap.group(1))
                    except Exception:  # noqa: BLE001
                        caption = []
                self._put_text(
                    sid,
                    "s4-dump",
                    caption,
                    pro.group(1) if pro else "",
                    "",
                    tab.group(1) if tab else "",
                )
        except Exception as exc:  # noqa: BLE001
            self._note_error("s4 packets dump", exc)

    def _reform_tar(self) -> None:
        try:
            with tarfile.open(self.inputs / "s5data" / "s5reform-data.tar.gz") as tf:
                names = tf.getnames()
                for name in names:
                    if name.endswith(".jsonl"):
                        fh = tf.extractfile(name)
                        for line in fh:
                            row = json.loads(line)
                            self._packet_row(row, "s5-data-tar")
                    elif name.endswith(".pkl"):
                        fh = tf.extractfile(name)
                        obj = pickle.load(fh)
                        rows = obj.values() if isinstance(obj, dict) else obj
                        for row in rows:
                            if isinstance(row, dict):
                                self._packet_row(row, "s5-data-tar")
        except Exception as exc:  # noqa: BLE001
            self._note_error("s5 data tar", exc)

    def _rendered_dump(self, path: Path, store: str) -> None:
        body = path.read_text()
        for block in re.split(r"^### ", body, flags=re.M):
            m = re.search(r"(\d{10}-\d{2}-\d{6}):(\d+)\b", block)
            mid = re.search(r"ID (\d{10}-\d{2}-\d{6}) tbl(\d+)", block)
            if m:
                sid = f"{m.group(1)}:{m.group(2)}"
            elif mid:
                sid = f"{mid.group(1)}:{mid.group(2)}"
            else:
                continue
            cap = re.search(r"^CAP: (.*)$", block, flags=re.M)
            ctx = re.search(r"^CTX: (.*)$", block, flags=re.M)
            hdr = re.search(r"^HDR: (.*)$", block, flags=re.M)
            rows = re.findall(r"^\s*R: (.*)$", block, flags=re.M)
            table_lines = ([hdr.group(1)] if hdr else []) + rows
            caption = [cap.group(1)] if cap and cap.group(1).strip() else []
            self._put_text(
                sid,
                store,
                caption,
                ctx.group(1) if ctx else "",
                "",
                "\n".join(table_lines),
            )

    def _rendered_dumps(self) -> None:
        for fname, store in (
            ("trues-dump.txt", "s4-trues-dump"),
            ("worklist-e.txt", "s4-worklist-e"),
        ):
            try:
                self._rendered_dump(self.inputs / "bases" / fname, store)
            except Exception as exc:  # noqa: BLE001
                self._note_error(f"s4 dump {fname}", exc)

    def _pool_records(self) -> None:
        try:
            pools = _load_json(self.inputs / "bases" / "pools-e.json")
            records = pools.values() if isinstance(pools, dict) else pools
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                sid = _row_sid(rec)
                if not sid:
                    acc = rec.get("accession")
                    tidx = rec.get("tidx", rec.get("table_index"))
                    if acc and tidx is not None:
                        sid = f"{acc}:{tidx}"
                if not sid:
                    continue
                table_text = rec.get("table_text") or ""
                if not table_text and isinstance(rec.get("rows"), list):
                    table_text = "\n".join(str(r) for r in rec["rows"])
                if table_text:
                    self._put_text(
                        sid,
                        "s4-pools-e",
                        rec.get("caption_stack") or [],
                        rec.get("prose_before") or rec.get("ctx") or "",
                        "",
                        table_text,
                    )
        except Exception as exc:  # noqa: BLE001
            self._note_error("s4 pools-e", exc)

    def _collect_packets(self) -> None:
        # Streamed last: only specimens no earlier store served.
        needed = {r["sid"] for r in self.falses.values()} | {
            sid for (_f, sid) in self.trues
        }
        missing = needed - set(self.text)
        if missing:
            sid_line = re.compile(r'"specimen_id": "(\d{10}-\d{2}-\d{6}:\d+)"')
            for strat in ("b", "d"):
                if not missing:
                    break
                try:
                    with gzip.open(
                        self.inputs / "run2pk" / f"step6-packets-{strat}.jsonl.gz",
                        "rt",
                        errors="replace",
                    ) as fh:
                        for line in fh:
                            m = sid_line.search(line[:80])
                            if m and m.group(1) in missing:
                                row = json.loads(line)
                                self._packet_row(row, "run2-packets")
                                missing.discard(m.group(1))
                except Exception as exc:  # noqa: BLE001
                    self._note_error(f"run2 packets {strat}", exc)

    # ------------------------------------------------------------ emit
    def run(self) -> tuple[list, dict]:
        """Run every leg in precedence order; return the artifact."""
        self._register_falses()
        self._seat_bases()
        self._grouped_populations()
        self._sweep_populations()
        self._gold_lists()
        self._verdicts_fallback()
        self._population_supplement()
        self._baseline_packets()
        self._slice_packets()
        self._lane_packets()
        self._gold_text()
        self._stratum_dump()
        self._reform_tar()
        self._rendered_dumps()
        self._pool_records()
        self._collect_packets()
        return self._emit()

    def _emit(self) -> tuple[list, dict]:
        units = sorted(
            {r["family"] for r in self.falses.values()}
            | {fam for (fam, _s) in self.trues}
        )
        pop_rows = []
        per_family = {}
        for fam in units:
            fam_falses = [r for r in self.falses.values() if r["family"] == fam]
            fam_trues = sorted({sid for (f, sid) in self.trues if f == fam})
            f_text = sum(1 for r in fam_falses if r["sid"] in self.text)
            t_text = sum(1 for sid in fam_trues if sid in self.text)
            by_source = {}
            for sid in fam_trues:
                for src in self.trues[(fam, sid)]:
                    by_source[src] = by_source.get(src, 0) + 1
            per_family[fam] = {
                "falses": len(fam_falses),
                "falses_with_text": f_text,
                "falses_no_text": sorted(
                    r["sid"] for r in fam_falses if r["sid"] not in self.text
                ),
                "trues": len(fam_trues),
                "trues_with_text": t_text,
                "trues_no_text": sorted(
                    sid for sid in fam_trues if sid not in self.text
                ),
                "trues_by_source": by_source,
                "thin": len(fam_trues) < 10,
            }
            for r in fam_falses:
                t = self.text.get(r["sid"], {})
                pop_rows.append(
                    {
                        "sid": r["sid"],
                        "family": fam,
                        "side": "false",
                        "source": r["source"],
                        "final_class": r["final_class"],
                        "true_family": r["true_family"],
                        "mechanism": r["mechanism"],
                        "stratum": r["stratum"],
                        "label": r["label"],
                        "text_source": t.get("store"),
                        "caption_stack": t.get("caption_stack", []),
                        "prose_before": t.get("prose_before", ""),
                        "prose_after": t.get("prose_after", ""),
                        "table_text": t.get("table_text", ""),
                    }
                )
            for sid in fam_trues:
                t = self.text.get(sid, {})
                pop_rows.append(
                    {
                        "sid": sid,
                        "family": fam,
                        "side": "true",
                        "source": sorted(self.trues[(fam, sid)]),
                        "final_class": None,
                        "true_family": None,
                        "mechanism": None,
                        "stratum": None,
                        "label": None,
                        "text_source": t.get("store"),
                        "caption_stack": t.get("caption_stack", []),
                        "prose_before": t.get("prose_before", ""),
                        "prose_after": t.get("prose_after", ""),
                        "table_text": t.get("table_text", ""),
                    }
                )
        assembly = {
            "units": units,
            "total_falses": len(self.falses),
            "total_true_rows": len(pop_rows) - len(self.falses),
            "per_family": per_family,
            "store_hits": self.store_hits,
            "label_distributions": self.label_dist,
            "unjoinable_base_rows": self.unjoinable,
            "gold_families": {k: len(v) for k, v in self.gold_families.items()},
            "errors": self.errors,
        }
        return pop_rows, assembly


def residual_lists(pricing: dict) -> str:
    """The pricing record's residual falses, listed per family."""
    lines = []
    for family, entry in pricing.items():
        residual = entry.get("residual") or []
        if not residual:
            continue
        lines.append(f"## {family} residual {len(residual)}")
        for r in residual:
            lines.append(
                f"{r['sid']} | {r['final_class']} | mech={r['mechanism']}"
                f" | firm={r['firm']} | core_carried={len(r['core_terms_carried'])}"
                f" | lexical={r['killed_by_lexical_single']}"
            )
    return "\n".join(lines)


def assemble(
    inputs: Path, out_dir: Path, pricing_path: Path | None = None
) -> dict:
    """Assemble the census artifact into out_dir; return the summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pop_rows, assembly = _CensusAssembly(inputs).run()
    population = "".join(json.dumps(row) + "\n" for row in pop_rows)
    atomic_write_text(out_dir / "census-population.jsonl", population)
    atomic_write_text(
        out_dir / "census-assembly.json", json.dumps(assembly, indent=1)
    )
    if pricing_path is not None:
        pricing = _load_json(pricing_path)
        atomic_write_text(out_dir / "residual-lists.txt", residual_lists(pricing))
    return {
        "units": len(assembly["units"]),
        "falses": assembly["total_falses"],
        "pop_rows": len(pop_rows),
        "errors": len(assembly["errors"]),
    }


def main(argv: list[str] | None = None) -> int:
    """Assemble a census population from a harvested inputs tree."""
    parser = argparse.ArgumentParser(prog="census_assembly")
    parser.add_argument("inputs", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--pricing", type=Path)
    args = parser.parse_args(argv)
    summary = assemble(args.inputs, args.out, args.pricing)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
