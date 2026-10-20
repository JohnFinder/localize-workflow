# Localize Workflow agent guidance

- Keep this repository a reusable localization tool. Do not import production app catalogs, translation caches, personal files, credentials, or private endpoint configuration.
- Translate app UI only through the project-configured `translategemma-27b-it` 27B service. The English source is generated through that model. Do not invent translations, substitute another model, or call a cloud translator.
- Do not mark machine output as linguistically reviewed. Preserve `needs_review` until a person checks the wording and in-app layout.
- Treat `examples/` as fictional input. `media/rosettica-workspace.png` is a reviewed empty-state public distribution image; it is the only app screenshot approved for this draft.
- Keep service URL and key in `LOCALIZE_BASE_URL` and `LOCALIZE_API_KEY`; never write them into source, logs, examples, or commits.
- Run `python3 scripts/check_release.py` before a public release, inspect all files and images, and publish only after the owner approves the final artifact.
