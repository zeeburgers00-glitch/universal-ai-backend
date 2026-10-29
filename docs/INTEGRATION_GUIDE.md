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
