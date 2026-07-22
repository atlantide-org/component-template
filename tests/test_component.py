"""Expansion structure: children, namespacing, wiring, and validation.

Assertions on the resource objects, before lowering; what a run does with them is in
test_pipeline.py.

The component declares no children, so these cases cover the input handling alone.
Add, per child declared:

- its type and namespaced id: ``c.bucket.node_id.endswith("aws.S3Bucket:example-bucket")``
- disjoint ids for two instances in one stack
- each cross-child value is a ``Ref``, not a literal
- each ``RegistryError`` branch
- each default derived from another input (``table or f"{bucket}-lock"``)
"""

from __future__ import annotations

import pytest
from conftest import NAME, REGION, component, stack

from atlantide.core import RegistryError

# --- construction ---------------------------------------------------------


def test_builds_inside_a_stack() -> None:
    with stack():
        instance = component()
    assert instance.name == NAME


def test_two_instances_do_not_collide() -> None:
    with stack():
        dev = component(name="dev")
        prod = component(name="prod")
    assert dev.name != prod.name


# --- region resolution ----------------------------------------------------


def test_requires_region_without_stack_or_param() -> None:
    with pytest.raises(RegistryError):
        component()


def test_falls_back_to_stack_region() -> None:
    with stack(region=REGION):
        instance = component()
    assert instance.region == REGION


def test_region_param_overrides_stack_region() -> None:
    with stack(region=REGION):
        instance = component(region="us-east-1")
    assert instance.region == "us-east-1"


# --- lifecycle and tags ---------------------------------------------------


def test_protect_arms_the_lifecycle_guard() -> None:
    """The guard passed to the children as ``lifecycle=``; unset by default."""
    with stack():
        assert component().guard is None
        guarded = component(protect=True).guard
    assert guarded is not None
    assert guarded.prevent_destroy


def test_tags_default_to_an_isolated_dict() -> None:
    """Each instance holds its own dict."""
    with stack():
        first, second = component(), component()
    first.tags["owner"] = "platform"
    assert second.tags == {}
