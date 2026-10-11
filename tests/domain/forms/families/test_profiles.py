"""Tests for family primary report profile models."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.evidence import ANNUAL_REPORT_TITLES
from edgar_sec.domain.forms.families.annual.profiles import (
    PRIMARY_PROFILE_10K,
    PRIMARY_PROFILE_20F,
)
from edgar_sec.domain.forms.families.current.evidence import CURRENT_TITLES
from edgar_sec.domain.forms.families.current.profiles import PRIMARY_PROFILE_8K
from edgar_sec.domain.forms.families.quarterly.evidence import QUARTERLY_REPORT_TITLES
from edgar_sec.domain.forms.families.quarterly.profiles import PRIMARY_PROFILE_10Q


def test_primary_10k_profile():
    """10-K primary profile is registered with family variants and titles."""
    assert PRIMARY_PROFILE_10K is not None
    assert PRIMARY_PROFILE_10K.family == "10-K"
    assert PRIMARY_PROFILE_10K.derived_taxonomy_family == "annual"
    assert PRIMARY_PROFILE_10K.checkbox_schema_family == "10-K"
    assert PRIMARY_PROFILE_10K.statutory_titles == ANNUAL_REPORT_TITLES
    assert "10-K" in PRIMARY_PROFILE_10K.designator_tokens
    assert "10-K/A" in PRIMARY_PROFILE_10K.designator_tokens
    assert "10-KSB" in PRIMARY_PROFILE_10K.designator_tokens
    assert "10-KT" in PRIMARY_PROFILE_10K.designator_tokens


def test_primary_20f_profile():
    """20-F primary profile is distinct and includes its foreign-issuer variants."""
    assert PRIMARY_PROFILE_20F is not None
    assert PRIMARY_PROFILE_20F.family == "20-F"
    assert PRIMARY_PROFILE_20F.derived_taxonomy_family == "annual"
    assert "20-F" in PRIMARY_PROFILE_20F.designator_tokens
    assert "20-F/A" in PRIMARY_PROFILE_20F.designator_tokens
    assert PRIMARY_PROFILE_20F.family != PRIMARY_PROFILE_10K.family


def test_primary_10q_profile():
    """10-Q primary profile is registered with family variants and titles."""
    assert PRIMARY_PROFILE_10Q is not None
    assert PRIMARY_PROFILE_10Q.family == "10-Q"
    assert PRIMARY_PROFILE_10Q.derived_taxonomy_family == "quarterly"
    assert PRIMARY_PROFILE_10Q.checkbox_schema_family == "10-Q"
    assert PRIMARY_PROFILE_10Q.statutory_titles == QUARTERLY_REPORT_TITLES
    assert "10-Q" in PRIMARY_PROFILE_10Q.designator_tokens
    assert "10-Q/A" in PRIMARY_PROFILE_10Q.designator_tokens


def test_primary_8k_profile():
    """8-K primary profile is registered with family variants and titles."""
    assert PRIMARY_PROFILE_8K is not None
    assert PRIMARY_PROFILE_8K.family == "8-K"
    assert PRIMARY_PROFILE_8K.derived_taxonomy_family == "current"
    assert PRIMARY_PROFILE_8K.checkbox_schema_family == "current"
    assert PRIMARY_PROFILE_8K.statutory_titles == CURRENT_TITLES
    assert "8-K" in PRIMARY_PROFILE_8K.designator_tokens
    assert "8-K/A" in PRIMARY_PROFILE_8K.designator_tokens


def test_primary_report_profile_is_dataclass():
    """PrimaryReportProfile is a frozen dataclass with version."""
    assert PRIMARY_PROFILE_10K.version == "v1"
    assert PRIMARY_PROFILE_10K.commission_header_required is True
