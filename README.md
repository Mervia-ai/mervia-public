# Mervia public

Open-source pieces of [Mervia](https://mervia.ai), the AI marketing agent for e-commerce stores.
Each top-level directory is an independent project with its own README, tests and versioning.

| Directory | What it is |
| --- | --- |
| [`mervia-store-connector/`](mervia-store-connector/) | Connect a store that is not on Shopify to Mervia: the HTTP contract as code (OpenAPI + JSON Schemas), `mervia-check` (a conformance checker a store's team runs against their staging site), and per-platform SDKs (`sdk/laravel/` first). |

## Contributing

Issues and pull requests are welcome. Each project's README says how to run its tests; the
[CI workflow](.github/workflows/ci.yml) runs all of them on every push and pull request.

## License

MIT for every project in this repository unless a directory states otherwise. See [LICENSE](LICENSE).
