"""Unit tests for the sql-interpolation policy scanner."""

from __future__ import annotations

import textwrap

from edgar_sec.foundation.scanners.base import ScannerFinding
from edgar_sec.foundation.scanners.sql_interpolation import (
    SCANNER,
    scan_sql_interpolation,
)


def _scan(tmp_path, monkeypatch, source: str, filename: str = "mod.py"):
    """Run the scanner over one synthetic module and return its findings."""
    target = tmp_path / filename
    target.write_text(textwrap.dedent(source), encoding="utf-8")
    monkeypatch.setattr(
        "edgar_sec.foundation.scanners.sql_interpolation.discover_python_files",
        lambda: [str(target)],
    )
    return scan_sql_interpolation()


def _messages(findings: list[ScannerFinding]) -> list[str]:
    return [finding.message for finding in findings]


def test_an_fstring_path_at_a_sink_is_flagged(tmp_path, monkeypatch) -> None:
    """The defect this scanner exists for: a filesystem path interpolated raw."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def assemble(paths, dest):
            listed = "[" + ", ".join(f"'{p}'" for p in paths) + "]"
            con.execute(f"SELECT * FROM read_parquet({listed})")
        """,
    )
    assert len(findings) == 1
    assert "unescaped value" in findings[0].message
    assert "sql_literal" in findings[0].hint


def test_a_bound_parameter_is_never_flagged(tmp_path, monkeypatch) -> None:
    """The safe path the rule steers toward must not itself be a finding."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def read(con, doc_id):
            con.execute("SELECT raw_payload FROM t WHERE doc_id = ?", (doc_id,))
            con.executemany("INSERT INTO t VALUES (?)", [(doc_id,)])
        """,
    )
    assert findings == []


def test_a_query_built_elsewhere_and_passed_as_a_variable_is_not_flagged(
    tmp_path, monkeypatch
) -> None:
    """The rule is about the argument at the sink, not about string building."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def run(con, paths):
            query = f"SELECT * FROM read_parquet({paths})"
            con.execute(query)
        """,
    )
    assert findings == []


def test_concatenated_sql_is_flagged(tmp_path, monkeypatch) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def read(con, doc_id):
            con.execute("SELECT raw_payload FROM t WHERE doc_id = '" + doc_id + "'")
        """,
    )
    assert len(findings) == 1


def test_percent_formatted_sql_is_flagged(tmp_path, monkeypatch) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def read(con, doc_id):
            con.execute("SELECT raw_payload FROM t WHERE doc_id = '%s'" % doc_id)
        """,
    )
    assert len(findings) == 1


def test_a_non_sql_call_with_an_fstring_is_ignored(tmp_path, monkeypatch) -> None:
    """Not every f-string is SQL; only one reaching a query sink is."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def log(path):
            print(f"reading {path}")
        """,
    )
    assert findings == []


def test_numeric_addition_is_not_string_concatenation(tmp_path, monkeypatch) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def total(a, b):
            con.execute("SELECT 1")
            return a + b
        """,
    )
    assert findings == []


def test_each_sink_name_is_covered(tmp_path, monkeypatch) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def run(con, value):
            con.execute(f"SELECT {value}")
            con.executemany(f"INSERT INTO t VALUES ({value})", [])
            cur.executescript(f"SET x = {value}")
        """,
    )
    assert len(findings) == 3


def test_the_finding_carries_path_and_line(tmp_path, monkeypatch) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        def read(con, doc_id):
            con.execute(f"SELECT {doc_id}")
        """,
        filename="pipeline.py",
    )
    assert findings[0].path.endswith("pipeline.py")
    assert findings[0].line == 3
    assert findings[0].scanner == "sql-interpolation"


def test_the_registry_exposes_the_scanner() -> None:
    from edgar_sec.foundation.scanners import ALL_SCANNERS

    assert SCANNER in ALL_SCANNERS
    assert SCANNER.name == "sql-interpolation"


def test_a_syntax_error_is_skipped_rather_than_failing_the_gate(
    tmp_path, monkeypatch
) -> None:
    findings = _scan(tmp_path, monkeypatch, "def broken(:\n")
    assert findings == []


def test_a_declared_sql_compiler_module_is_exempt(tmp_path, monkeypatch) -> None:
    """The dialect owner must be able to assemble the statement it exists to
    assemble; it is exempted by declaration, not by being the only module."""
    relative = "edgar_sec/infra/storage/duckdb.py"
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(
        textwrap.dedent(
            """
            from edgar_sec.infra.storage.duckdb import sql_literal

            def copy_out(con, query, destination):
                con.execute(
                    f"COPY ({query}) TO {sql_literal(str(destination))} "
                    f"(FORMAT PARQUET, COMPRESSION zstd)"
                )
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "edgar_sec.foundation.scanners.sql_interpolation.discover_python_files",
        lambda: [relative],
    )
    assert scan_sql_interpolation() == []


def test_every_declared_compiler_entry_names_a_real_module() -> None:
    """An allowlist entry that has been moved or deleted would silently exempt a
    path nothing occupies, and would read as coverage that does not exist."""
    import pathlib

    from edgar_sec.foundation.scanners.sql_interpolation import _SQL_COMPILER_PATHS

    root = pathlib.Path(__file__).resolve().parents[3]
    for entry in sorted(_SQL_COMPILER_PATHS):
        assert (root / entry).is_file(), entry


def test_a_value_routed_through_sql_literal_is_not_flagged(
    tmp_path, monkeypatch
) -> None:
    """The escaped spelling of the same statement must pass, or the rule cannot
    distinguish the two cases and every query site becomes an exemption."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        from edgar_sec.infra.storage.duckdb import sql_literal

        def read(con, path):
            con.execute(f"SELECT * FROM read_parquet({sql_literal(str(path))})")
        """,
    )
    assert findings == []


def test_a_value_routed_through_sql_path_list_is_not_flagged(
    tmp_path, monkeypatch
) -> None:
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        from edgar_sec.infra.storage.duckdb import sql_path_list

        def read(con, paths):
            con.execute(f"SELECT * FROM read_parquet({sql_path_list(paths)})")
        """,
    )
    assert findings == []


def test_a_join_over_escaped_literals_is_not_flagged(tmp_path, monkeypatch) -> None:
    """Assembling a list of already-escaped fragments stays safe."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        from edgar_sec.infra.storage.duckdb import sql_literal

        def read(con, paths):
            listed = ", ".join(sql_literal(str(p)) for p in paths)
            con.execute(f"SELECT * FROM read_parquet([{listed}])")
        """,
    )
    assert findings == []


def test_a_hoisted_escaped_statement_is_not_flagged(tmp_path, monkeypatch) -> None:
    """Composing the statement into a local and passing the local is the spelling
    this codebase already uses for every large query."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        from edgar_sec.infra.storage.duckdb import sql_literal

        def read(con, path, form):
            query = f"SELECT * FROM t WHERE form = {sql_literal(form)}"
            con.execute(query)
        """,
    )
    assert findings == []


def test_one_unescaped_value_among_escaped_ones_is_still_flagged(
    tmp_path, monkeypatch
) -> None:
    """Partial escaping is the case worth catching: the statement looks careful
    but one value still came from outside."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        from edgar_sec.infra.storage.duckdb import sql_literal

        def read(con, path, form):
            con.execute(
                f"SELECT * FROM read_parquet({sql_literal(str(path))}) "
                f"WHERE form = {form}"
            )
        """,
    )
    assert len(findings) == 1


def test_a_rebound_local_does_not_stay_safe(tmp_path, monkeypatch) -> None:
    """Safety is the value bound, not the name: rebinding to raw text revokes it."""
    findings = _scan(
        tmp_path,
        monkeypatch,
        """
        from edgar_sec.infra.storage.duckdb import sql_literal

        def read(con, path, raw):
            clause = f"form = {sql_literal('10-K')}"
            clause = f"form = {raw}"
            con.execute(f"SELECT * FROM t WHERE {clause}")
        """,
    )
    assert len(findings) == 1
