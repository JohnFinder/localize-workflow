---
name: localize-apple-app
description: Incrementally localize Apple String Catalogs with a project-approved local TranslateGemma 27B service, preserving provenance and review states. Use when adding or updating app UI strings in a project configured for this workflow.
---

# Localize an Apple app

Use the project's `project.json`, source registry, and catalog paths. The self-contained CLI is [scripts/localize.py](scripts/localize.py), resolved relative to this skill. Invoke it with the target project's configuration path. The toolkit repository also provides a root `localize.py` launcher. Keep credentials in `LOCALIZE_BASE_URL` and `LOCALIZE_API_KEY`; do not read secrets from another repository or include them in outputs.

1. Identify only the new or changed stable keys. Add the original text and UI context to the source registry. Leave user documents, protocol values, and technical symbols out of UI localization.
2. Run the bundled CLI with `python3 <skill-folder>/scripts/localize.py --config <project-config> plan --keys key1 key2`, replacing the path markers with resolved local paths. Use the same `--keys` scope for translation, export, and verification; do not expand into unrelated pending work.
3. Run `translate` only with the configured `translategemma-27b-it` 27B service. For non-English originals, the tool requests English first, then target locales from English. Original English supplied by the project is retained as source text. Never use a coding model or an unapproved fallback to fill missing values.
4. Run `export`, then `verify`. Inspect the diff, placeholders, plural or substitution entries, and the app layout. Keep machine output at `needs_review` until a qualified reviewer accepts it. A catalog's presence alone is not a quality claim.
5. Before preparing anything public, inspect the intended file set and images for user data, credentials, local paths, and app-specific content. When preparing the toolkit repository itself, also run its `scripts/check_release.py`. Keep production app catalogs and translation caches out of a public toolkit copy. Do not publish or upload without the owner's direction.

The toolkit fails on conflicting existing catalog values and plural/substitution structures instead of overwriting them. Resolve those cases in the app project with explicit review. The agent may adapt the workflow to another project, but must keep that project's localization and release rules authoritative.

This skill and its code use the included Apache 2.0 [LICENSE](LICENSE). TranslateGemma model weights retain their separate Gemma Terms of Use; the skill contains no weights.
