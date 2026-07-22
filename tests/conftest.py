"""Test primitives: build a config, lower it, and diff it as the engine does.

Two layers:

- ``stack()`` / ``component()`` construct the component, for assertions on the
  resource objects themselves.
- ``Compiled`` / ``Plan`` lower a config to IR, construct the state a prior apply
  would have committed, and run the engine's ``diff`` over the pair.

Pipeline assertions go through ``against``::

    desired.against(prior)            # a run over prior's committed state
    desired.against()                 # a run over empty state
    Compiled.empty().against(prior)   # a run that deletes everything

Each returns a :class:`Plan`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from atlantide.core import Stack, collecting
from atlantide.core.fields import Mutability, field_mutability
from atlantide.core.node_id import local_name_of
from atlantide.graph import build_graph, topological_order
from atlantide.ir import IRGraph, IRNode, canonical_bytes, lower, merkle_hashes
from atlantide.providers.aws import TYPES as AWS_TYPES
from atlantide.providers.local import TYPES as LOCAL_TYPES
from atlantide.providers.random import TYPES as RANDOM_TYPES
from atlantide.reconcile import Action, Change, ChangeSet, diff, plan
from atlantide.state import StateGraph, StateNode
from returns.result import Result

from src import ExampleComponent

T = TypeVar("T")

#: Field mutability per resource type, as ``Engine`` builds it. All three providers
#: are folded in, so the harness covers a component built on any of them.
MUTABILITY: dict[str, dict[str, Mutability]] = {
    name: field_mutability(cls)
    for types in (AWS_TYPES, LOCAL_TYPES, RANDOM_TYPES)
    for name, cls in types.items()
}


# --- component-specific ---------------------------------------------------

STACK = "infra"
REGION = "eu-north-1"
NAME = "example"

#: The children of every instance, by ``child()`` local name — e.g. ``("bucket",
#: "policy")``. In the graph they are namespaced under the instance name.
CORE: tuple[str, ...] = ()
#: The children an optional block adds — e.g. ``("role", "access")``.
ACCESS: tuple[str, ...] = ()


def component(*, name: str = NAME, **kwargs: Any) -> ExampleComponent:
    """The component with the test defaults, in the caller's stack."""
    return ExampleComponent(name, **kwargs)


def compiled(**kwargs: Any) -> Compiled:
    """One instance with the test defaults plus ``kwargs``, lowered to IR."""
    return Compiled.of(lambda: component(**kwargs))


# --- generic --------------------------------------------------------------


@contextmanager
def stack(*, region: str = REGION, **kwargs: Any) -> Iterator[None]:
    """The stack the tests build in."""
    with Stack(STACK, region=region, name_prefix="acme", **kwargs):
        yield


def local(*children: str, name: str = NAME) -> set[str]:
    """The namespaced local names of ``children`` (``"bucket"`` -> ``"example-bucket"``)."""
    return {f"{name}-{kid}" for kid in children}


@dataclass(frozen=True)
class Compiled:
    """A lowered config and its Merkle hashes: one evaluation of a config."""

    ir: IRGraph
    hashes: Mapping[str, str]

    @classmethod
    def of(cls, build: Callable[[], object], *, region: str = REGION) -> Compiled:
        """Evaluate ``build`` in a stack and lower it to IR and Merkle hashes."""
        with collecting() as registry, stack(region=region):
            build()
        ir = lower(registry)
        return cls(ir, merkle_hashes(ir, topological_order(build_graph(ir).unwrap())))

    @classmethod
    def empty(cls) -> Compiled:
        """A config with no nodes."""
        return cls(IRGraph(()), {})

    @property
    def bytes(self) -> bytes:
        """The canonical IR encoding."""
        return canonical_bytes(self.ir)

    @property
    def names(self) -> set[str]:
        """The local name of every node."""
        return {local_name_of(node.id) for node in self.ir.nodes}

    def __getitem__(self, local_name: str) -> IRNode:
        """The IR node with this local name."""
        return _one(self.ir.nodes, lambda node: local_name_of(node.id) == local_name, local_name)

    def state(self) -> StateGraph:
        """The state an apply of this config would have committed."""
        return StateGraph(
            {node.id: _committed(node, self.hashes[node.id]) for node in self.ir.nodes}
        )

    def against(self, prior: Compiled | None = None) -> Plan:
        """The plan for this config over ``prior``'s committed state (empty by default)."""
        state = (prior or Compiled.empty()).state()
        return Plan(diff(self.ir, self.hashes, state, MUTABILITY), _guarded(state))


@dataclass(frozen=True)
class Plan:
    """A changeset and the committed ids carrying ``prevent_destroy``."""

    changes: ChangeSet
    protected: frozenset[str]

    @property
    def actions(self) -> dict[str, Action]:
        """The action per node, keyed by local name."""
        return {local_name_of(c.node_id): c.action for c in self.changes}

    def __getitem__(self, local_name: str) -> Change:
        """The change affecting this local name, with its fields and flags."""
        return _one(self.changes, lambda c: local_name_of(c.node_id) == local_name, local_name)

    def approve(self) -> Result[ChangeSet, Exception]:
        """The planner's verdict: ``Failure(PreventDestroyError)`` over a protected delete."""
        return plan(self.changes, self.protected)


def _one(items: Iterable[T], match: Callable[[T], bool], label: str) -> T:
    """The single item satisfying ``match``, or an assertion naming ``label``."""
    found = next((item for item in items if match(item)), None)
    assert found is not None, f"nothing named {label!r}"
    return found


def _committed(node: IRNode, input_hash: str) -> StateNode:
    """The state record an apply of ``node`` would have written."""
    return StateNode(
        id=node.id,
        type=node.type,
        provider=node.provider,
        provider_version=node.provider_version,
        input_hash=input_hash,
        properties=dict(node.properties),
        dependencies=node.dependencies,
        prevent_destroy=node.prevent_destroy,
    )


def _guarded(state: StateGraph) -> frozenset[str]:
    """The committed ids the planner refuses to delete."""
    return frozenset(node.id for node in state.nodes.values() if node.prevent_destroy)
