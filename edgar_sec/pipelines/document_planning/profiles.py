"""Load and normalize immutable document-target profiles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.pipelines.document_planning.paths import (
    resolve_document_planning_paths,
    validate_profile_id,
)
from edgar_sec.pipelines.document_planning.schemas import PROFILE_SCHEMA_VERSION

_ROLES = {"primary", "exhibit", "data_file", "graphic", "package"}
_CODE_TYPE_RE = re.compile(r"EX-[A-Z0-9]+(?:\.[A-Z0-9]+)*\Z", re.ASCII)
_EXHIBIT_PREFIX_RE = re.compile(r"EX-(?:\*|10\.\*)\Z", re.ASCII)
_TARGET_KEYS = {"role", "type", "optional"}
_RULE_KEYS = {"form_selector", "targets"}
_PROFILE_KEYS = {"profile_id", "schema_version", "version", "rules"}


@dataclass(frozen=True, slots=True)
class ProfileTarget:
    role: str
    type: str
    optional: bool
    request_id: str


@dataclass(frozen=True, slots=True)
class ProfileRule:
    form_selector: str
    targets: tuple[ProfileTarget, ...]


@dataclass(frozen=True, slots=True)
class ResolvedProfile:
    profile_id: str
    schema_version: str
    version: str
    digest: str
    rules: tuple[ProfileRule, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredProfile:
    profile_id: str
    path: Path
    profile: ResolvedProfile | None
    error: str | None

    @property
    def valid(self) -> bool:
        return self.profile is not None


def _normalize_form(token: str) -> str:
    cleaned = token.strip().upper()
    if not cleaned:
        raise ValueError("form_selector contains an empty token")
    if cleaned == "*":
        return cleaned
    return resolve_alias(cleaned) or cleaned


def _selector_tokens(selector: Any) -> tuple[str, ...]:
    if not isinstance(selector, str):
        raise ValueError("form_selector must be a string")
    tokens = tuple(_normalize_form(part) for part in selector.split(","))
    if len(tokens) != len(set(tokens)):
        raise ValueError(f"duplicate form token in selector: {selector!r}")
    if "*" in tokens and len(tokens) != 1:
        raise ValueError("wildcard form selector cannot be combined with forms")
    return tuple(sorted(tokens))


def _validate_target_type(role: str, target_type: str) -> None:
    if role == "primary" and target_type == "primary":
        return
    if role == "exhibit" and (
        _CODE_TYPE_RE.fullmatch(target_type)
        or _EXHIBIT_PREFIX_RE.fullmatch(target_type)
    ):
        return
    if role == "data_file" and (
        _CODE_TYPE_RE.fullmatch(target_type)
        or target_type == "extracted_xbrl_instance"
        or target_type == "EX-101.*"
    ):
        return
    if role == "graphic" and target_type == "GRAPHIC":
        return
    if role == "package" and target_type == "xbrl_zip":
        return
    raise ValueError(f"invalid role/type pair: {role!r}/{target_type!r}")


def _target_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    left_prefix = left[:-1] if left.endswith("*") else None
    right_prefix = right[:-1] if right.endswith("*") else None
    if left_prefix is not None and right_prefix is not None:
        return left_prefix.startswith(right_prefix) or right_prefix.startswith(
            left_prefix
        )
    if left_prefix is not None:
        return right.startswith(left_prefix)
    if right_prefix is not None:
        return left.startswith(right_prefix)
    return False


def _parse_target(raw: Any) -> ProfileTarget:
    if not isinstance(raw, dict) or set(raw) != _TARGET_KEYS:
        raise ValueError("each target must contain exactly role, type, and optional")
    role, raw_type, optional = raw["role"], raw["type"], raw["optional"]
    if not isinstance(role, str) or role not in _ROLES:
        raise ValueError(f"invalid target role: {role!r}")
    if not isinstance(raw_type, str) or not raw_type.strip():
        raise ValueError("target type must be a non-empty string")
    target_type = raw_type.strip()
    if type(optional) is not bool:
        raise ValueError("target optional must be a boolean")
    _validate_target_type(role, target_type)
    return ProfileTarget(role, target_type, optional, f"{role}:{target_type}")


def _parse_rule(raw: Any) -> tuple[ProfileRule, tuple[str, ...]]:
    if not isinstance(raw, dict) or set(raw) != _RULE_KEYS:
        raise ValueError("each rule must contain exactly form_selector and targets")
    tokens = _selector_tokens(raw["form_selector"])
    raw_targets = raw["targets"]
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError("rule targets must be a non-empty array")
    targets = tuple(_parse_target(target) for target in raw_targets)
    for index, target in enumerate(targets):
        for other in targets[index + 1 :]:
            if target.role == other.role and _target_overlap(target.type, other.type):
                raise ValueError(
                    f"overlapping targets in rule: {target.role}:{target.type} and "
                    f"{other.role}:{other.type}"
                )
    return ProfileRule(", ".join(tokens), targets), tokens


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _profile_from_data(data: Any, expected_id: str) -> ResolvedProfile:
    if not isinstance(data, dict) or set(data) != _PROFILE_KEYS:
        raise ValueError(
            "profile must contain exactly profile_id, schema_version, version, and rules"
        )
    profile_id = data["profile_id"]
    validate_profile_id(profile_id)
    if profile_id != expected_id:
        raise ValueError(
            f"profile_id {profile_id!r} does not match filename stem {expected_id!r}"
        )
    schema_version = data["schema_version"]
    if schema_version != PROFILE_SCHEMA_VERSION:
        raise ValueError(f"unsupported profile schema_version: {schema_version!r}")
    version = data["version"]
    if not isinstance(version, str) or not version.strip():
        raise ValueError("profile version must be a non-empty string")
    raw_rules = data["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ValueError("profile rules must be a non-empty array")
    parsed: list[tuple[ProfileRule, tuple[str, ...]]] = [
        _parse_rule(rule) for rule in raw_rules
    ]
    seen: set[str] = set()
    for _rule, tokens in parsed:
        overlap = seen.intersection(tokens)
        if overlap:
            raise ValueError(f"overlapping form rules: {', '.join(sorted(overlap))}")
        seen.update(tokens)
    rules = tuple(
        sorted(
            (rule for rule, _tokens in parsed),
            key=lambda rule: rule.form_selector,
        )
    )
    canonical = {
        "profile_id": profile_id,
        "schema_version": schema_version,
        "version": version.strip(),
        "rules": [
            {
                "form_selector": rule.form_selector,
                "targets": [
                    {
                        "role": target.role,
                        "type": target.type,
                        "optional": target.optional,
                    }
                    for target in sorted(
                        rule.targets,
                        key=lambda item: (item.role, item.type, item.optional),
                    )
                ],
            }
            for rule in rules
        ],
    }
    digest = hashlib.sha256(canonical_json(canonical).encode("utf-8")).hexdigest()
    return ResolvedProfile(profile_id, schema_version, version.strip(), digest, rules)


def profile_digest(profile: ResolvedProfile) -> str:
    """Return the canonical digest stored on a resolved profile."""
    return profile.digest


def load_profile(
    profile_id: str, profiles_root: str | Path | None = None
) -> ResolvedProfile:
    """Load and validate one profile selected by its safe filename stem."""
    safe_id = validate_profile_id(profile_id)
    root = (
        Path(profiles_root).resolve()
        if profiles_root is not None
        else resolve_document_planning_paths().profiles_root
    )
    path = root / f"{safe_id}.json"
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid profile {safe_id!r}: {exc}") from exc
    return _profile_from_data(data, safe_id)


def discover_profiles(
    profiles_root: str | Path | None = None,
) -> tuple[DiscoveredProfile, ...]:
    """Discover direct JSON profile children, retaining invalid entries."""
    root = (
        Path(profiles_root).resolve()
        if profiles_root is not None
        else resolve_document_planning_paths().profiles_root
    )
    if not root.exists():
        return ()
    discovered: list[DiscoveredProfile] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        if not path.is_file():
            continue
        profile_id = path.stem
        try:
            profile = load_profile(profile_id, root)
        except (OSError, ValueError) as exc:
            discovered.append(DiscoveredProfile(profile_id, path, None, str(exc)))
        else:
            discovered.append(DiscoveredProfile(profile_id, path, profile, None))
    return tuple(discovered)


_BASELINE_PROFILE_ID = "primary-only"
_BASELINE_VERSION = "1.0.0"


def _make_baseline_profile() -> ResolvedProfile:
    """Create a canonical primary-only baseline profile."""
    rules: tuple[ProfileRule, ...] = (
        ProfileRule(
            "*",
            (ProfileTarget("primary", "primary", False, "primary:primary"),),
        ),
    )
    digest = hashlib.sha256(
        canonical_json(
            {
                "profile_id": _BASELINE_PROFILE_ID,
                "schema_version": PROFILE_SCHEMA_VERSION,
                "version": _BASELINE_VERSION,
                "rules": [
                    {
                        "form_selector": "*",
                        "targets": [
                            {"role": "primary", "type": "primary", "optional": False}
                        ],
                    }
                ],
            }
        ).encode("utf-8")
    ).hexdigest()
    return ResolvedProfile(
        _BASELINE_PROFILE_ID, PROFILE_SCHEMA_VERSION, _BASELINE_VERSION, digest, rules
    )


def get_or_create_baseline_profile(
    profiles_root: str | Path | None = None,
) -> ResolvedProfile:
    """Return the canonical baseline, creating it atomically if absent."""
    safe_id = _BASELINE_PROFILE_ID
    baseline = _make_baseline_profile()
    root = (
        Path(profiles_root).resolve()
        if profiles_root is not None
        else resolve_document_planning_paths().profiles_root
    )
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_id}.json"

    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            raise ValueError(
                f"baseline profile {safe_id!r} exists but is unreadable; "
                "please rename or remove it and retry"
            )
        try:
            existing = _profile_from_data(data, safe_id)
        except ValueError as err:
            raise ValueError(
                f"baseline profile {safe_id!r} exists but is invalid; "
                f"please fix or rename it: {err}"
            ) from err

        if existing.digest == baseline.digest:
            return existing
        raise ValueError(
            f"baseline profile {safe_id!r} exists with modified content; "
            "please rename it or create a new profile ID"
        )

    import tempfile
    import stat

    temp_fd, temp_path = tempfile.mkstemp(
        suffix=".json", prefix=f"{safe_id}.", dir=root
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(baseline, indent=2, ensure_ascii=False) + "\n")
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return baseline


def compatible_with_catalog_only(profile: ResolvedProfile) -> bool:
    """Whether every request in the normalized profile is primary-only."""
    return all(
        target.role == "primary" and target.type == "primary"
        for rule in profile.rules
        for target in rule.targets
    )


def targets_for_form(profile: ResolvedProfile, form: str) -> tuple[ProfileTarget, ...]:
    """Select the exact normalized form rule, falling back to ``*`` only."""
    normalized = _normalize_form(form)
    for rule in profile.rules:
        if rule.form_selector != "*" and normalized in rule.form_selector.split(", "):
            return rule.targets
    for rule in profile.rules:
        if rule.form_selector == "*":
            return rule.targets
    return ()


__all__ = [
    "DiscoveredProfile",
    "ProfileRule",
    "ProfileTarget",
    "ResolvedProfile",
    "compatible_with_catalog_only",
    "discover_profiles",
    "get_or_create_baseline_profile",
    "load_profile",
    "profile_digest",
    "targets_for_form",
]
