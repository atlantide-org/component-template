"""Pipeline behaviour: determinism, Merkle skip, and update versus replace.

The stages `atlantide plan` runs — lower to IR, hash, diff against the state a prior
apply would have committed — so the assertions cover what a run does, not only what
the objects hold. This is where a field declared with the wrong mutability shows up,
as a replace where an update was intended.

The component declares no children, so these cases cover the harness alone. Add one
case per input as the expansion grows::

    def test_toggling_versioning_updates_in_place() -> None:
        run = compiled(versioning=False).against(compiled())
        assert run.actions["example-bucket"] is Action.UPDATE
        assert run["example-bucket"].changed_fields == ("versioning",)

- a mutable field changed        -> ``UPDATE``, with ``run[...].changed_fields``
- an immutable field changed     -> ``REPLACE``, of that node and any node naming it
- an optional block on or off    -> ``CREATE`` / ``DELETE``, the rest ``NOOP``
- an immutable field on a ref    -> ``REPLACE`` with ``run[...].conditional``
- ``protect=True``, then a teardown -> ``approve()`` returns ``PreventDestroyError``
"""

from __future__ import annotations

from conftest import CORE, Compiled, compiled, component, local, stack
from returns.pipeline import is_successful

from atlantide.core import collecting
from atlantide.ir import IRGraph, lower
from atlantide.reconcile import Action

# --- determinism ----------------------------------------------------------


def test_two_evaluations_are_byte_identical() -> None:
    """Equal inputs lower to equal canonical bytes."""
    assert compiled().bytes == compiled().bytes


def test_lowering_is_order_independent() -> None:
    """Two instances declared in either order lower to the same IR."""

    def pair(first: str, second: str) -> IRGraph:
        with collecting() as registry, stack():
            component(name=first)
            component(name=second)
        return lower(registry)

    assert pair("dev", "prod").to_canonical() == pair("prod", "dev").to_canonical()


def test_two_instances_lower_to_disjoint_nodes() -> None:
    """Node ids are namespaced per instance."""
    both = Compiled.of(lambda: [component(name="dev"), component(name="prod")])
    assert both.names == local(*CORE, name="dev") | local(*CORE, name="prod")


# --- first run vs re-run --------------------------------------------------


def test_first_run_creates_every_node() -> None:
    """Over empty state, every node is a CREATE."""
    run = compiled().against()
    assert set(run.actions) == local(*CORE)
    assert set(run.actions.values()) <= {Action.CREATE}


def test_unchanged_config_is_all_noop() -> None:
    """Equal input hashes are Merkle-skipped: no provider call."""
    assert set(compiled().against(compiled()).actions.values()) <= {Action.NOOP}


# --- destroy guard --------------------------------------------------------


def test_protect_travels_into_the_ir() -> None:
    """``protect=True`` marks its children ``prevent_destroy``; the default does not."""
    protect = compiled(protect=True)
    assert Compiled.empty().against(protect).protected == {
        node.id for node in protect.ir.nodes if node.prevent_destroy
    }
    assert not any(node.prevent_destroy for node in compiled().ir.nodes)


def test_teardown_succeeds_unprotected() -> None:
    """With nothing protected, deleting everything plans cleanly."""
    run = Compiled.empty().against(compiled())
    assert run.protected == frozenset()
    assert set(run.actions.values()) <= {Action.DELETE}
    assert is_successful(run.approve())
