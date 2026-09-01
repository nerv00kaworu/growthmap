# Third-party notices and inventory

Third-party components are available under their respective licenses. This file is an index, not a guessed or hand-maintained complete dependency list.

The authoritative inventory is the production lockfile(s) and any licenses packaged with the released application. Current package-manager inputs include `website/package-lock.json`, `desktop/package-lock.json`, `src/frontend/package-lock.json`, and `src/backend/requirements.lock`.

To inspect a JavaScript package inventory, use the package's own lockfile with the installed package manager (for example `npm ci` followed by `npm ls --all` in that package directory). For backend inventory, use `src/backend/requirements.lock` and the environment's package metadata. Packaging and legal review must generate and verify the release's notices before relying on them for distribution; this document does not replace that review.
