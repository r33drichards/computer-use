#!/usr/bin/env bash
# Regenerates docs/ from the provider's schema and examples/.
#   hack/generate-docs.sh [tofu|terraform] [tfplugindocs version]
set -euo pipefail

tf="${1:-tofu}"
version="${2:-v0.25.0}"
here="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

[ -x "$here/terraform-provider-computeruse" ] || (cd "$here" && go build -o terraform-provider-computeruse .)

cat > "$work/rc" <<RC
provider_installation {
  dev_overrides {
    "r33drichards/computeruse" = "$here"
  }
  direct {}
}
RC
cat > "$work/main.tf" <<'TF'
terraform {
  required_providers {
    computeruse = { source = "r33drichards/computeruse" }
  }
}
TF

# tfplugindocs looks the provider up as registry.terraform.io/hashicorp/<name>;
# the schema is keyed by the address in main.tf on whichever registry host the
# binary assumes. There is one provider, so rename its key.
(cd "$work" && TF_CLI_CONFIG_FILE="$work/rc" "$tf" providers schema -json |
  jq '.provider_schemas |= with_entries(.key = "registry.terraform.io/hashicorp/computeruse") |
      .provider_schemas[].resource_schemas |= with_entries(.key = "computeruse_" + .key) |
      .provider_schemas[].data_source_schemas |= with_entries(.key = "computeruse_" + .key)' > schema.json)

# tfplugindocs requires provider-prefixed schema keys. Stage aliases only for
# rendering; the actual provider schema and HCL examples keep unprefixed types.
mkdir -p "$work/examples/resources" "$work/examples/data-sources"
cp -R "$here/examples/provider" "$work/examples/provider"
for kind in resources data-sources; do
  for example in "$here/examples/$kind"/*; do
    cp -R "$example" "$work/examples/$kind/computeruse_$(basename "$example")"
  done
done

cd "$here"
go run "github.com/hashicorp/terraform-plugin-docs/cmd/tfplugindocs@$version" generate \
  --provider-dir "$work" \
  --provider-name computeruse \
  --rendered-provider-name computeruse \
  --providers-schema "$work/schema.json"

# Remove the rendering-only aliases from generated titles and type references.
for doc in "$work/docs/index.md" "$work/docs/resources"/*.md "$work/docs/data-sources"/*.md; do
  sed 's/computeruse_session_policy/session_policy/g; s/computeruse_sessions/sessions/g; s/computeruse_session/session/g' "$doc" > "$doc.tmp"
  mv "$doc.tmp" "$doc"
done
rm -rf "$here/docs"
cp -R "$work/docs" "$here/docs"
