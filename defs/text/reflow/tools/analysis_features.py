"""Schemas and deterministic feature helpers for the reflow review inventory."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from statistics import fmean, pvariance
from typing import Any

from defs.storage import pa
from defs.text.reflow.features import _compute_features, _Features, _numeric_cell_starts

SCHEMA_VERSION = "2"
FEATURE_VERSION = "prose-layout-v1"
LABELS = frozenset({"PROSE_UNWRAP", "TABLE_TAG", "LAYOUT_PRESERVE", "MIXED_REVIEW"})
CONTROL_ROLES = (
    "ordinary_prose_control",
    "table_tag_control",
    "layout_preserve_control",
    "hardwrapped_preserve_control",
    "protected_table_control",
    "protected_signature_control",
    "protected_signature_control",
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_TABLE_SENTINEL = re.compile(r"__SEC_TBL_\d+__")
_SIGNATURE_SENTINEL = re.compile(r"__SEC_SIG_\d+_\d+__")
_LIST_MARKER = re.compile(
    r"^\s*(?:\([A-Za-z0-9]+\)|\d+[.)]|[A-Za-z][.)]|[ivxlcdm]+[.)]|[-*])(?=\s)",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:,\d{3})*(?:\.\d+)?%?|[^\w\s]")
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s*$")
_FUNCTION_WORDS = frozenset(
    [
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "may",
        "me",
        "might",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "year",
        "years",
        "ended",
        "respectively",
    ]
)

BLOCK_SCHEMA = pa.schema(
    [
        pa.field("block_id", pa.string(), nullable=False),
        pa.field("record_kind", pa.string(), nullable=False),
        pa.field("case_id", pa.string(), nullable=False),
        pa.field("document_id", pa.string(), nullable=False),
        pa.field("accession", pa.string()),
        pa.field("document_path", pa.string()),
        pa.field("form", pa.string()),
        pa.field("source_sha256", pa.string()),
        pa.field("current_output_sha256", pa.string(), nullable=False),
        pa.field("current_output_line_start", pa.int32(), nullable=False),
        pa.field("current_output_line_end", pa.int32(), nullable=False),
        pa.field("masked_line_start", pa.int32(), nullable=False),
        pa.field("masked_line_end", pa.int32(), nullable=False),
        pa.field("source_char_start", pa.int64()),
        pa.field("source_char_end", pa.int64()),
        pa.field("block_text", pa.string(), nullable=False),
        pa.field("context_before", pa.string(), nullable=False),
        pa.field("context_after", pa.string(), nullable=False),
        pa.field("contains_protected_table", pa.bool_(), nullable=False),
        pa.field("contains_protected_signature", pa.bool_(), nullable=False),
        pa.field("classifier_action", pa.string(), nullable=False),
        pa.field("classifier_confidence", pa.float64(), nullable=False),
        pa.field("classifier_evidence", pa.list_(pa.string()), nullable=False),
        pa.field("classifier_trace", pa.string(), nullable=False),
        pa.field("pipeline_action", pa.string(), nullable=False),
        pa.field("pipeline_evidence", pa.list_(pa.string()), nullable=False),
        pa.field("pipeline_trace", pa.string(), nullable=False),
        pa.field("final_action", pa.string(), nullable=False),
        pa.field("final_evidence", pa.list_(pa.string()), nullable=False),
        pa.field("final_trace", pa.string(), nullable=False),
        pa.field("control_role", pa.string(), nullable=False),
        pa.field("label_required", pa.bool_(), nullable=False),
        pa.field("gold_label", pa.string()),
        pa.field("label_rationale", pa.string()),
        pa.field("split_group", pa.string(), nullable=False),
        pa.field("content_fingerprint", pa.string(), nullable=False),
        pa.field("feature_non_blank", pa.int32(), nullable=False),
        pa.field("feature_has_structural", pa.bool_(), nullable=False),
        pa.field("feature_has_tab", pa.bool_(), nullable=False),
        pa.field("feature_has_separator", pa.bool_(), nullable=False),
        pa.field("feature_has_dot_leader", pa.bool_(), nullable=False),
        pa.field("feature_has_signature", pa.bool_(), nullable=False),
        pa.field("feature_max_gap", pa.int32(), nullable=False),
        pa.field("feature_gap_row_count", pa.int32(), nullable=False),
        pa.field("feature_gap_start_positions", pa.list_(pa.int32()), nullable=False),
        pa.field("feature_numeric_cell_rows", pa.int32(), nullable=False),
        pa.field("feature_shared_numeric_columns", pa.int32(), nullable=False),
        pa.field(
            "feature_numeric_cell_positions", pa.list_(pa.int32()), nullable=False
        ),
        pa.field("feature_alpha_density", pa.float64(), nullable=False),
        pa.field("feature_any_lowercase", pa.bool_(), nullable=False),
        pa.field("feature_word_count", pa.int32(), nullable=False),
        pa.field("feature_function_word_count", pa.int32(), nullable=False),
        pa.field("feature_function_word_ratio", pa.float64(), nullable=False),
        pa.field("feature_words_per_line_mean", pa.float64(), nullable=False),
        pa.field("feature_line_length_variance", pa.float64(), nullable=False),
        pa.field("feature_sentence_punctuation_count", pa.int32(), nullable=False),
        pa.field("feature_sentence_terminal_lines", pa.int32(), nullable=False),
        pa.field("feature_list_marker_count", pa.int32(), nullable=False),
        pa.field("feature_numeric_run_count", pa.int32(), nullable=False),
        pa.field("feature_max_consecutive_numbers", pa.int32(), nullable=False),
        pa.field(
            "feature_numeric_lines_without_list_marker", pa.int32(), nullable=False
        ),
    ]
)

TOKEN_SCHEMA = pa.schema(
    [
        pa.field("block_id", pa.string(), nullable=False),
        pa.field("document_id", pa.string(), nullable=False),
        pa.field("control_role", pa.string(), nullable=False),
        pa.field("token_ordinal", pa.int32(), nullable=False),
        pa.field("line_index", pa.int32(), nullable=False),
        pa.field("char_start", pa.int32(), nullable=False),
        pa.field("token", pa.string(), nullable=False),
        pa.field("normalized_token", pa.string(), nullable=False),
        pa.field("token_kind", pa.string(), nullable=False),
        pa.field("is_function_word", pa.bool_(), nullable=False),
        pa.field("is_list_marker", pa.bool_(), nullable=False),
        pa.field("is_numeric", pa.bool_(), nullable=False),
        pa.field("gold_label", pa.string()),
    ]
)


def digest(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def safe_id(value: str, name: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{name} must contain only letters, numbers, '.', '_', or '-'")
    return value


def jsonl_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL at {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield record


def tokenize(
    text: str, block_id: str, document_id: str, control_role: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    ordinal = 0
    for line_index, line in enumerate(text.splitlines()):
        marker = _LIST_MARKER.match(line)
        marker_start, marker_end = (
            (marker.start(), marker.end()) if marker else (-1, -1)
        )
        for match in _TOKEN.finditer(line):
            raw = match.group(0)
            kind = (
                "word"
                if raw[0].isalpha()
                else "number"
                if raw[0].isdigit()
                else "punctuation"
            )
            is_marker = marker_start <= match.start() < marker_end
            if is_marker:
                kind = "list_marker"
            normalized = raw.casefold()
            records.append(
                {
                    "block_id": block_id,
                    "document_id": document_id,
                    "control_role": control_role,
                    "token_ordinal": ordinal,
                    "line_index": line_index,
                    "char_start": match.start(),
                    "token": raw,
                    "normalized_token": normalized,
                    "token_kind": kind,
                    "is_function_word": kind == "word"
                    and normalized in _FUNCTION_WORDS,
                    "is_list_marker": is_marker,
                    "is_numeric": kind == "number",
                    "gold_label": None,
                }
            )
            ordinal += 1
    return records


def feature_values(
    lines: tuple[str, ...], features: _Features | None = None
) -> dict[str, Any]:
    features = features or _compute_features(lines)
    gap_positions = [position for row in features.gap_start_rows for position in row]
    numeric_positions = [
        position for line in lines for position in _numeric_cell_starts(line)
    ]
    word_counts: list[int] = []
    function_count = word_count = punctuation_count = sentence_terminals = 0
    list_count = numeric_runs = max_numeric_sequence = unmarked_numeric_lines = 0
    for line in lines:
        tokens = list(_TOKEN.finditer(line))
        words = [
            token.group(0).casefold() for token in tokens if token.group(0)[0].isalpha()
        ]
        word_counts.append(len(words))
        word_count += len(words)
        function_count += sum(word in _FUNCTION_WORDS for word in words)
        numbers = [token for token in tokens if token.group(0)[0].isdigit()]
        marker = _LIST_MARKER.match(line)
        list_count += int(marker is not None)
        unmarked_numeric_lines += int(len(numbers) >= 2 and marker is None)
        run = 0
        for token in tokens:
            value = token.group(0)
            if value[0].isdigit():
                run += 1
                max_numeric_sequence = max(max_numeric_sequence, run)
            else:
                if run >= 2:
                    numeric_runs += 1
                run = 0
            punctuation_count += int(value in {".", "!", "?", ":", ";"})
        numeric_runs += int(run >= 2)
        sentence_terminals += int(bool(_SENTENCE_END.search(line)))
    lengths = [len(line.strip()) for line in lines if line.strip()]
    return {
        "feature_non_blank": features.non_blank,
        "feature_has_structural": features.has_structural,
        "feature_has_tab": features.has_tab,
        "feature_has_separator": features.has_separator,
        "feature_has_dot_leader": features.has_dot_leader,
        "feature_has_signature": features.has_signature,
        "feature_max_gap": features.max_gap,
        "feature_gap_row_count": len(features.gap_start_rows),
        "feature_gap_start_positions": gap_positions,
        "feature_numeric_cell_rows": len(features.numeric_cell_rows),
        "feature_shared_numeric_columns": features.shared_numeric_columns,
        "feature_numeric_cell_positions": numeric_positions,
        "feature_alpha_density": features.alpha_density,
        "feature_any_lowercase": features.any_lowercase,
        "feature_word_count": word_count,
        "feature_function_word_count": function_count,
        "feature_function_word_ratio": function_count / max(word_count, 1),
        "feature_words_per_line_mean": fmean(word_counts) if word_counts else 0.0,
        "feature_line_length_variance": pvariance(lengths) if len(lengths) > 1 else 0.0,
        "feature_sentence_punctuation_count": punctuation_count,
        "feature_sentence_terminal_lines": sentence_terminals,
        "feature_list_marker_count": list_count,
        "feature_numeric_run_count": numeric_runs,
        "feature_max_consecutive_numbers": max_numeric_sequence,
        "feature_numeric_lines_without_list_marker": unmarked_numeric_lines,
    }


def display_block_text(text: str) -> str:
    return _SIGNATURE_SENTINEL.sub(
        "[PROTECTED_SIGNATURE]", _TABLE_SENTINEL.sub("[PROTECTED_TABLE]", text)
    )


__all__ = [
    "BLOCK_SCHEMA",
    "CONTROL_ROLES",
    "FEATURE_VERSION",
    "LABELS",
    "SCHEMA_VERSION",
    "TOKEN_SCHEMA",
    "digest",
    "display_block_text",
    "feature_values",
    "jsonl_records",
    "safe_id",
    "tokenize",
]
