# Provider-root release preparation

This is a local, unsigned candidate for the approved r33drichards/terraform-provider-computeruse mirror. The source is a full immutable commit SHA supplied at runtime; preparation baseline is not final release identity. The parent alone selects the final immutable release, authenticated Copybara synchronization, version, Registry registration, signing identity and publication. None of these scripts creates a repository, tag, release, key or push.

## Actual inputs and mirror map

- terraform-provider-computeruse/** -> mirror root (Go code, go.mod/go.sum, examples, Registry docs, Makefile and local development scripts).
- Provider module and its internal imports -> github.com/r33drichards/terraform-provider-computeruse, including root main.go.
- sdk/Cargo.toml, Cargo.lock, LICENSE, README.md, crates/** and go/** -> sdk/ unchanged, at exactly the upstream SHA. All three Rust workspace members remain present; generated Go headers and bindings are retained, not regenerated.
- Provider Go replacement ../sdk/go -> ./sdk/go. SDK module identity remains github.com/r33drichards/computer-use/sdk/go. SDK build path becomes ./sdk in GNUmakefile.
- docs/contracts/policy/{backend-api.yaml,terraform-provider.md,rego-contract.md,examples/**} -> contracts/policy/; docs/terraform-provider.md -> contracts/terraform-provider.md. The policy-copy test uses the mirrored contract path. README links and build command examples are adjusted for the new root.
- Repository LICENSE and THIRD_PARTY.md -> root. SDK and crate licenses remain in sdk/. ZIPs include LICENSE, THIRD_PARTY.md and SDK_LICENSE.
- Final exports require release inputs committed at the runtime source SHA. No local release overlay is copied. The workflow is installed from that immutable snapshot; SOURCE_SHA records the supplied commit. Preparation exports are explicitly labeled and omit uncommitted release inputs. No monorepo backend, development clone, SDK lane, unrelated provider or image binaries are included.

## Local Copybara export

Use Google's official Copybara, not a Python emulation. The config uses a public git.origin and folder.destination in SQUASH mode. Its fallback author is copied from the actual upstream commit author and is not a GPG signer. It has no public destination authority. The parent must review any eventual git.destination configuration separately.

From the isolated monorepo lane, set COPYBARA to an executable launching the official tool, then:

    bash terraform-provider-computeruse/release/stage.sh FULL_40_CHAR_SHA

The default output is the sibling artifacts/export-SHA/mirror (override RELEASE_WORK with a new lane-private directory). The script refuses to overwrite it. All Copybara work/cache and HOME/TMPDIR are lane-local. A Java wrapper must also set java.io.tmpdir and user.home locally.

Historical tooling observations from the retained candidate (NOT validation of this fresh checkout): official Copybara v20260928 JAR SHA256 25807645ee17b7b863f4f885012b06192b9952632b540bdf8a21088313fe4925 verified against its official sidecar. Java21 was too old (class 69 requires Java25); lane-local public Temurin JRE25 runs via the existing Nix glibc loader. The wrapper uses jdk.lang.Process.launchMechanism=FORK because the downloaded spawn helper has an unavailable ELF interpreter. This is an unprivileged local adaptation, not a change to release runtime inputs. Official validation and transformation must be rerun after any config change.

## Native build and release workflow

From the provider-root mirror on EACH native runner, with Go1.26.8, Rust1.91+, a C compiler, Python3, zip/unzip, and platform inspection tools on PATH:

    bash release/build-platform.sh VERSION linux amd64
    bash release/build-platform.sh VERSION linux arm64
    bash release/build-platform.sh VERSION darwin amd64
    bash release/build-platform.sh VERSION darwin arm64

Run only the command matching that host. The script rejects Go-only cross compilation. It builds the matching Rust SDK using Cargo.lock, copies ONLY libcomputeruse.a into .lib, enables CGO, runs vet/race tests, and injects -X main.version=VERSION. A provider is not pure Go. Linux needs glibc and system libraries m/dl/pthread; macOS needs Security/CoreFoundation/SystemConfiguration. The SDK uses platform trust roots. No SDK shared library should accompany the provider.

The build script records ELF/load-command and runtime dependency output, rejects missing libraries, an SDK shared-library dependency, or Nix-store linkage. Native system libc/frameworks are not stripped away or replaced by mock implementations. Inspect minimum glibc symbol and macOS deployment requirements on each actual runner; runner OS labels alone do not establish a compatibility baseline.

provider-release.yml is an unexecuted reusable workflow candidate, not an enabled publishing workflow. It has four native runners, pinned action revisions, read-only contents permissions, checkout without persisted credentials, tar transport preserving executable modes, and an unsigned artifact assembly job. No workflow was dispatched. Runner availability and action behavior must be checked by the parent. Before use, the parent must bind the workflow invocation to its immutable final candidate revision. It intentionally has no secrets or automatic signing/publishing.

Collect native output directories under dist/binaries, then:

    python3 release/package_test.py -v
    python3 release/package.py VERSION dist/binaries dist/release
    python3 release/check-release.py dist/release/terraform-provider-computeruse_VERSION_SHA256SUMS

Default packaging requires all four targets, verifies OS/architecture headers and executable mode, creates deterministic ZIP metadata from given binary bytes, creates terraform-provider-computeruse_VERSION_manifest.json with protocol_versions ["6.0"], and hashes all four ZIPs AND the manifest. The checksum file does not hash itself or its later signature. Existing output directories are refused. Header checks and packaging fixtures do not establish native execution or reproducible native compilation.

For a clearly partial, unsigned LOCAL smoke package only:

    python3 release/package.py --platform linux_amd64 VERSION dist/binaries dist/local-smoke

This partial inventory cannot pass check-release.py and is rejected by the signing step. Do not present it as a complete Registry release.

## Real local installation check and server dependencies

On each actual target, after packaging:

    bash release/check-install.sh VERSION dist/release dist/install-check terraform

Use a fresh install-check directory; optional final argument tofu also works. This verifies the checksum inventory, extracts the host's ZIP into both registry filesystem-mirror layouts, runs real init without backend or direct fallback, and reads the provider schema through the CLI. It does not configure or contact a live API. It does not establish other-platform or older-libc compatibility.

The provider still needs a running Computer Use API and real server-side session/policy machinery for live operations. Nothing here bundles or substitutes those services. Upstream unit/acceptance/e2e tests use the existing fake API by default. No real token is needed for schema inspection; do not point acceptance tests at production or supply real credentials in this lane.

## Parent-controlled signing and approval

After four-platform verification and final immutable selection, the parent may provide an existing authorized GNUPGHOME and SIGNING_KEY_ID and execute:

    bash release/sign-checksums.sh dist/release/terraform-provider-computeruse_VERSION_SHA256SUMS

The script first validates the complete unsigned inventory, then uses GPG --detach-sign without --armor, yielding the binary SHA256SUMS.sig, and verifies it. It neither creates nor imports keys, chooses no signer identity, stores no secrets, and refuses an existing signature. GPG, key access, passphrase handling and Registry public-key registration are parent responsibilities and were NOT exercised here.

Release gates: all four real builds and installation/runtime baselines; live-server compatibility where appropriate; generated Registry documentation freshness; complete third-party notices/license review for embedded Rust/Go dependencies (inherited THIRD_PARTY.md is not an exhaustive binary SBOM); final mirror diff review; independent reviewer acceptance; parent signing/auth/approval. No package mechanics test or synthetic header fixture substitutes for these gates.

## Runtime immutable export (review correction)

Invoke `COPYBARA=/path/to/official-tool bash terraform-provider-computeruse/release/stage.sh FULL_40_CHAR_SHA`. The final path requires integrated committed release inputs, rejects mutable source mismatch/untracked release overlays, renders the committed `@@SOURCE_SHA@@` token into a separate configuration, and compares against a git archive of that commit. It never embeds its own final hash in tracked source or copies working-tree release inputs. The workflow is installed from that immutable archive. `SOURCE_SHA` is runtime provenance.

Until parent integration, append `--preparation` and set a fresh `RELEASE_WORK` under lane artifacts. This explicitly labeled preparation-only export uses the local template/checker but exports source from the specified commit, without copying the local release overlay. It is not a final integrated release. The earlier fixed-pin/overlay instructions above are historical and superseded by this section. Native Nix/glibc 2.42 outputs are validation-only; dependency rejection, signing and platform gates remain strict.
