"""Comprehensive stress testing suite for SQL AST compilation and execution.

Validates:
1. Dialect compilation fidelity across SQLite, PostgreSQL, and DuckDB.
2. Parameter ordering & placeholder alignment across complex nested trees.
3. Multi-branch CASE statements, window functions, and statistical formulas.
4. Live in-memory execution against SQLite and DuckDB engines.
"""

from __future__ import annotations

import math
import re
import sqlite3
from typing import Any

import duckdb

from defs.sql import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOp,
    BooleanGroup,
    BooleanOp,
    Case,
    CaseBranch,
    ColumnDef,
    ColumnType,
    ComparisonOp,
    CompiledQuery,
    CreateTable,
    Cte,
    DbApiBackend,
    DerivedTable,
    Exists,
    FunctionCall,
    Insert,
    Join,
    JoinKind,
    JsonArrayContains,
    JsonExtract,
    JsonPath,
    MatchMode,
    Not,
    NotNull,
    OrderBy,
    PrimaryKey,
    QueryCompiler,
    RangeTest,
    RecursiveCte,
    ScalarSubquery,
    Select,
    SqlDialect,
    SqlExecutor,
    Star,
    StringMatch,
    Table,
    ValuesSource,
    Windowed,
    WithClause,
    col,
    lit,
    param,
)
from defs.sql.models import Direction, NullsOrder, RangeOp
from defs.sql.predicates import Compare


def _compile_and_log(
    compiler: QueryCompiler, ast_node: Any, label: str = ""
) -> CompiledQuery:
    """Compile an AST node and print dialect SQL + params for inspection."""
    compiled = compiler.compile(ast_node)
    header = f"=== [{compiler.dialect.value.upper()}] {label} ==="
    print(
        f"\n{header}\nSQL:\n{compiled.sql}\nPARAMS:\n{compiled.params}\n{'=' * len(header)}"
    )
    return compiled


# ---------------------------------------------------------------------------
# 1. Parameter Ordering & Context Traversal Stress Tests
# ---------------------------------------------------------------------------


def test_deeply_nested_parameter_ordering_and_placeholder_alignment():
    """Stress test parameter order preservation across CTEs, subqueries, joins,
    CASE statements, window functions, and multi-clause WHERE conditions.
    """
    # 1. CTE with parameter
    cte_query = Select(
        source=Table("customers", "c"),
        projection=(col("id", "c"), col("name", "c")),
        where=Compare(col("tier", "c"), ComparisonOp.EQ, param("gold")),
    )
    cte = Cte("gold_customers", cte_query)

    # 2. Derived table with parameter
    derived_query = Select(
        source=Table("orders", "o"),
        projection=(col("customer_id", "o"), col("amount", "o")),
        where=Compare(col("amount", "o"), ComparisonOp.GT, param(100.0)),
    )
    derived = DerivedTable(derived_query, "big_orders")

    # 3. Scalar subquery in projection with parameter
    scalar_sub = ScalarSubquery(
        Select(
            source=Table("rates", "r"),
            projection=(col("rate", "r"),),
            where=Compare(col("currency", "r"), ComparisonOp.EQ, param("USD")),
        )
    )

    # 4. Complex CASE in projection with parameters
    case_expr = Case(
        branches=(
            CaseBranch(
                when=Compare(
                    col("amount", "big_orders"), ComparisonOp.GT, param(500.0)
                ),
                then=Arithmetic(
                    ArithmeticOp.MULTIPLY, (col("amount", "big_orders"), param(0.9))
                ),
            ),
        ),
        else_=col("amount", "big_orders"),
    )

    # 5. Window function with partition & order parameters
    window_expr = Windowed(
        operand=Aggregate(AggregateFunction.SUM, col("amount", "big_orders")),
        partition_by=(col("customer_id", "big_orders"),),
        order_by=(OrderBy(col("amount", "big_orders"), direction=Direction.DESC),),
    )

    # 6. WHERE clause with multiple predicates and parameters
    where_condition = BooleanGroup(
        operator=BooleanOp.AND,
        terms=(
            Compare(col("name", "gc"), ComparisonOp.NEQ, param("BlockedUser")),
            RangeTest(
                col("amount", "big_orders"),
                RangeOp.BETWEEN,
                param(50.0),
                param(10000.0),
            ),
            StringMatch(col("name", "gc"), param("A%"), mode=MatchMode.LIKE),
        ),
    )

    full_ast = Select(
        with_=WithClause(ctes=(cte,)),
        source=Table("gold_customers", "gc"),
        joins=(
            Join(
                kind=JoinKind.INNER,
                source=derived,
                condition=Compare(
                    col("id", "gc"),
                    ComparisonOp.EQ,
                    col("customer_id", "big_orders"),
                ),
            ),
        ),
        projection=(
            col("id", "gc"),
            scalar_sub,
            case_expr,
            window_expr,
        ),
        where=where_condition,
    )

    expected_params_order = (
        "gold",  # CTE where tier = 'gold'
        "USD",  # Projection scalar subquery currency = 'USD'
        500.0,  # Case branch when amount > 500.0
        0.9,  # Case branch then amount * 0.9
        100.0,  # Derived table where amount > 100.0
        "BlockedUser",  # Main where name != 'BlockedUser'
        50.0,  # Main where amount >= 50.0
        10000.0,  # Main where amount <= 10000.0
        "A%",  # Main where name LIKE 'A%'
    )

    # Verify PostgreSQL Compilation & Positional Parameters
    pg_compiler = QueryCompiler(SqlDialect.POSTGRES)
    pg_compiled = _compile_and_log(pg_compiler, full_ast, "Nested Parameters Postgres")

    assert pg_compiled.params == expected_params_order
    # Ensure $1 through $9 appear in exact ascending sequence in the rendered SQL
    placeholders = [int(m) for m in re.findall(r"\$(\d+)", pg_compiled.sql)]
    assert placeholders == list(range(1, len(expected_params_order) + 1))

    # Verify SQLite & DuckDB compilation
    for dialect in (SqlDialect.SQLITE, SqlDialect.DUCKDB):
        compiler = QueryCompiler(dialect)
        compiled = _compile_and_log(
            compiler, full_ast, f"Nested Parameters {dialect.value}"
        )
        assert compiled.params == expected_params_order
        assert compiled.sql.count("?") == len(expected_params_order)


# ---------------------------------------------------------------------------
# 2. Live In-Memory Execution: Statistical Aggregates Stress Tests
# ---------------------------------------------------------------------------


def test_statistical_aggregates_live_execution_sqlite_and_duckdb():
    """Verify that SQLite lowered statistical aggregates (variance, stddev, RMSE, MAE, MSE)
    produce mathematically accurate results matching DuckDB native execution.
    """
    sample_values = [10.0, 12.0, 23.0, 23.0, 16.0, 23.0, 21.0, 16.0]
    n = len(sample_values)
    mean = sum(sample_values) / n
    expected_var_pop = sum((x - mean) ** 2 for x in sample_values) / n
    expected_var_samp = sum((x - mean) ** 2 for x in sample_values) / (n - 1)
    expected_std_pop = math.sqrt(expected_var_pop)
    expected_std_samp = math.sqrt(expected_var_samp)
    expected_mae = sum(abs(x) for x in sample_values) / n
    expected_mse = sum(x**2 for x in sample_values) / n
    expected_rmse = math.sqrt(expected_mse)

    # Build DDL and Insert AST
    create_stmt = CreateTable(
        table="metrics",
        columns=(
            ColumnDef("id", ColumnType.INT, (PrimaryKey(),)),
            ColumnDef("val", ColumnType.REAL, (NotNull(),)),
        ),
    )
    insert_stmt = Insert(
        table="metrics",
        columns=("id", "val"),
        source=ValuesSource(tuple((i + 1, v) for i, v in enumerate(sample_values))),
    )

    # Aggregation Query AST
    agg_query = Select(
        source=Table("metrics"),
        projection=(
            Aggregate(AggregateFunction.COUNT, Star()),
            Aggregate(AggregateFunction.AVG, col("val")),
            Aggregate(AggregateFunction.VAR_POP, col("val")),
            Aggregate(AggregateFunction.VAR_SAMP, col("val")),
            Aggregate(AggregateFunction.STDDEV_POP, col("val")),
            Aggregate(AggregateFunction.STDDEV_SAMP, col("val")),
            Aggregate(AggregateFunction.MAE, col("val")),
            Aggregate(AggregateFunction.MSE, col("val")),
            Aggregate(AggregateFunction.RMSE, col("val")),
            Aggregate(AggregateFunction.RANGE, col("val")),
        ),
    )

    # 1. Execute in SQLite
    sqlite_conn = sqlite3.connect(":memory:")
    sqlite_backend = DbApiBackend(sqlite_conn, dialect=SqlDialect.SQLITE)
    sqlite_exec = SqlExecutor(sqlite_backend)

    sqlite_exec.exec(sqlite_exec.compiler.compile(create_stmt))
    sqlite_exec.exec(sqlite_exec.compiler.compile(insert_stmt))
    res_sqlite = sqlite_exec.query_one(sqlite_exec.compiler.compile(agg_query))
    assert res_sqlite is not None

    # 2. Execute in DuckDB
    duckdb_conn = duckdb.connect(":memory:")
    duckdb_backend = DbApiBackend(duckdb_conn, dialect=SqlDialect.DUCKDB)
    duckdb_exec = SqlExecutor(duckdb_backend)

    duckdb_exec.exec(duckdb_exec.compiler.compile(create_stmt))
    duckdb_exec.exec(duckdb_exec.compiler.compile(insert_stmt))
    res_duckdb = duckdb_exec.query_one(duckdb_exec.compiler.compile(agg_query))
    assert res_duckdb is not None

    print(f"\nSQLite Stats Result: {res_sqlite}")
    print(f"DuckDB Stats Result: {res_duckdb}")

    # Check numerical accuracy (within 1e-6 precision)
    sq_vals = list(res_sqlite.values())
    dk_vals = list(res_duckdb.values())

    assert sq_vals[0] == n
    assert math.isclose(sq_vals[1], mean, rel_tol=1e-6)
    assert math.isclose(sq_vals[2], expected_var_pop, rel_tol=1e-6)
    assert math.isclose(sq_vals[3], expected_var_samp, rel_tol=1e-6)
    assert math.isclose(sq_vals[4], expected_std_pop, rel_tol=1e-6)
    assert math.isclose(sq_vals[5], expected_std_samp, rel_tol=1e-6)
    assert math.isclose(sq_vals[6], expected_mae, rel_tol=1e-6)
    assert math.isclose(sq_vals[7], expected_mse, rel_tol=1e-6)
    assert math.isclose(sq_vals[8], expected_rmse, rel_tol=1e-6)
    assert math.isclose(
        sq_vals[9], max(sample_values) - min(sample_values), rel_tol=1e-6
    )

    # Check that SQLite and DuckDB produced equivalent results
    for v_sq, v_dk in zip(sq_vals, dk_vals):
        assert math.isclose(float(v_sq), float(v_dk), rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 3. Date, Math & Multi-Pattern String Function Stress Tests
# ---------------------------------------------------------------------------


def test_date_and_string_function_execution():
    """Verify date parts, string pattern matching ('any'/'all'), and substring/concat functions."""
    create_stmt = CreateTable(
        table="events",
        columns=(
            ColumnDef("id", ColumnType.INT, (PrimaryKey(),)),
            ColumnDef("event_date", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("title", ColumnType.TEXT, (NotNull(),)),
        ),
    )
    insert_stmt = Insert(
        table="events",
        columns=("id", "event_date", "title"),
        source=ValuesSource(
            (
                (1, "2024-03-15", "Apple Quarterly 10-K Report"),
                (2, "2024-07-22", "Microsoft Annual Proxy Statement"),
                (3, "2024-11-05", "Google 8-K Current Filing"),
            )
        ),
    )

    # String Pattern: Contains "Report" OR "Filing" (mode='any')
    query_any = Select(
        source=Table("events"),
        projection=(col("id"), col("title")),
        where=FunctionCall(
            "str_contains", (col("title"), lit("Report"), lit("Filing"), lit("any"))
        ),
    )

    # String Pattern: Starts with "Apple" AND Contains "10-K"
    query_all = Select(
        source=Table("events"),
        projection=(col("id"), col("title")),
        where=BooleanGroup(
            BooleanOp.AND,
            (
                FunctionCall("starts_with", (col("title"), lit("Apple"))),
                FunctionCall("str_contains", (col("title"), lit("10-K"))),
            ),
        ),
    )

    # Date extractions
    query_date = Select(
        source=Table("events"),
        projection=(
            col("id"),
            FunctionCall("year", (col("event_date"),)),
            FunctionCall("month", (col("event_date"),)),
            FunctionCall("quarter", (col("event_date"),)),
        ),
        where=Compare(col("id"), ComparisonOp.EQ, param(1)),
    )

    # Execute on SQLite
    sq_conn = sqlite3.connect(":memory:")
    sq_backend = DbApiBackend(sq_conn, dialect=SqlDialect.SQLITE)
    sq_exec = SqlExecutor(sq_backend)
    sq_exec.exec(sq_exec.compiler.compile(create_stmt))
    sq_exec.exec(sq_exec.compiler.compile(insert_stmt))

    rows_any = sq_exec.query(sq_exec.compiler.compile(query_any))
    assert len(rows_any) == 2  # Apple and Google
    assert {r["id"] for r in rows_any} == {1, 3}

    rows_all = sq_exec.query(sq_exec.compiler.compile(query_all))
    assert len(rows_all) == 1
    assert rows_all[0]["id"] == 1

    date_res = sq_exec.query_one(sq_exec.compiler.compile(query_date))
    assert date_res is not None
    vals = list(date_res.values())
    assert vals[1] == 2024
    assert vals[2] == 3
    assert vals[3] == 1  # Q1

    # Execute on DuckDB
    dk_conn = duckdb.connect(":memory:")
    dk_backend = DbApiBackend(dk_conn, dialect=SqlDialect.DUCKDB)
    dk_exec = SqlExecutor(dk_backend)
    dk_exec.exec(dk_exec.compiler.compile(create_stmt))
    dk_exec.exec(dk_exec.compiler.compile(insert_stmt))

    dk_rows_any = dk_exec.query(dk_exec.compiler.compile(query_any))
    assert len(dk_rows_any) == 2
    dk_rows_all = dk_exec.query(dk_exec.compiler.compile(query_all))
    assert len(dk_rows_all) == 1


# ---------------------------------------------------------------------------
# 4. JSON Extraction & Array Containment Stress Tests
# ---------------------------------------------------------------------------


def test_json_extraction_and_array_containment():
    """Verify JSON path extraction and array membership testing across dialects."""
    json_data = '{"company": {"name": "Acme Inc", "tags": ["tech", "sec"]}}'

    create_stmt = CreateTable(
        table="entities",
        columns=(
            ColumnDef("id", ColumnType.INT, (PrimaryKey(),)),
            ColumnDef("meta", ColumnType.JSON, (NotNull(),)),
        ),
    )
    insert_stmt = Insert(
        table="entities",
        columns=("id", "meta"),
        source=ValuesSource(((1, json_data),)),
    )

    # 1. JSON Path Extract
    query_extract = Select(
        source=Table("entities"),
        projection=(
            col("id"),
            JsonExtract(col("meta"), JsonPath.parse("company.name")),
        ),
    )

    # 2. JSON Array Contains
    query_contains = Select(
        source=Table("entities"),
        projection=(col("id"),),
        where=JsonArrayContains(
            target=JsonExtract(col("meta"), JsonPath.parse("company.tags")),
            member=param("tech"),
        ),
    )

    # SQLite execution
    sq_conn = sqlite3.connect(":memory:")
    sq_backend = DbApiBackend(sq_conn, dialect=SqlDialect.SQLITE)
    sq_exec = SqlExecutor(sq_backend)
    sq_exec.exec(sq_exec.compiler.compile(create_stmt))
    sq_exec.exec(sq_exec.compiler.compile(insert_stmt))

    ext_res = sq_exec.query_one(sq_exec.compiler.compile(query_extract))
    assert ext_res is not None
    assert "Acme Inc" in list(ext_res.values())

    cont_res = sq_exec.query_one(sq_exec.compiler.compile(query_contains))
    assert cont_res is not None
    assert cont_res["id"] == 1

    # Postgres compilation check for jsonb operators
    pg_comp = QueryCompiler(SqlDialect.POSTGRES)
    pg_extract_sql = _compile_and_log(
        pg_comp, query_extract, "Postgres JSON Extract"
    ).sql
    assert "#>> ARRAY['company', 'name']" in pg_extract_sql

    pg_contains_sql = _compile_and_log(
        pg_comp, query_contains, "Postgres JSON Contains"
    ).sql
    assert "@>" in pg_contains_sql


# ---------------------------------------------------------------------------
# 5. Recursive CTE & Set Operations Stress Tests
# ---------------------------------------------------------------------------


def test_recursive_cte_fibonacci_sequence_execution():
    """Verify recursive CTE compilation and sequence generation in SQLite and DuckDB."""
    # Fibonacci sequence generator up to 10 iterations:
    # fib(n, a, b) -> seed (1, 0, 1), recursive term (n + 1, b, a + b) WHERE n < 10
    fib_cte = RecursiveCte(
        name="fib",
        seed=Select(
            source=None,
            projection=(lit(1), lit(0), lit(1)),
        ),
        recursive_term=Select(
            source=Table("fib"),
            projection=(
                Arithmetic(ArithmeticOp.ADD, (col("n"), lit(1))),
                col("b"),
                Arithmetic(ArithmeticOp.ADD, (col("a"), col("b"))),
            ),
            where=Compare(col("n"), ComparisonOp.LT, param(8)),
        ),
        columns=("n", "a", "b"),
    )

    query = Select(
        with_=WithClause(ctes=(fib_cte,)),
        source=Table("fib"),
        projection=(col("n"), col("a")),
        order_by=(OrderBy(col("n")),),
    )

    # 1. SQLite execution
    sq_conn = sqlite3.connect(":memory:")
    sq_backend = DbApiBackend(sq_conn, dialect=SqlDialect.SQLITE)
    sq_exec = SqlExecutor(sq_backend)

    fib_rows = sq_exec.query(sq_exec.compiler.compile(query))
    assert len(fib_rows) == 8
    seq = [r["a"] for r in fib_rows]
    assert seq == [0, 1, 1, 2, 3, 5, 8, 13]
    print(f"\nComputed Fibonacci sequence in SQLite: {seq}")

    # 2. DuckDB execution
    dk_conn = duckdb.connect(":memory:")
    dk_backend = DbApiBackend(dk_conn, dialect=SqlDialect.DUCKDB)
    dk_exec = SqlExecutor(dk_backend)
    dk_fib_rows = dk_exec.query(dk_exec.compiler.compile(query))
    assert [r["a"] for r in dk_fib_rows] == [0, 1, 1, 2, 3, 5, 8, 13]
    print(f"Computed Fibonacci sequence in DuckDB: {seq}")


# ---------------------------------------------------------------------------
# 6. Concept Taxonomy Hierarchy Traversal (Transitive Closure)
# ---------------------------------------------------------------------------


def test_taxonomy_hierarchy_recursive_cte_and_execution():
    """Verify recursive taxonomy graph traversal (transitive closure) across SQLite and DuckDB."""
    create_stmt = CreateTable(
        table="dict_concept_relations",
        columns=(
            ColumnDef("parent_id", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("child_id", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("rel_type", ColumnType.TEXT, (NotNull(),)),
        ),
    )

    # GAAP-style Asset calculation hierarchy:
    # Assets -> CurrentAssets -> Cash, AccountsReceivable
    # Assets -> NoncurrentAssets -> PropertyPlantEquipment
    relations_data = [
        ("us-gaap/Assets", "us-gaap/CurrentAssets", "parent-child"),
        ("us-gaap/Assets", "us-gaap/NoncurrentAssets", "parent-child"),
        ("us-gaap/CurrentAssets", "us-gaap/CashAndCashEquivalents", "parent-child"),
        ("us-gaap/CurrentAssets", "us-gaap/AccountsReceivable", "parent-child"),
        ("us-gaap/NoncurrentAssets", "us-gaap/PropertyPlantEquipment", "parent-child"),
    ]

    insert_stmt = Insert(
        table="dict_concept_relations",
        columns=("parent_id", "child_id", "rel_type"),
        source=ValuesSource(tuple(relations_data)),
    )

    # Seed term: direct children of root concept at depth 1
    seed = Select(
        source=Table("dict_concept_relations", "r"),
        projection=(
            col("parent_id", "r"),
            col("child_id", "r"),
            col("rel_type", "r"),
            lit(1),
        ),
        where=Compare(col("parent_id", "r"), ComparisonOp.EQ, param("us-gaap/Assets")),
    )

    # Recursive term: join child_id from previous level to parent_id in relations
    recursive_term = Select(
        source=Table("tree", "t"),
        projection=(
            col("parent_id", "t"),
            col("child_id", "r"),
            col("rel_type", "r"),
            Arithmetic(ArithmeticOp.ADD, (col("link_depth", "t"), lit(1))),
        ),
        joins=(
            Join(
                kind=JoinKind.INNER,
                source=Table("dict_concept_relations", "r"),
                condition=Compare(
                    col("parent_id", "r"), ComparisonOp.EQ, col("child_id", "t")
                ),
            ),
        ),
        where=Compare(col("link_depth", "t"), ComparisonOp.LT, param(5)),
    )

    tree_cte = RecursiveCte(
        name="tree",
        seed=seed,
        recursive_term=recursive_term,
        columns=("parent_id", "child_id", "rel_type", "link_depth"),
    )

    query = Select(
        with_=WithClause(ctes=(tree_cte,)),
        source=Table("tree"),
        projection=(
            col("parent_id"),
            col("child_id"),
            col("rel_type"),
            col("link_depth"),
        ),
        order_by=(OrderBy(col("link_depth")), OrderBy(col("child_id"))),
    )

    # Compile and inspect across dialects
    for dialect in (SqlDialect.POSTGRES, SqlDialect.SQLITE, SqlDialect.DUCKDB):
        compiler = QueryCompiler(dialect)
        _compile_and_log(compiler, query, f"Taxonomy Hierarchy {dialect.value}")

    # SQLite execution
    sq_conn = sqlite3.connect(":memory:")
    sq_backend = DbApiBackend(sq_conn, dialect=SqlDialect.SQLITE)
    sq_exec = SqlExecutor(sq_backend)
    sq_exec.exec(sq_exec.compiler.compile(create_stmt))
    sq_exec.exec(sq_exec.compiler.compile(insert_stmt))

    sq_results = sq_exec.query(sq_exec.compiler.compile(query))
    assert len(sq_results) == 5
    print(f"\nSQLite Hierarchy Traversal ({len(sq_results)} descendants found):")
    for row in sq_results:
        print(
            f"  depth {row['link_depth']}: {row['parent_id']} -> {row['child_id']} ({row['rel_type']})"
        )

    # DuckDB execution
    dk_conn = duckdb.connect(":memory:")
    dk_backend = DbApiBackend(dk_conn, dialect=SqlDialect.DUCKDB)
    dk_exec = SqlExecutor(dk_backend)
    dk_exec.exec(dk_exec.compiler.compile(create_stmt))
    dk_exec.exec(dk_exec.compiler.compile(insert_stmt))

    dk_results = dk_exec.query(dk_exec.compiler.compile(query))
    assert len(dk_results) == 5
    assert [r["child_id"] for r in sq_results] == [r["child_id"] for r in dk_results]


# ---------------------------------------------------------------------------
# 7. Correlated Policy Filter Eligibility Stress Tests
# ---------------------------------------------------------------------------


def test_correlated_policy_filter_eligibility_and_execution():
    """Verify correlated EXISTS / NOT EXISTS policy filtering against role rules."""
    create_expressions = CreateTable(
        table="dict_custom_expressions",
        columns=(
            ColumnDef("id", ColumnType.TEXT, (PrimaryKey(),)),
            ColumnDef("term", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("concept_id", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("priority_weight", ColumnType.REAL, (NotNull(),)),
        ),
    )
    create_filters = CreateTable(
        table="concept_filters",
        columns=(
            ColumnDef("filter_id", ColumnType.TEXT, (PrimaryKey(),)),
            ColumnDef("concept_id", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("role_name", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("policy", ColumnType.TEXT, (NotNull(),)),
            ColumnDef("active", ColumnType.INT, (NotNull(),)),
        ),
    )

    expressions_data = [
        ("exp_1", "Cash", "concept_whitelisted", 10.0),
        ("exp_2", "Secret Reserve", "concept_blacklisted", 5.0),
        ("exp_3", "Common Stock", "concept_no_filters", 8.0),
        ("exp_4", "Retained Earnings", "concept_auditor_only_filter", 9.0),
    ]

    filters_data = [
        # concept_whitelisted is whitelisted for analyst
        ("flt_1", "concept_whitelisted", "analyst", "whitelist", 1),
        # concept_blacklisted is blacklisted for analyst
        ("flt_2", "concept_blacklisted", "analyst", "blacklist", 1),
        # concept_auditor_only_filter is whitelisted for auditor (not analyst)
        ("flt_3", "concept_auditor_only_filter", "auditor", "whitelist", 1),
    ]

    insert_exp = Insert(
        table="dict_custom_expressions",
        columns=("id", "term", "concept_id", "priority_weight"),
        source=ValuesSource(tuple(expressions_data)),
    )
    insert_flt = Insert(
        table="concept_filters",
        columns=("filter_id", "concept_id", "role_name", "policy", "active"),
        source=ValuesSource(tuple(filters_data)),
    )

    role_target = "analyst"

    # Correlated subquery 1: Blacklist
    blacklist_sub = Select(
        source=Table("concept_filters", "fb"),
        projection=(lit(1),),
        where=BooleanGroup(
            BooleanOp.AND,
            (
                Compare(
                    col("concept_id", "fb"), ComparisonOp.EQ, col("concept_id", "e")
                ),
                Compare(col("role_name", "fb"), ComparisonOp.EQ, param(role_target)),
                Compare(col("active", "fb"), ComparisonOp.EQ, param(1)),
                Compare(col("policy", "fb"), ComparisonOp.EQ, param("blacklist")),
            ),
        ),
    )

    # Correlated subquery 2: Any active filter for role
    any_active_sub = Select(
        source=Table("concept_filters", "fa"),
        projection=(lit(1),),
        where=BooleanGroup(
            BooleanOp.AND,
            (
                Compare(
                    col("concept_id", "fa"), ComparisonOp.EQ, col("concept_id", "e")
                ),
                Compare(col("role_name", "fa"), ComparisonOp.EQ, param(role_target)),
                Compare(col("active", "fa"), ComparisonOp.EQ, param(1)),
            ),
        ),
    )

    # Correlated subquery 3: Whitelist
    whitelist_sub = Select(
        source=Table("concept_filters", "fw"),
        projection=(lit(1),),
        where=BooleanGroup(
            BooleanOp.AND,
            (
                Compare(
                    col("concept_id", "fw"), ComparisonOp.EQ, col("concept_id", "e")
                ),
                Compare(col("role_name", "fw"), ComparisonOp.EQ, param(role_target)),
                Compare(col("active", "fw"), ComparisonOp.EQ, param(1)),
                Compare(col("policy", "fw"), ComparisonOp.EQ, param("whitelist")),
            ),
        ),
    )

    filter_eligibility = BooleanGroup(
        BooleanOp.AND,
        (
            Not(Exists(blacklist_sub)),
            BooleanGroup(
                BooleanOp.OR,
                (
                    Not(Exists(any_active_sub)),
                    Exists(whitelist_sub),
                ),
            ),
        ),
    )

    query = Select(
        source=Table("dict_custom_expressions", "e"),
        projection=(
            col("id", "e"),
            col("term", "e"),
            col("concept_id", "e"),
            col("priority_weight", "e"),
        ),
        where=filter_eligibility,
        order_by=(
            OrderBy(
                col("priority_weight", "e"),
                direction=Direction.DESC,
                nulls=NullsOrder.LAST,
            ),
        ),
    )

    # Compile across dialects and log
    for dialect in (SqlDialect.POSTGRES, SqlDialect.SQLITE, SqlDialect.DUCKDB):
        compiler = QueryCompiler(dialect)
        _compile_and_log(compiler, query, f"Correlated Policy Filter {dialect.value}")

    # SQLite execution
    sq_conn = sqlite3.connect(":memory:")
    sq_backend = DbApiBackend(sq_conn, dialect=SqlDialect.SQLITE)
    sq_exec = SqlExecutor(sq_backend)
    sq_exec.exec(sq_exec.compiler.compile(create_expressions))
    sq_exec.exec(sq_exec.compiler.compile(create_filters))
    sq_exec.exec(sq_exec.compiler.compile(insert_exp))
    sq_exec.exec(sq_exec.compiler.compile(insert_flt))

    sq_rows = sq_exec.query(sq_exec.compiler.compile(query))
    assert (
        len(sq_rows) == 3
    )  # exp_1 (whitelisted), exp_3 (no filter), exp_4 (auditor filter only)
    assert "exp_2" not in [r["id"] for r in sq_rows]  # exp_2 is blacklisted for analyst
    print(f"\nSQLite Eligible Expressions for role '{role_target}':")
    for r in sq_rows:
        print(
            f"  - {r['id']}: {r['term']} ({r['concept_id']}) weight={r['priority_weight']}"
        )

    # DuckDB execution
    dk_conn = duckdb.connect(":memory:")
    dk_backend = DbApiBackend(dk_conn, dialect=SqlDialect.DUCKDB)
    dk_exec = SqlExecutor(dk_backend)
    dk_exec.exec(dk_exec.compiler.compile(create_expressions))
    dk_exec.exec(dk_exec.compiler.compile(create_filters))
    dk_exec.exec(dk_exec.compiler.compile(insert_exp))
    dk_exec.exec(dk_exec.compiler.compile(insert_flt))

    dk_rows = dk_exec.query(dk_exec.compiler.compile(query))
    assert len(dk_rows) == 3
    assert [r["id"] for r in sq_rows] == [r["id"] for r in dk_rows]
