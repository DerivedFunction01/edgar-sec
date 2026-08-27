"""Private rendering state: parameter binder, scope stack, walk guards."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

from .errors import AstCycleError, AstDepthError, ScopeError, ValidationError
from .models import SqlDialect


@dataclass
class QueryScope:
    aliases: frozenset[str]
    allow_outer: bool = True


@dataclass
class RenderContext:
    dialect: SqlDialect
    params: list[object] = field(default_factory=list)
    _next_index: int = 1
    scopes: list[QueryScope] = field(default_factory=list)
    allow_unsafe: bool = False
    allow_params: bool = True
    max_depth: int = 100
    _active: set[int] = field(default_factory=set)

    def add_param(self, value: object) -> str:
        if not self.allow_params:
            raise ValidationError("bound parameters are not permitted in DDL")
        self.params.append(value)
        index = self._next_index
        self._next_index += 1
        if self.dialect is SqlDialect.POSTGRES:
            return f"${index}"
        return "?"

    def push_scope(self, aliases: set[str], *, allow_outer: bool = True) -> None:
        self.scopes.append(QueryScope(frozenset(aliases), allow_outer))

    def pop_scope(self) -> None:
        self.scopes.pop()

    def check_qualifier(self, qualifier: str) -> None:
        for scope in reversed(self.scopes):
            if qualifier in scope.aliases:
                return
            if not scope.allow_outer:
                break
        raise ScopeError(
            f"column qualifier '{qualifier}' does not match any visible FROM alias or CTE"
        )

    def check_cycle(self, node: object) -> None:
        node_id = id(node)
        if node_id in self._active:
            raise AstCycleError("AST contains an object cycle on the active path")

    def enter(self, node: object) -> None:
        if len(self._active) >= self.max_depth:
            raise AstDepthError(
                f"AST nesting exceeds max_depth={self.max_depth}"
            )
        self.check_cycle(node)
        self._active.add(id(node))

    def leave(self, node: object) -> None:
        self._active.discard(id(node))

    @contextmanager
    def ddl(self):
        previous = self.allow_params
        self.allow_params = False
        try:
            yield
        finally:
            self.allow_params = previous
