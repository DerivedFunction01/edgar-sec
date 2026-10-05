"""Universe-scale company-family assignment as DuckDB relations.

The retired index materialized one Python object per registrant; this assigns families
once and publishes a Parquet relation that downstream joins read directly. Normalize,
canonicalize token boundaries, classify, resolve a sponsor, then key.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from edgar_sec.domain.taxonomy.family_vocab import (
    CIK_PREFIX,
    ENTITY_PREFIX,
    INSTITUTION_ALIASES,
    MIN_SQUASH_CHARS,
    SPONSOR_BOUNDARY_WORDS,
    SPV_MARKERS,
    SPV_PREFIX,
)
from edgar_sec.engine.company_family.tokens import (
    contains_umbrella,
    has_spv_marker,
    identity_tokens,
    normalized_key,
    sponsor_candidate,
    umbrella_parent,
)

# Output columns of the published assignment, in write order.
ASSIGNMENT_COLUMNS = (
    "cik",
    "company_family",
    "family_kind",
    "sponsor_key",
    "assignment_rule",
)

KIND_ENTITY = "entity"
KIND_SPV = "spv"
KIND_SINGLETON = "singleton"

# A sponsor name is rarely longer than this, and bounding the generated truncations
# keeps the prefix join linear in candidates rather than quadratic in name length.
MAX_SPONSOR_PREFIX_TOKENS = 8


@dataclass(frozen=True, slots=True)
class FamilyAssignmentStats:
    """Coverage of one built assignment, for the cache manifest and acceptance runs."""

    registrants: int
    entity_families: int
    spv_families: int
    singletons: int
    spv_registrants: int
    unresolved_sponsors: int


def _values_relation(name: str, values: Sequence[str]) -> str:
    """A literal VALUES relation over a vocabulary, so SQL can join the word lists."""
    rows = ", ".join("('%s')" % value.replace("'", "''") for value in sorted(values))
    return f"(VALUES {rows}) AS {name}(token)"


def _alias_relation(alias: str, aliases: dict[str, str]) -> str:
    """A literal VALUES relation over the reviewed institution spellings."""
    rows = ", ".join(
        "('%s', '%s')" % (k.replace("'", "''"), v.replace("'", "''"))
        for k, v in sorted(aliases.items())
    )
    return f"(VALUES {rows}) AS {alias}(squashed, canonical)"


def register_udfs(con: duckdb.DuckDBPyConnection) -> None:
    """Register the per-name Python step; everything after it is a relation.

    Idempotent: DuckDB refuses to redefine a function, so a connection that builds
    twice would otherwise fail on the second build.
    """
    for name, fn in (
        ("fam_stem", normalized_key),
        ("fam_is_spv", has_spv_marker),
        ("fam_sponsor_candidate", sponsor_candidate),
        ("fam_umbrella_parent", umbrella_parent),
        ("fam_has_umbrella", contains_umbrella),
    ):
        kind = "BOOLEAN" if name in {"fam_is_spv", "fam_has_umbrella"} else "VARCHAR"
        try:
            con.remove_function(name)
        except duckdb.InvalidInputException:
            pass
        con.create_function(name, fn, ["VARCHAR"], kind, null_handling="special")


def _staging_sql(source: str) -> str:
    return f"""
        CREATE OR REPLACE TABLE family_staging AS
        SELECT
            lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
            CAST(name AS VARCHAR) AS company_name,
            fam_stem(name) AS stem,
            fam_is_spv(name) AS is_spv,
            fam_has_umbrella(name) AS has_umbrella,
            nullif(fam_umbrella_parent(name), '') AS umbrella_parent,
            fam_sponsor_candidate(name) AS sponsor_candidate
        FROM ({source})
        WHERE name IS NOT NULL AND trim(name) <> ''
    """


def _canonicalize_sql() -> str:
    """Collapse stems differing only in token boundaries, before classification.

    `SMART TRUST 218` and `SMARTTRUST 455` are one issuer; read spaced, the trailing
    `trust` would route one to the SPV namespace and split the family in two.
    """
    return """
        CREATE OR REPLACE TABLE family_canonical AS
        WITH squashed AS (
            SELECT stem, replace(stem, ' ', '') AS squashed, count(*) AS members
            FROM family_staging
            WHERE stem IS NOT NULL AND stem <> ''
            GROUP BY 1, 2
        )
        SELECT s.cik, s.company_name,
               coalesce(k.canonical, s.stem) AS stem,
               s.is_spv, s.has_umbrella, s.umbrella_parent, s.sponsor_candidate
        FROM family_staging s
        LEFT JOIN (
            SELECT stem,
                   first_value(stem) OVER (
                       PARTITION BY squashed ORDER BY members DESC, stem ASC
                   ) AS canonical
            FROM squashed
            WHERE length(squashed) >= {min_chars}
        ) k ON k.stem = s.stem
    """.format(min_chars=MIN_SQUASH_CHARS)


def _known_entities_sql() -> str:
    """Collect the corpus's own non-SPV entity keys, which resolve sponsors by prefix."""
    return f"""
        CREATE OR REPLACE TABLE known_entities AS
        SELECT stem, count(*) AS registrants
        FROM family_canonical
        WHERE NOT is_spv AND stem IS NOT NULL AND stem <> ''
        GROUP BY 1
    """


def _prefix_tokens_sql() -> str:
    """One row per token position of every known entity key, so prefixes are a join."""
    return """
        CREATE OR REPLACE TABLE entity_prefixes AS
        SELECT e.stem AS entity_stem,
               list_aggregate(list(t.token ORDER BY t.position), 'string_agg', ' ')
                   AS prefix
        FROM known_entities e,
             unnest(string_split(e.stem, ' ')) WITH ORDINALITY AS t(token, position)
        GROUP BY e.stem, t.position
    """


def _assign_sql() -> str:
    """Resolve each registrant's sponsor and namespace, entirely in relations."""
    return f"""
        CREATE OR REPLACE TABLE family_assignment AS
        WITH boundary AS (
            SELECT token FROM {_values_relation("b", SPONSOR_BOUNDARY_WORDS)}
        ),
        -- Tokens before the first boundary word form the sponsor candidate. It is only
        -- a fallback: a known entity prefix, then an institution alias, beat it below.
        candidate_tokens AS (
            SELECT c.cik, t.token, t.position
            FROM family_canonical c,
                 unnest(string_split(c.sponsor_candidate, ' '))
                     WITH ORDINALITY AS t(token, position)
            WHERE c.is_spv AND c.stem IS NOT NULL AND c.stem <> '' AND t.token <> ''
        ),
        first_boundary AS (
            SELECT t.cik, min(t.position) AS cut
            FROM candidate_tokens t JOIN boundary b ON b.token = t.token
            GROUP BY t.cik
        ),
        candidates AS (
            SELECT t.cik,
                   list_aggregate(list(t.token ORDER BY t.position), 'string_agg', ' ')
                       AS candidate
            FROM candidate_tokens t
            LEFT JOIN first_boundary f ON f.cik = t.cik
            WHERE t.position < coalesce(f.cut, 1e9)
            GROUP BY t.cik
        ),
        -- Alias folding runs before prefix matching, so both spellings of a sponsor
        -- resolve through the corpus's canonical entity stem.
        spelled AS (
            SELECT c.cik, c.candidate,
                   coalesce(
                       (SELECT al.canonical
                        FROM {_alias_relation("al", dict(INSTITUTION_ALIASES))}
                        WHERE al.squashed = replace(c.candidate, ' ', '')),
                       c.candidate
                   ) AS canonical
            FROM candidates c
        ),
        -- The longest known entity prefix wins, so a sponsor resolves to the corpus's
        -- own spelling rather than to whatever tokens precede a boundary word. A
        -- candidate carries trailing product words the entity name does not, so every
        -- truncation of it is generated and joined by equality: `starts_with` cannot
        -- hash, and one nested loop over the whole prefix index costs minutes.
        candidate_prefixes AS (
            SELECT s.cik, t.depth,
                   list_aggregate(list(u.token ORDER BY u.position) FILTER (
                       WHERE u.position <= t.depth
                   ), 'string_agg', ' ') AS prefix
            FROM spelled s,
                 LATERAL (SELECT unnest(range(1, least(
                     len(string_split(s.canonical, ' ')) + 1,
                     {{max_depth}} + 1))) AS depth) AS t,
                 unnest(string_split(s.canonical, ' '))
                     WITH ORDINALITY AS u(token, position)
            GROUP BY s.cik, t.depth
        ),
        longest AS (
            SELECT c.cik, p.entity_stem,
                   row_number() OVER (
                       PARTITION BY c.cik
                       ORDER BY length(p.entity_stem) DESC, p.entity_stem ASC
                   ) AS rn
            FROM candidate_prefixes c
            JOIN entity_prefixes p ON p.prefix = c.prefix
        ),
        aliased AS (
            SELECT s.cik, s.candidate, l.entity_stem AS sponsor
            FROM spelled s
            LEFT JOIN longest l ON l.cik = s.cik AND l.rn = 1
        ),
        sponsor_of AS (
            SELECT f.cik, f.stem, f.has_umbrella, f.umbrella_parent,
                   coalesce(a.candidate, f.sponsor_candidate) AS candidate,
                   coalesce(a.sponsor, '') AS matched
            FROM family_canonical f
            LEFT JOIN aliased a ON a.cik = f.cik
            WHERE f.is_spv AND f.stem IS NOT NULL AND f.stem <> ''
        ),
        keyed AS (
            SELECT s.cik, f.company_name,
                   '{SPV_PREFIX}' || s.sponsor AS company_family,
                   '{KIND_SPV}' AS family_kind,
                   s.sponsor AS sponsor_key,
                   s.rule AS assignment_rule
            FROM (
                SELECT cik, stem, has_umbrella, umbrella_parent, candidate, matched,
                       -- A name whose first token is already a boundary word has no
                       -- sponsor prefix at all. Falling back to its own stem keeps it
                       -- distinct instead of merging every such name under `spv:`.
                       CASE WHEN has_umbrella AND umbrella_parent IS NOT NULL
                            THEN umbrella_parent
                            WHEN matched <> '' THEN matched
                            WHEN candidate <> '' THEN candidate
                            ELSE stem END AS sponsor,
                       CASE WHEN has_umbrella AND umbrella_parent IS NOT NULL
                            THEN 'umbrella'
                            WHEN matched <> '' THEN 'sponsor_prefix'
                            WHEN candidate <> '' THEN 'boundary_fallback'
                            ELSE 'stem_fallback' END AS rule
                FROM sponsor_of
            ) s
            JOIN family_canonical f ON f.cik = s.cik
        )
        SELECT cik, company_name, company_family, family_kind, sponsor_key,
               assignment_rule
        FROM keyed
        UNION ALL
        SELECT f.cik, f.company_name,
               '{ENTITY_PREFIX}' || f.stem AS company_family,
               '{KIND_ENTITY}' AS family_kind,
               CAST(NULL AS VARCHAR) AS sponsor_key,
               'entity_name' AS assignment_rule
        FROM family_canonical f
        WHERE NOT f.is_spv AND f.stem IS NOT NULL AND f.stem <> ''
        UNION ALL
        SELECT f.cik, f.company_name,
               '{CIK_PREFIX}' || f.cik AS company_family,
               '{KIND_SINGLETON}' AS family_kind,
               CAST(NULL AS VARCHAR) AS sponsor_key,
               'no_identity' AS assignment_rule
        FROM family_canonical f
        WHERE f.stem IS NULL OR f.stem = ''
    """.format(max_depth=MAX_SPONSOR_PREFIX_TOKENS)


def build_assignment(
    con: duckdb.DuckDBPyConnection, roster_source: str
) -> FamilyAssignmentStats:
    """Assign a family to every registrant in ``roster_source``.

    ``roster_source`` is any relation yielding ``cik`` and ``name``, normally the
    compiled universe roster. The result is the ``family_assignment`` table.
    """
    register_udfs(con)
    con.execute(_staging_sql(roster_source))
    con.execute(_canonicalize_sql())
    con.execute(_known_entities_sql())
    con.execute(_prefix_tokens_sql())
    con.execute(_assign_sql())
    row = con.execute(
        """
        SELECT count(*) AS registrants,
               count(DISTINCT company_family) FILTER (WHERE family_kind = 'entity')
                   AS entity_families,
               count(DISTINCT company_family) FILTER (WHERE family_kind = 'spv')
                   AS spv_families,
               count(*) FILTER (WHERE family_kind = 'singleton') AS singletons,
               count(*) FILTER (WHERE family_kind = 'spv') AS spv_registrants,
               count(*) FILTER (
                   WHERE family_kind = 'spv'
                     AND (sponsor_key IS NULL OR sponsor_key = '')
               ) AS unresolved_sponsors
        FROM family_assignment
        """
    ).fetchone()
    return FamilyAssignmentStats(*(int(v or 0) for v in row))


def assignment_relation_sql(assignment_path: str | Path) -> str:
    """A relation over a published assignment, for a downstream SQL join."""
    escaped = str(Path(assignment_path)).replace("'", "''")
    return (
        "SELECT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik, company_family "
        f"FROM read_parquet('{escaped}')"
    )


__all__ = [
    "ASSIGNMENT_COLUMNS",
    "KIND_ENTITY",
    "KIND_SINGLETON",
    "KIND_SPV",
    "FamilyAssignmentStats",
    "assignment_relation_sql",
    "build_assignment",
    "register_udfs",
]
