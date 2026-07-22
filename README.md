# component-template

[![CI](https://github.com/atlantide-org/component-template/actions/workflows/ci.yml/badge.svg)](https://github.com/atlantide-org/component-template/actions/workflows/ci.yml)

Scaffolding for publishing an [Atlantide](https://github.com/atlantide-org/atlantide)
L2 component: repository layout, packaging, CI, and a test harness that runs a
component through the same stages `atlantide plan` does.

It provisions nothing. `ExampleComponent` is an empty shell with the input handling
every component needs — region resolution, a `prevent_destroy` guard, per-instance
tags — and a numbered comment block where the children go. Clone it, rename it, declare
the expansion.

---

## Contents

- [Layout](#layout)
- [Forking the template](#forking-the-template)
- [Writing the component](#writing-the-component)
- [Writing the tests](#writing-the-tests)
- [Conventions](#conventions)
- [Publishing](#publishing)
- [Limitations](#limitations)
- [Development](#development)

## Layout

```
component-template/
├── src/__init__.py         # the component — the only tree consumers vendor
├── tests/
│   ├── conftest.py         # build / compile / diff primitives
│   ├── test_component.py   # structure: children, namespacing, wiring, validation
│   └── test_pipeline.py    # behaviour: determinism, Merkle skip, update vs replace
├── scripts/rename.py       # one-shot placeholder rewrite
├── .github/workflows/ci.yml
└── pyproject.toml
```

On fetch, Atlantide copies `src/` into `.atlantis/components/<alias>/` and mounts it,
so `atlantide.components.<alias>` resolves. Nothing outside `src/` is vendored — tests,
CI, and this README stay in the repository.

`.atlantis/` and `atlantide.lock` are git-ignored here: they are consumer-side
artifacts, and this repository is the producer.

The scaffolding is **provider-agnostic** — the harness folds the `aws`, `local`, and
`random` type registries into one mutability table, and the scaffold itself imports no
provider. Nothing needs changing to build on any of them.

## Forking the template

1. **Copy the repository** under the new name, e.g. `aws-remote-state`.
2. **Rewrite the placeholder names**, once, before writing anything of your own:

   ```bash
   python scripts/rename.py aws-remote-state RemoteState
   ```

   That substitutes `component-template` → `aws-remote-state`, `component_template` →
   `aws_remote_state`, and `ExampleComponent` → `RemoteState` across every text file,
   and renames `tests/test_component.py` → `tests/test_aws_remote_state.py`. Then
   delete `scripts/rename.py`.
3. **Fix the `description`** in `pyproject.toml` — the rename leaves it as `TEMPLATE`.
4. **Declare the expansion** in `src/__init__.py`, following the numbered comments.
5. **Retarget the tests**: the `# component-specific` block at the top of
   `tests/conftest.py` (`NAME`, `REGION`, `CORE`, `ACCESS`) plus the `component()`
   builder. The rest of the harness is generic.
6. **Fill in the test modules.** Each carries a checklist in its docstring of the cases
   to add per child and per input.
7. **Rewrite this README** for the real component — see
   [`aws-remote-state`](https://github.com/atlantide-org/aws-remote-state) for the
   target shape: Overview, Requirements, Installation, Usage, API, Behaviour,
   Operations, Limitations, Development.
8. **Refresh the lockfile.** `uv lock`, and commit it — CI verifies it with
   `uv lock --check`.

`uv sync && uv run pytest` is green at every step: the scaffold's 14 tests pass against
an empty expansion and keep passing as it grows.

## Writing the component

`__init__` runs at config-evaluation time and does four things, in order:

```python
class RemoteState(Component):
    def __init__(self, name: str, *, bucket: str, region: str | None = None) -> None:
        # 1. validate and resolve — raise RegistryError before building anything
        self.region = _require_region(region)

        # 2. declare children; they namespace under `name` (-> "tfstate-bucket")
        self.bucket = child(S3Bucket, "bucket", bucket=bucket, region=self.region)

        # 3. wire with refs, never literals — a Ref is what creates the edge
        self.policy = child(S3BucketPolicy, "policy", bucket=self.bucket.bucket)

        # 4. expose outputs: physical names as values, computed fields as refs
        self.bucket_name = self.bucket.bucket
        self.bucket_arn = self.bucket.arn
```

There is no component-level node: the children lower as flat resources, so a component
has no state, output, or lifecycle of its own — only theirs.

## Writing the tests

Two layers, and both matter:

| Module | Asserts on | Catches |
|--------|-----------|---------|
| `test_component.py` | the live resource objects, before lowering | wrong child count, colliding node ids, a ref wired as a literal, missing validation |
| `test_pipeline.py` | IR + Merkle hashes + the engine's own `diff` | a field declared with the wrong mutability — a rename that quietly *replaces* something unrecoverable instead of updating it |

The pipeline layer is the one you cannot skip. Object-level assertions cannot see that
`versioning` is `mutable()` while `bucket` is `immutable()`; only a diff against the
state a prior apply would have written can:

```python
def test_renaming_the_bucket_replaces_it() -> None:
    run = compiled(bucket="acme-v2").against(compiled())
    assert run.actions["example-bucket"] is Action.REPLACE
```

Every pipeline assertion goes through one call — `desired.against(prior)`:

| Call | Is |
|------|----|
| `compiled(**kwargs)` | a config lowered to IR + Merkle hashes (a `Compiled`) |
| `desired.against(prior)` | what a second run does over `prior`'s state (a `Plan`) |
| `desired.against()` | what a first run does, over empty state |
| `Compiled.empty().against(prior)` | a teardown of everything |

A `Plan` exposes `.actions` (per node, by local name), `plan["example-bucket"]` for one
`Change` (its `changed_fields`, and the `conditional` flag on a known-after-apply
replace), `.protected` for the ids `prevent_destroy` guards, and `.approve()` for the
planner's verdict — `Failure(PreventDestroyError)` when a guarded node would be
deleted.

Write one case per input: unchanged (all `NOOP`), each mutable field (`UPDATE`), each
immutable field (`REPLACE`), each optional block added or removed (`CREATE` / `DELETE`).
Every row of your README's *Behaviour* table should map to one.

## Conventions

Followed by every published component in the organisation:

- **One component per repository**, exported from `src/__init__.py` via `__all__`.
- **Children via `child(Type, "local-name", ...)`** — they namespace under the instance
  name, so two instances never collide.
- **Wire with refs, never literals.** `bucket.arn` creates a dependency edge; an
  f-string of the same value creates nothing.
- **Resolve the region once**, from `region=` or `current_stack_region()`, and raise
  `RegistryError` when neither exists.
- **Validate inputs in `__init__`** and raise `RegistryError` with a message naming the
  fix (`"needs assumed_by= (a service principal)"`).
- **`protect=` is opt-in**, mapping to `Lifecycle(prevent_destroy=True)` on the
  stateful children only.
- **Copy mutable defaults per child** (`dict(self.tags)`) — resources merge the stack's
  tags into the dict they were handed.
- **Expose physical names as plain values and computed fields as refs**, plus the child
  handles, so callers can wire further resources.
- **Document limitations honestly.** Fields the provider does not expose are out of
  scope; say so rather than faking them.

## Publishing

Consumers pin a commit and a content hash, so a tag is the contract:

```bash
git tag v1 && git push --tags
```

```bash
atlantide component add https://github.com/<owner>/<name> --ref v1 --subdir src
```

which writes to the consumer's `atlantide.toml`:

```toml
[components.<name>]
git    = "https://github.com/<owner>/<name>"
ref    = "v1"
subdir = "src"
```

`atlantide component vendor` rebuilds `.atlantis/` from `atlantide.lock`;
`atlantide component verify` re-hashes it against the lock. Moving a tag breaks
`verify` for everyone pinned to it — cut a new tag instead. A published component runs
as trusted Python in the consumer's process, so review changes as you would a provider.

## Limitations

- **Config cannot define components.** Atlas-lang bans `class`, so a component is
  ordinary Python written by a library author and imported under
  `atlantide.components.*`. Config uses them; it cannot declare them.
- **No network or clock at eval time.** The component body runs inside the
  deterministic sandbox's import surface — no fetching, no timestamps, no randomness.
  Derive names from inputs (`table or f"{bucket}-lock"`).
- **A component owns no IR node**, and therefore no state, output, or lifecycle of its
  own — only its children's.

## Development

```bash
uv sync
uv run pytest                  # 14 scaffold tests
uv run mypy src tests
uv run ruff check .
uv run ruff format --check .
```

CI runs the same checks on Python 3.11, 3.12, and 3.13.
