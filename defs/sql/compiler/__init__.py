"""SQL AST compiler with recursive rendering, dialect policies, and shared parameters."""

from __future__ import annotations

from ..context import RenderContext
from ..dialects import policy_for
from ..errors import ValidationError
from ..models import CompiledQuery, SqlDialect, Statement
from .common import KNOWN_FUNCTIONS, _contains_table_reference
from .ddl import DdlCompilerMixin
from .expressions import ExpressionCompilerMixin
from .predicates import PredicateCompilerMixin
from .relations import RelationCompilerMixin
from .statements import StatementCompilerMixin


class QueryCompiler(
    ExpressionCompilerMixin,
    PredicateCompilerMixin,
    RelationCompilerMixin,
    StatementCompilerMixin,
    DdlCompilerMixin,
):
    """Dialect-neutral SQL AST compiler facade."""

    def __init__(
        self,
        dialect: SqlDialect | str = SqlDialect.SQLITE,
        *,
        allow_unsafe: bool = False,
        max_ast_depth: int = 100,
    ) -> None:
        self.dialect = SqlDialect(dialect)
        self.policy = policy_for(self.dialect)
        self.allow_unsafe = allow_unsafe
        self.max_ast_depth = max_ast_depth

    def compile(self, statement: Statement) -> CompiledQuery:
        ctx = RenderContext(
            dialect=self.dialect,
            allow_unsafe=self.allow_unsafe,
            max_depth=self.max_ast_depth,
        )
        sql = self._statement(statement, ctx).rstrip(";")
        return CompiledQuery(sql=sql, params=tuple(ctx.params), dialect=self.dialect)

    def compile_ddl_batch(
        self, statements: tuple[Statement | CompiledQuery | str, ...]
    ) -> str:
        """Join already-rendered DDL statements without adding nesting semicolons."""
        rendered = []
        for statement in statements:
            if isinstance(statement, CompiledQuery):
                rendered.append(statement.sql.strip().rstrip(";"))
            elif isinstance(statement, str):
                rendered.append(statement.strip().rstrip(";"))
            else:
                rendered.append(self.compile(statement).sql)
        return "\n\n".join(item for item in rendered if item)

    def wrap_in_transaction(self, query: CompiledQuery | str) -> CompiledQuery | str:
        """Wrap a compiled statement or SQL string in BEGIN/COMMIT."""
        if isinstance(query, str):
            return f"BEGIN;\n{query.strip().rstrip(';')}\nCOMMIT;"
        return CompiledQuery(
            sql=f"BEGIN\n{query.sql.strip().rstrip(';')}\nCOMMIT",
            params=query.params,
            dialect=query.dialect or self.dialect,
        )

    def _unsafe(self, ctx: RenderContext) -> None:
        if not ctx.allow_unsafe:
            raise ValidationError(
                "unsafe SQL requires QueryCompiler(allow_unsafe=True)"
            )


__all__ = [
    "KNOWN_FUNCTIONS",
    "QueryCompiler",
    "_contains_table_reference",
]
