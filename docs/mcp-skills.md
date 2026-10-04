# Repository documentation as MCP skills

The MCP image serves one SEP-2640 skill per customer-facing page
in the public site's `tutorials/`, `guides/`, `reference/`, and `explanation/`
sections. These are the documentation sections in the site's navigation.
Internal `docs/`, repository READMEs, landing pages and blog posts are excluded.

Examples: `tutorials-first-program`, `guides-use-from-code`, `reference-mcp`,
and `explanation-code-mode`. Each `SKILL.md` contains one page's full text,
with only its linked public-documentation assets in the manifest. Links to
other site documentation pages select their separate `skill://` entrypoints,
including the site's clean URLs. Names retain nested topics in the source path.

The sole MCP image serves these skills for every session. The container
build checks isolation, name collisions, resource links, and SEP-2640 limits.
It compiles the reviewed upstream implementation at immutable commit
`723fe32d4cc31c18f8255af2639059f7d8450324`; the pin is in
`images/mcp-js/Dockerfile`.

Build from the repository root:

```sh
docker build -f images/mcp-js/Dockerfile -t browserjs/mcp-js:dev .
```

The images workflow publishes `<registry>/mcp-js:<commit>` and `:main`.
Production templates and the warm pool use the same immutable image digest.
Skills, runtime imports, and policy-gated HTTP(S) fetch are features of this
image. There is no per-user image selection or separate skills rollout.

## Rollout and verification

Use the standard GitOps release. Build and deploy the MCP image with any
required backend and policy operator changes. New cold and warm sessions
then receive the same MCP build; existing sessions retain their image until
they are restarted. The release canary creates a temporary ordinary session
and checks skills discovery, separate manifests, and page/asset hashes,
alongside fetch and editable fetch permissions. It deletes its test session.

For a compatible Pi client, connect to the session's MCP URL and load a page:

```text
/mcp-skill computeruse skill://tutorials-first-desktop/SKILL.md Explain how to create a desktop
```

The client verifies the resource hashes and loads linked skills and assets
when needed. The catalog is read-only and tied to the image: documentation
edits require rebuilding the same MCP image. The pinned upstream version
uses its legacy initialize handshake; clients must use a compatible MCP
skills implementation.
