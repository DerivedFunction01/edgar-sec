from __future__ import annotations

import pytest

from defs.sql import (
    Aggregate,
    AggregateFunction,
    Alias,
    BooleanGroup,
    BooleanOp,
    Case,
    CaseBranch,
    Cte,
    ColumnDef,
    ComparisonOp,
    CreateTable,
    DerivedTable,
    FunctionCall,
    JsonExtract,
    JsonPath,
    MatchMode,
    Membership,
    Parameter,
    QueryCompiler,
    RecursiveCte,
    ScalarSubquery,
    Select,
    SelectSource,
    SetOperator,
    Star,
    SubquerySource,
    Table,
    ValueList,
    WithClause,
    Windowed,
    col,
    lit,
    param,
)
from defs.sql.errors import ScopeError, ValidationError
from defs.sql.predicates import Compare
from defs.sql.relations import SetOperation
from defs.sql.statements import Insert, ValuesSource


def test_nested_query_shares_parameter_context_and_allows_correlation():
    inner = Select(
        source=Table("orders", "o"),
        projection=(Aggregate(AggregateFunction.COUNT, Star()),),
        where=Compare(
            col("user_id", "o"),
            ComparisonOp.EQ,
            col("id", "u"),
        ),
    )
    query = Select(
        source=Table("users", "u"),
        projection=(
            col("id", "u"),
            Alias(ScalarSubquery(inner), "order_count"),
        ),
        where=Compare(col("active", "u"), ComparisonOp.EQ, param(True)),
    )

    compiled = QueryCompiler("postgres").compile(query)

    assert 'FROM "orders" AS "o"' in compiled.sql
    assert '"o"."user_id" = "u"."id"' in compiled.sql
    assert '"u"."active" = $1' in compiled.sql
    assert compiled.params == (True,)


def test_nested_subquery_parameters_are_numbered_in_sql_order():
    inner = Select(
        source=Table("orders", "o"),
        projection=(col("id", "o"),),
        where=Compare(col("status", "o"), ComparisonOp.EQ, param("open")),
    )
    query = Select(
        source=Table("users", "u"),
        projection=(Alias(ScalarSubquery(inner), "latest"),),
        where=Compare(col("state", "u"), ComparisonOp.EQ, param("active")),
    )

    compiled = QueryCompiler("postgres").compile(query)

    assert compiled.params == ("open", "active")
    assert "$1" in compiled.sql and "$2" in compiled.sql


def test_derived_table_cannot_correlate_without_lateral():
    derived = DerivedTable(
        query=Select(
            source=Table("orders", "o"),
            projection=(col("user_id", "o"),),
            where=Compare(col("user_id", "o"), ComparisonOp.EQ, col("id", "u")),
        ),
        alias="d",
    )
    query = Select(source=derived, projection=(col("user_id", "d"),))

    with pytest.raises(ScopeError):
        QueryCompiler().compile(query)


def test_recursive_cte_uses_name_reference_not_python_object_cycle():
    recursive = RecursiveCte(
        name="descendants",
        columns=("id",),
        seed=Select(source=Table("nodes", "n"), projection=(col("id", "n"),)),
        recursive_term=Select(
            source=Table("descendants", "d"),
            projection=(col("id", "d"),),
        ),
    )
    query = Select(
        source=Table("descendants", "d"),
        projection=(col("id", "d"),),
        with_=WithClause((recursive,)),
    )

    compiled = QueryCompiler("postgres").compile(query)

    assert compiled.sql.startswith("WITH RECURSIVE")
    assert compiled.sql.count('"descendants"') >= 3


def test_set_operation_and_in_subquery_are_composable():
    branch = Select(source=Table("users"), projection=(col("id"),))
    union = SetOperation(branch, SetOperator.UNION_ALL, branch)
    query = Select(
        source=Table("orders", "o"),
        projection=(col("id", "o"),),
        where=Membership(
            value=col("user_id", "o"),
            source=SubquerySource(union),
        ),
    )

    compiled = QueryCompiler().compile(query)

    assert "IN (SELECT" in compiled.sql
    assert "UNION ALL" in compiled.sql


def test_empty_boolean_groups_preserve_source_semantics():
    query = Select(
        source=Table("users"),
        projection=(Star(),),
        where=BooleanGroup(BooleanOp.AND, ()),
    )

    assert "WHERE 1=1" in QueryCompiler().compile(query).sql


def test_empty_membership_is_rejected_before_rendering():
    with pytest.raises(ValueError, match="empty membership"):
        Membership(col("id"), ValueList(()))


def test_json_case_and_aggregate_are_separate_expression_chunks():
    query = Select(
        source=Table("filings", "f"),
        projection=(
            Case((CaseBranch(BooleanGroup(BooleanOp.AND, ()), JsonExtract(col("data", "f"), JsonPath.parse("form"))),),),
            Aggregate(AggregateFunction.COUNT, JsonExtract(col("data", "f"), JsonPath.parse("form"))),
        ),
    )

    compiled = QueryCompiler("duckdb").compile(query)

    assert "CASE WHEN 1=1" in compiled.sql
    assert "json_extract_string" in compiled.sql


def test_unsafe_expression_requires_explicit_opt_in():
    from defs.sql import UnsafeExpression

    query = Select(source=Table("users"), projection=(UnsafeExpression("1"),))

    with pytest.raises(ValidationError, match="unsafe SQL"):
        QueryCompiler().compile(query)
    assert "SELECT 1" in QueryCompiler(allow_unsafe=True).compile(query).sql


def test_insert_and_ddl_contracts_are_explicit():
    insert = Insert(
        table="users",
        columns=("name",),
        source=ValuesSource(((Parameter("Ada"),),)),
    )
    assert QueryCompiler("postgres").compile(insert).params == ("Ada",)

    table = CreateTable(
        table="users",
        columns=(ColumnDef("id", "int"), ColumnDef("name", "text")),
    )
    assert "CREATE TABLE IF NOT EXISTS" in QueryCompiler().compile(table).sql


def test_source_scalar_function_compatibility_cases():
    integer = QueryCompiler("postgres").compile(
        Select(Table("t"), (FunctionCall("to_number", (col("x"), lit("int"))),))
    )
    contains_any = QueryCompiler().compile(
        Select(
            Table("t"),
            (FunctionCall("str_contains", (col("x"), param("a"), param("b"), lit("any"))),),
        )
    )
    zero_arg = QueryCompiler().compile(Select(Table("t"), (FunctionCall("ceil", ()),)))

    assert 'CAST("x" AS INTEGER)' in integer.sql
    assert " OR " in contains_any.sql
    assert "CEIL(NULL)" in zero_arg.sql


def test_sqlite_statistical_aggregates_are_lowered():
    compiled = QueryCompiler().compile(
        Select(Table("t"), (Aggregate(AggregateFunction.STDDEV_SAMP, col("value")),))
    )

    assert "CASE WHEN COUNT" in compiled.sql
    assert "SQRT" in compiled.sql


def test_case_insensitive_prefix_match_uses_ilike_when_available():
    from defs.sql.predicates import StringMatch

    compiled = QueryCompiler("postgres").compile(
        Select(
            Table("t"),
            (Star(),),
            where=StringMatch(
                value=col("email"),
                pattern=param("a"),
                mode=MatchMode.STARTS_WITH,
                case_insensitive=True,
            ),
        )
    )

    assert "ILIKE" in compiled.sql


def test_window_and_repeated_expression_parameters_match_placeholder_order():
    from defs.sql.relations import OrderBy

    window = Select(
        Table("t"),
        (Windowed(param("operand"), (param("partition"),), (OrderBy(param("sort")),)),),
    )
    aggregate = Select(Table("t"), (Aggregate(AggregateFunction.MSE, param(2.0)),))

    window_result = QueryCompiler().compile(window)
    aggregate_result = QueryCompiler().compile(aggregate)

    assert window_result.params == ("operand", "partition", "sort")
    assert aggregate_result.sql.count("?") == len(aggregate_result.params) == 2


def test_membership_preserves_expression_values():
    query = Select(
        Table("t"),
        (Star(),),
        where=Membership(col("id"), ValueList((lit(1), param(2)))),
    )

    compiled = QueryCompiler().compile(query)

    assert "IN (1, ?)" in compiled.sql
    assert compiled.params == (2,)


def test_cte_scope_isolated_from_outer_query_aliases():
    cte = Cte(
        "recent",
        Select(
            Table("filings", "f"),
            (col("id", "f"),),
            where=Compare(col("cik", "f"), ComparisonOp.EQ, col("cik", "c")),
        ),
    )

    with pytest.raises(Exception, match="qualifier"):
        QueryCompiler().compile(
            Select(Table("companies", "c"), with_=WithClause((cte,)))
        )


def test_duckdb_ignore_does_not_combine_insert_or_ignore_and_on_conflict():
    from defs.sql.statements import DoNothing

    compiled = QueryCompiler("duckdb").compile(
        Insert("t", ("id",), ValuesSource(((param(1),),)), DoNothing())
    )

    assert "INSERT OR IGNORE" not in compiled.sql
    assert "ON CONFLICT DO NOTHING" in compiled.sql


def test_ddl_rejects_bound_parameters_and_postgres_pragma():
    from defs.sql import CreateIndex, IndexColumn, Pragma

    index = CreateIndex(
        name="idx",
        table="t",
        columns=(IndexColumn(col("value")),),
        where=Compare(col("value"), ComparisonOp.EQ, param(1)),
    )
    with pytest.raises(ValidationError, match="parameters"):
        QueryCompiler().compile(index)
    with pytest.raises(Exception, match="PRAGMA"):
        QueryCompiler("postgres").compile(Pragma("journal_mode", "WAL"))
