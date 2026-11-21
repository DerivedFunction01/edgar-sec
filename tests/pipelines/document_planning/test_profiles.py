import json
from pathlib import Path

import pytest

from edgar_sec.pipelines.document_planning.profiles import (
    compatible_with_catalog_only,
    discover_profiles,
    get_or_create_baseline_profile,
    load_profile,
    profile_digest,
    targets_for_form,
)


def _write_profile(root: Path, profile_id: str, rules: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{profile_id}.json").write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "schema_version": "1",
                "version": "1.0.0",
                "rules": rules,
            }
        ),
        encoding="utf-8",
    )


def _rule(selector: str, *targets: dict) -> dict:
    return {"form_selector": selector, "targets": list(targets)}


def _primary(
    optional: bool = False,
    catalog_direct_selection: str | None = "submitted_primary",
) -> dict:
    target = {
        "role": "primary",
        "type": "primary",
        "optional": optional,
    }
    if catalog_direct_selection is not None:
        target["catalog_direct_selection"] = catalog_direct_selection
    return target


def test_selector_aliases_specificity_and_catalog_compatibility(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _write_profile(
        root,
        "annual",
        [
            _rule("*", _primary()),
            _rule(
                "10-K/A, 20-F",
                _primary(),
                {"role": "exhibit", "type": "EX-21", "optional": True},
            ),
        ],
    )

    profile = load_profile("annual", root)
    assert [target.role for target in targets_for_form(profile, "10-K/A")] == [
        "primary",
        "exhibit",
    ]
    assert targets_for_form(profile, "8-K")[0].request_id == "primary:primary"
    assert not compatible_with_catalog_only(profile)
    assert profile_digest(profile) == profile.digest


def test_digest_ignores_rule_and_target_array_order(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    first = [
        _rule(
            "10-K", _primary(), {"role": "exhibit", "type": "EX-21", "optional": True}
        ),
        _rule("8-K", _primary()),
    ]
    second = [
        _rule("8-K", _primary()),
        _rule(
            "10-K", {"role": "exhibit", "type": "EX-21", "optional": True}, _primary()
        ),
    ]
    _write_profile(root, "stable", first)
    first_profile = load_profile("stable", root)
    _write_profile(root, "stable", second)
    second_profile = load_profile("stable", root)

    assert first_profile.digest == second_profile.digest


@pytest.mark.parametrize(
    "rules",
    [
        [_rule("10-K/A", _primary()), _rule("10-K", _primary())],
        [
            _rule(
                "10-K",
                {"role": "graphic", "type": "GRAPHIC", "optional": False},
                {"role": "graphic", "type": "GRAPHIC", "optional": True},
            )
        ],
        [
            _rule(
                "10-K",
                {"role": "exhibit", "type": "EX-10.*", "optional": True},
                {"role": "exhibit", "type": "EX-10.1", "optional": False},
            )
        ],
        [_rule("10-K", {"role": "exhibit", "type": "EX-99.*", "optional": True})],
        [_rule("10-K", {"role": "exhibit", "type": "ex-21", "optional": True})],
    ],
)
def test_invalid_rule_and_target_contracts_raise(
    tmp_path: Path, rules: list[dict]
) -> None:
    root = tmp_path / "profiles"
    _write_profile(root, "invalid", rules)

    with pytest.raises(ValueError):
        load_profile("invalid", root)


def test_discovery_keeps_malformed_json_as_invalid(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    root.mkdir()
    (root / "broken.json").write_text("{", encoding="utf-8")

    found = discover_profiles(root)

    assert len(found) == 1
    assert found[0].profile_id == "broken"
    assert not found[0].valid
    assert found[0].error


def test_catalog_only_profile_is_accepted_and_schema_version_is_checked(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    _write_profile(
        root, "primary", [_rule("*", _primary(catalog_direct_selection=None))]
    )
    assert compatible_with_catalog_only(load_profile("primary", root))

    # schema_version mismatch
    data = json.loads((root / "primary.json").read_text(encoding="utf-8"))
    data["schema_version"] = "2"
    (root / "primary.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        load_profile("primary", root)

    _write_profile(
        root,
        "operations",
        [
            _rule(
                "*",
                {
                    **_primary(),
                    "acquisition_policy": {"operations": ["raw", "raw"]},
                },
            )
        ],
    )
    with pytest.raises(ValueError, match="must be unique"):
        load_profile("operations", root)

    _write_profile(
        root,
        "bad-selector",
        [
            _rule(
                "*",
                _primary(catalog_direct_selection="invalid_selector"),
            )
        ],
    )
    with pytest.raises(ValueError, match="invalid catalog_direct_selection"):
        load_profile("bad-selector", root)

    _write_profile(
        root,
        "nonprimary-selector",
        [
            _rule(
                "*",
                {
                    "role": "exhibit",
                    "type": "EX-21",
                    "optional": True,
                    "catalog_direct_selection": "submitted_primary",
                },
            )
        ],
    )
    with pytest.raises(ValueError, match="only allowed on primary targets"):
        load_profile("nonprimary-selector", root)


def test_generated_baseline_profile_omits_null_acquisition_policy(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"

    generated = get_or_create_baseline_profile(root)
    raw = json.loads((root / "primary-only.json").read_text(encoding="utf-8"))

    assert "acquisition_policy" not in raw["rules"][0]["targets"][0]
    assert load_profile("primary-only", root).digest == generated.digest
    assert get_or_create_baseline_profile(root).digest == generated.digest


@pytest.mark.parametrize("operations", [[], ["unknown"], ["raw", 1]])
def test_operation_request_must_be_nonempty_and_known(
    tmp_path: Path, operations: list[object]
) -> None:
    root = tmp_path / "profiles"
    _write_profile(
        root,
        "invalid-operations",
        [
            _rule(
                "*",
                {
                    **_primary(),
                    "acquisition_policy": {"operations": operations},
                },
            )
        ],
    )
    with pytest.raises(ValueError):
        load_profile("invalid-operations", root)
