"""Member subsumption decided from a filing's own definition arcs."""

from __future__ import annotations

from collections.abc import Sequence

from edgar_sec.engine.xbrl.schema.models import DefinitionArc

_DIMENSION_DOMAIN = "dimension-domain"
_DIMENSION_DEFAULT = "dimension-default"
_DOMAIN_MEMBER = "domain-member"


def _arcrole_kind(arcrole: str) -> str:
    return arcrole.rsplit("/", 1)[-1]


class MemberSubsumption:
    """Axis member trees from dimension-domain and domain-member arcs.

    None abstains: axis undeclared, or a member outside its tree. The
    dimension-default target subsumes every tree member, and only itself.
    """

    def __init__(self, arcs: Sequence[DefinitionArc]) -> None:
        self._domains: dict[str, set[str]] = {}
        self._defaults: dict[str, set[str]] = {}
        self._parents: dict[str, set[str]] = {}
        self._children: dict[str, set[str]] = {}
        for arc in arcs:
            kind = _arcrole_kind(arc.arcrole)
            if kind == _DIMENSION_DOMAIN:
                self._domains.setdefault(arc.parent_qname, set()).add(arc.child_qname)
            elif kind == _DIMENSION_DEFAULT:
                self._defaults.setdefault(arc.parent_qname, set()).add(arc.child_qname)
            elif kind == _DOMAIN_MEMBER and arc.usable is not False:
                self._parents.setdefault(arc.child_qname, set()).add(arc.parent_qname)
                self._children.setdefault(arc.parent_qname, set()).add(arc.child_qname)
        self._trees: dict[str, frozenset[str]] = {}

    def default_member(self, axis: str) -> str | None:
        """The axis's declared default member, when exactly one is declared."""
        defaults = self._defaults.get(axis, set())
        return next(iter(defaults)) if len(defaults) == 1 else None

    def axis_tree(self, axis: str) -> frozenset[str]:
        """Domain and member nodes reachable from the axis's domains."""
        if axis not in self._trees:
            seen = set(self._domains.get(axis, set()))
            stack = list(seen)
            while stack:
                node = stack.pop()
                for child in self._children.get(node, set()):
                    if child not in seen:
                        seen.add(child)
                        stack.append(child)
            self._trees[axis] = frozenset(seen)
        return self._trees[axis]

    def _known(self, axis: str, node: str) -> bool:
        return node in self.axis_tree(axis) or node == self.default_member(axis)

    def is_subsumed(self, axis: str, child: str, ancestor: str) -> bool | None:
        """Whether child is subsumed by ancestor on axis; None abstains."""
        if axis not in self._domains and axis not in self._defaults:
            return None
        default = self.default_member(axis)
        if child == ancestor:
            return True if self._known(axis, child) else None
        if ancestor == default:
            return True if self._known(axis, child) else None
        if child == default:
            return False
        if not self._known(axis, child) or not self._known(axis, ancestor):
            return None
        visited: set[str] = set()
        queue = [child]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            parents = self._parents.get(node, set())
            if ancestor in parents:
                return True
            queue.extend(parents)
        return False

    def frontier(self, axis: str, members: Sequence[str]) -> tuple[str, ...] | None:
        """Members not subsumed by any other listed member; None abstains."""
        kept: list[str] = []
        for member in members:
            subsumed = False
            for other in members:
                if other == member:
                    continue
                verdict = self.is_subsumed(axis, member, other)
                if verdict is None:
                    return None
                if verdict:
                    subsumed = True
                    break
            if not subsumed:
                kept.append(member)
        return tuple(kept)
