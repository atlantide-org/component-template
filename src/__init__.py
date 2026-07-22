"""Atlantide component: TEMPLATE — replace this docstring.

``ExampleComponent`` declares no resources. Add ``child(...)`` calls in ``__init__``
and expose the handles and outputs.

Fetch with ``atlantide component add <repo-url> --ref v1 --subdir src``, then import
from config as ``atlantide.components.component_template``. See README.md.
"""

from __future__ import annotations

from atlantide.core import Component, Lifecycle, current_stack_region
from atlantide.core.errors import RegistryError

__all__ = ["ExampleComponent"]


class ExampleComponent(Component):
    """TEMPLATE — a component with an empty expansion.

    Declare the children in ``__init__``::

        self.bucket = child(S3Bucket, "bucket", bucket=bucket, region=self.region)
        self.policy = child(S3BucketPolicy, "policy", bucket=self.bucket.bucket)

    Children are namespaced under the component's name (``name`` + ``"bucket"`` ->
    ``<name>-bucket``). Pass refs between them (``self.bucket.arn``) rather than
    equivalent literals: the ref creates the dependency edge.
    """

    def __init__(
        self,
        name: str,
        *,
        region: str | None = None,
        protect: bool = False,
        tags: dict[str, str] | None = None,
    ) -> None:
        # 1. Resolve and validate the inputs, before building anything.
        self.name = name
        self.region = _require_region(region)
        # 2. The lifecycle guard, passed as ``lifecycle=self.guard`` to the children
        #    holding state. It blocks any planned delete of them, deliberate included.
        self.guard: Lifecycle | None = Lifecycle(prevent_destroy=True) if protect else None
        # 3. Tags to merge into each child as ``dict(self.tags)``; a resource mutates
        #    the dict it is handed.
        self.tags = dict(tags or {})

        # 4. The children: ``child(Type, "local-name", ...)``.

        # 5. The outputs: physical names as values, computed fields as the refs they
        #    are until apply resolves them.


def _require_region(region: str | None) -> str:
    """The explicit region, else the enclosing stack's."""
    resolved = region or current_stack_region()
    if resolved is None:
        raise RegistryError("ExampleComponent needs a region (pass region= or use a Stack)")
    return resolved
