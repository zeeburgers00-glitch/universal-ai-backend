# Integration guide

## Catalog versus integration

- `catalog_only`: metadata and links only.
- `external-service`: expects a separately deployed service and credentials.
- `python-library`: requires a reviewed package, pinned dependency, adapter, and tests.
- `provider-adapter`: callable from the backend only after server-side credentials and routing are configured.

A repository appearing in the catalog or GitHub discovery output does not mean it is installed or safe.

## Add a repository to the catalog

Add a JSON object to `catalog/tools.json` with a unique `id`, human-readable `name`, `category`, `description`, upstream `repository_url`, `license` review note, `integration_type`, `status`, and `capabilities`.

You can also call `POST /v1/tools` with `X-API-Key`. This starter's in-memory write does not persist across Vercel cold starts. For production writes, back this route with PostgreSQL/Supabase.

## Add executable behavior

1. Review the upstream source, its license, dependency provenance, maintainer history, permissions, and threat model.
2. Define an adapter with typed input/output schemas, timeouts, rate limits, and clear error handling.
3. Store provider credentials in server environment variables or a secret manager.
4. Do not execute user-supplied shell commands or install arbitrary repositories inside the API process.
5. Place untrusted/side-effectful tools in isolated workers with scoped credentials and audit logs.
6. Require user approval for actions that publish content, alter files or accounts, spend money, or control a desktop.
7. Add tests and only then mark the integration as tested.

## Live GitHub discovery

`GET /v1/discover/github?q=browser+automation&per_page=20` queries GitHub Search API at request time. GitHub may rate-limit requests. Configure `GITHUB_TOKEN` server-side for higher limits. Results should be reviewed before registration.


## Expanded catalog sources and license filters

The API loads seven catalogs in this order: `catalog/tools.json`, `catalog/extended.json`, `catalog/commercial.json`, `catalog/llmops.json`, `catalog/voice_media.json`, `catalog/mcp_ecosystem.json`, and `catalog/global_ai_directory.json`. Duplicate repository URLs are merged and the original seed IDs are preserved.

In addition, `catalog/rea_mcp_tools.json` captures the `229` MCP tools, `6` guided prompts, and `180` CLI commands exposed by [REA (`morluto/rea`)](https://github.com/morluto/rea), along with cryptographic Evidence IDs from static JavaScript application-graph verification of official MCP packages. Query REA metadata via `GET /v1/rea/status` and `GET /v1/rea/tools`. Always follow upstream `DISCLAIMER.md` responsible-use boundaries: only inspect software, bundles, websites, or model files you own or are authorized to analyze.


- `GET /v1/catalog/stats` shows current entry totals, categories, and license review statuses.
- `GET /v1/catalog/sources` lists the curated directories used for discovery and explains the classification policy.
- `GET /v1/tools?license_status=review_required` returns entries whose licenses still need verification.
- `GET /v1/tools?source_classification=source_available` can narrow candidate classifications by substring.
- `GET /v1/discover/github?q=agent+framework&license_filter=apache-2.0&min_stars=100&sort=stars` queries current public GitHub metadata.

This catalog includes three distinct concepts: a project's source license, the license of model weights/data, and the terms for a hosted API or enterprise edition. An open-source SDK for a paid hosted API does not make that hosted API or its models open-source. "Source available" and fair-code projects may have restrictions that differ from OSI-approved licenses.

The catalog is not a universal inventory. A project being indexed does not mean its code is installed, safe, compatible, or tested. Review the exact upstream commit, license, dependencies, commercial terms, and required permissions before implementing an adapter.


## LLMOps tool candidates

The `catalog/llmops.json` file adds candidate references covering LLM gateway/router layers, tracing and observability, evaluation and safety testing, and prompt management. It includes source-reported license hints, inactive/archived markers when provided by the source list, and upstream links. Treat all candidates as review-required and validate current license and project status before integration.
