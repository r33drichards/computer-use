# Preparation-only release safety

The workflow is manual build-only. Publication requests fail until the parent
integrates reviewed patches into a final immutable commit and receives exact
release approval. No tag trigger is enabled. Re-enabling publication is a separate
reviewed change, not something this preparation performs.

Before any public write, preflight queries both crates, computeruse-native-sdk on
PyPI, computeruse on npm, and the SDK GitHub release. Only HTTP 404 is absence;
existing versions/releases and transport/auth/server errors abort. Both SDK and
Go remote tags must resolve to the exact immutable commit. Existing GitHub
releases are refused entirely (including matching releases): no source/assets
are trusted and no asset overwrite occurs. The original exact-commit Go retry
guard remains as defense in depth. Registries are not transactionally atomic;
a concurrent publication can still cause partial success. Do not blindly rerun:
reconcile every published digest/source, then obtain an explicit recovery plan.

## npm bootstrap and OIDC plan (not authorization)

Node >=22.14.0 and npm >=11.5.1 are required for trusted publishing. The current
publish job is token-based bootstrap and remains disabled; no token is assumed.
User deferred 2FA/token issuance until exact release approval. After approval,
parent must arrange authorized bootstrap of the unpublished package, then configure
its Trusted Publisher for this repository, workflow and approved environment.
Replace the token requirement with npm OIDC only after that binding is verified;
retain id-token: write and install a supported npm version. Never use npm >=11
as proof that a Trusted Publisher was configured. Package settings/namespace
claims and credentials are outside this lane. No public action performed here.

## Evidence boundaries

Offline guard fixtures are not native success. Final integrated immutable SHA
must run Rust workspace tests/package verification, four native builds, installed
wheel imports, packed npm artifact smoke, and Go static-library tests. Linux does
not prove macOS or arm64. Existing published macro dependency may be needed for
SDK cargo package resolution; never silently substitute a fake registry/library.

## Actual Cargo archive verification

`verify-crates.py` verifies publication units without publishing. It copies the
SDK packaging workspace and original lock into a fresh output directory. Cargo
may generate a new packaging lock only in that isolated copy; the original
workspace lock is not edited. `cargo package --no-verify` only generates each
actual `.crate` archive and is not itself native verification. The verifier
records archive SHA256, package name/version, and source inventory, then extracts
both archives and checks the SDK normalized macros dependency version. Archive
manifests remain unchanged and cannot contain a workspace path, git source, or
alternate registry for that dependency.

For the unpublished macros unit, a command-line `patch.crates-io` points solely
to its extracted archived source. Cargo metadata must resolve the SDK macros
manifest to that exact extracted path and matching version, not workspace source.
Both extracted crate units must then compile and pass `cargo test`; only after
all gates succeed is `VERIFIED` written. A generated archive, receipt, metadata
file, or interrupted run without that marker is not verification success.

This local archived-source patch is not a public registry and does not prove
macros availability on crates.io. Successful local tests also do not prove final
integrated immutable source identity, Ubuntu minimum ABI, macOS, or arm64. Those
release checks remain separate mandatory gates.

Every Cargo phase (packaging, metadata, and both extracted test gates) uses a
verification target child beneath the inherited CARGO_TARGET_DIR, namespaced by
the absolute verification output path. Relative inherited paths resolve against
the verifier invocation directory. Fresh output directories are mandatory, so
independent runs cannot overwrite workspace multi-crate-type library artifacts
and leave stale workspace fingerprints. The behavioral regression executes a
recording Cargo fixture across all five phases; it is offline isolation coverage,
not native build proof. Actual extracted-archive compilation is a separate gate.
