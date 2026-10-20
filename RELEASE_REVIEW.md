# Initial source release review

This initial source release packages the reusable workflow, portable agent skill, fictional examples, and reviewed showcase assets. The owner has authorized its public initial push.

## Included material

- New reusable localization CLI and a portable agent skill containing the same implementation.
- Three fictional source strings, an empty example String Catalog, and public configuration without credentials.
- English README, an eight-second code-rendered video and GIF, a poster, an editable standalone HTML animation, and a catalog-label illustration.
- One Rosettica empty-state screenshot from the October 8, 2026 distribution asset set, version 1.2.7. EXIF and textual PNG metadata were removed from the public copy and its embedded HTML resource. Image pixels were preserved.
- Apache 2.0 code license, with the model's separate Gemma terms and app-branding ownership explained.

## Privacy boundary

No production app catalog, model output cache, user document, service configuration, local absolute path, account identity, or model weight is intentionally included. The release manifest lists the intended files and hashes the reviewed media. Adding or replacing a file requires another review.

## Verification and remaining work

The CLI's planning command and the skill structure are validated. The supplied example intentionally contains no translations, so it cannot pass catalog-completeness verification until a real approved model run has populated it. Offline structural checks use temporary original-source fixtures; they are not model-generated translations and are not included in the release.

The video was checked at 1280 × 720, 30 fps, eight seconds, 240 frames, H.264, with a successful full decode. Opening, main, and ending images were inspected. Text and image review does not establish that the current App Store build matches the older capture.

The service adapter has not been validated against a live 27B endpoint in this task. Confirm a small scoped translation run, arrange language review, refresh the app captures where needed, and review final repository identity and history before declaring a production-ready release.
