# CI notes

The running record of what CI checks in this repository, what it does not,
and what to do next. **Read this at the start of every CI-review loop, and
update it at the end.** The routine behind it: explore the repo and its
workflows, make sure every component is linted, formatted, tested,
valgrind-checked, fuzzed and (where it has a spec) model-checked, on pull
requests too, with a comment on the pull request.

## Coverage matrix

| Component | Format | Lint | Tests | Valgrind | Fuzz | TLA+ |
|---|---|---|---|---|---|---|
| `backend/` (Go) | gofmt, `go mod tidy` (backend-tests) | vet (backend-tests), staticcheck (quality) | `go test -race` (backend-tests) | n/a (pure Go) | `Fuzz*` targets, auto-discovered (quality) | — |
| `sdk/` (Rust, UniFFI) | `cargo fmt` (sdk) | clippy `-D warnings`, rustdoc (sdk) | `cargo test`, bindings smoke tests (sdk) | memcheck over the tests (quality) | **gap**: no `cargo fuzz` targets | — |
| `terraform-provider-*` (Go) | gofmt, `tofu fmt` | vet; staticcheck only covers `backend/` | unit, acceptance, e2e | n/a | **gap** | — |
| `web/` (TS) | **gap**: no formatter | `tsc --noEmit` only; **gap**: no eslint | vitest, build | n/a | n/a | — |
| `site/` | **gap** | build only | release regression tests | n/a | n/a | — |
| `images/*-operator`, `hack/`, `test/` (Python) | **gap**: `ruff format` would change 84 files | ruff `E9,F` (quality) | pytest / unittest | n/a | **gap** | — |
| Shell scripts | — | shellcheck `-S warning` (quality) | — | — | — | — |
| `.github/workflows/` | — | actionlint (quality) | — | — | — | — |
| `infra/`, `deploy/` | `tofu fmt` (infra-plan) | `tofu validate` | `tofu test` | n/a | n/a | — |
| `spec/opa-replacement` | — | — | — | — | — | TLC, every `.cfg` (quality) |

## Guidance: go wide, not in sequence

Applies to the workflows and to the loop that maintains them.

**In CI**
- No job waits on another unless it needs its output. `report` is the only
  `needs:` fan-in; everything else starts at once.
- One tool, one job: lint is five jobs (coverage, actionlint, shellcheck, ruff,
  staticcheck), not five steps, so one failure does not hide the rest and the
  run takes as long as the slowest, not the sum.
- Fan out over data with a matrix: each Go `Fuzz*` target and each TLC
  configuration is its own leg, found by the `discover` job. Use
  `fail-fast: false` so every leg reports.
- New check, new job. Do not append steps to an existing job to save a
  runner. Share only what is expensive to rebuild, through `actions/cache`.
- Keep `cancel-in-progress` concurrency groups so a newer push replaces the
  runs in flight.

**In the loop**
- Survey the components in parallel: spawn one subagent per component or per
  gap (Go, SDK, web/site, Python, shell, infra, specs) in a single message,
  each told to find what is unchecked and to propose or make the change on
  its own files. Do not walk the components one after another.
- Run the local verifications (TLC, valgrind, fuzz, linters) concurrently as
  background commands, not one after the next.
- Work independent backlog items at once, each on separate files, and merge
  the results; serialise only changes to the same file (this doc, `quality.yml`).
- Check the CI result of every job, not just the first red one.

## What `quality.yml` does

Runs on every pull request (no path filter), every push to main, nightly, and
by hand.

- **discover**: lists the fuzz targets and TLC configurations the matrices
  below fan out over.
- **lint**, five parallel jobs: `hack/ci-coverage.sh` (fails when a go.mod,
  Cargo.toml, package.json, pyproject.toml or `.tla` directory is not
  mentioned by any workflow), actionlint, shellcheck, ruff, staticcheck.
- **fuzz**: one parallel leg per `func FuzzXxx` in any Go module, each run
  for 30 s (10 min nightly). Add a target and it runs; no workflow edit. Failing
  inputs upload as the `fuzz-failures` artifact; commit them under
  `testdata/fuzz/` as seeds. Seeds also run in plain `go test`.
- **valgrind**: the SDK's tests with cargo's runner set to memcheck;
  invalid accesses and definite leaks fail it. About 1 minute of test time
  locally.
- **tla**: one parallel leg per `spec/*/*.cfg`, each `hack/tlc-check.sh <cfg>`
  (pinned `tla2tools.jar`, checked by sha256). A configuration named in the spec
  directory's `expect-violation` file must *find* a violation (it pins what
  the model says is broken); every other must hold. Adding a spec: put the
  `.tla` and `.cfg` files in `spec/<name>/`, and list the violating ones.
- **report**: one comment on the pull request, edited in place, with each
  job's result. A fork's read-only token cannot comment; the run summary has
  the same table.

## Code coverage (`coverage.yml`)

Parallel jobs, one per measured component, each writing `{"pct": N}`; a
`report` job compares them with the `coverage-baseline` artifact that the last
successful run on main left, writes one table as a PR comment
(`hack/coverage-report.py`), and **fails the PR when a component drops by more
than 1 point or has no result**. On main the run stores the new baseline
(90 days). Locally measured at the first pass (lines/statements):

| Component | Tool | Coverage |
|---|---|---|
| `backend` (Go) | `go test -coverprofile` | 59.9% |
| `terraform-provider-metronome` (Go) | same | 67.9% |
| `web` (TS) | vitest + `@vitest/coverage-v8` | 85.4% |
| `hack/` (Python, PyYAML-only suites) | coverage.py | 61.0% (branch-inclusive, `--source=hack`) |
| `sdk` (Rust) | `cargo llvm-cov` 0.6.16 | 93.7% lines |

Not measured yet: `terraform-provider-computeruse` (needs the Nix shell and
cgo), the two Python operators (pytest in Nix shells), `site/`, Go integration
and fuzz coverage, and the NixOS/kind end-to-end suites. Adding a component:
add a job that uploads `cov/<name>.json`, and add `report` to its `needs`.
Raising the floor: when a component is well above 1 point of headroom, lower
`MAX_DROP` for it or add a minimum; the lowest numbers (backend) are where new
tests pay most. Removing a component makes the report fail once: land the
removal, then re-run on main to refresh the baseline.

## Decisions and baselines

- Linters are set to what is clean today, so they can fail on new problems
  rather than on old ones: ruff `E9,F` (not the default set, 138 findings;
  not `ruff format`, 84 files); staticcheck without the `ST` style checks that
  fire on existing error strings; shellcheck without SC2148/SC2034 and
  skipping the generated `examples/*/import.sh`. Tighten these one at a time,
  fixing the findings in the same change.
- `test/webhooks-nixos/*-test.py` is excluded from ruff: the NixOS test
  driver injects its globals (`cluster`, ...).
- All third-party actions are pinned to a commit with the version in a
  comment (CONTRIBUTING.md). `go run ...@version` tools are pinned by version.
- The Go fuzz target so far: `FuzzURLTemplate`
  (`backend/internal/sessions/urls_fuzz_test.go`): the session URL template
  parser, and that URLs it makes are read back by `Match`.

## Fixed in the first pass

- `sdk.yml` used `matrix.language` in the non-matrix rust job (actionlint).
- Unused Python imports removed (6 files); `hack/lib.sh` `cd` without
  `|| return`.

## Backlog (in order)

0. Coverage: measure the gaps above; raise `backend` from 59.9% (list the
   lowest packages with `go tool cover -func`); a floor per component.

1. More Go fuzz targets: webhook payload parsers (`billing/stripe`,
   `billing/metronome`), `hosts.Split`, `auth.SameHost`, policy JSON bodies.
2. `cargo fuzz` for the SDK's request/response decoding (the SDK is the
   native-code surface; also try valgrind on the provider's cgo link).
3. ESLint and a formatter (prettier or biome) for `web/` and `site/`.
4. `ruff format` baseline commit, then `ruff format --check` in CI.
5. Staticcheck for `terraform-provider-*`; drop the ST exclusions.
6. Dependency and supply-chain checks: Dependabot for actions, Go, Cargo,
   npm; `govulncheck`, `cargo audit`, `npm audit`; secret scanning.
7. More TLA+: the lease/capacity, drain and autoscale logic
   (`backend/internal/sessions/capacity.go`, `docs/warm-pool.md`) have no spec.
8. Required status checks: make `quality / report`'s jobs required in branch
   protection (a repo setting, not in code).
9. Some per-component workflows still have path filters and no `push` to main
   (`sdk.yml` has both; `terraform-provider.yml` has no push trigger).

## Loop checklist

1. Read this file. `git log` since the last entry for new components, workflows
   or specs.
2. `hack/ci-coverage.sh`; run actionlint; look at the last runs of `quality`.
3. Work the top of the backlog; keep each change small and its checks green.
4. Update the matrix, the backlog and the log below.

## Log

- 2026-10-05 (third): added `coverage.yml`, `hack/coverage-report.py`, vitest
  coverage dependency (`web/package.json`, lockfile), and the section above.
  The baseline artifact does not exist until the first run on main, so PR
  runs before then show every component as `new`.
- 2026-10-05 (second): made it parallel: discover job, five lint jobs, fuzz and
  TLA+ matrices; added the go-wide guidance above. Checked locally: actionlint,
  matrix discovery output, `tlc-check.sh <cfg>`.
- 2026-10-05: first pass. Added `quality.yml`, `hack/ci-coverage.sh`,
  `hack/tlc-check.sh`, `spec/opa-replacement/expect-violation`,
  `FuzzURLTemplate`, and this file. Verified locally: TLC (6 configs, as
  expected), valgrind on the SDK `api` test (0 errors), the 30 s fuzz run,
  actionlint, shellcheck, ruff, staticcheck. The workflow itself has not run
  on GitHub yet.
