# Frontend Changes — Code Quality Tooling

Added automatic code formatting and linting to the front-end development workflow, and reformatted `frontend/` for consistency.

## Note on `black`

The request asked for `black`, which is a **Python** formatter. This work was scoped to front-end only, and `frontend/` is plain HTML/CSS/JS with no Python — so black cannot format it. **Prettier** was used instead as the direct front-end equivalent: an opinionated, config-light auto-formatter, the same role black plays for Python. No Python files were touched.

## Files added

| File | Purpose |
| --- | --- |
| `package.json` | Declares the dev dependencies and the quality scripts. Marked `private`; no runtime deps, so the app still has no build step. |
| `.prettierrc.json` | Prettier config: 100-col width (120 for HTML), 2-space indent, single quotes, semicolons, ES5 trailing commas, LF line endings. |
| `.prettierignore` | Restricts Prettier to `frontend/` — excludes `backend/`, `docs/`, `node_modules/`, lockfiles, and the Chroma DB. |
| `eslint.config.mjs` | ESLint flat config for `frontend/**/*.js`. Browser globals plus `marked` (loaded from CDN in `index.html`) declared readonly. |
| `scripts/quality.sh` | Read-only gate: checks formatting, then lints. Exits non-zero on first failure. |
| `scripts/format.sh` | Write mode: formats `frontend/` and applies safe ESLint auto-fixes. |

Both scripts auto-run `npm install` if `node_modules/` is missing, and `cd` to the repo root so they work from any directory.

## Files modified

- `.gitignore` — added `node_modules/`.
- `frontend/index.html`, `frontend/script.js`, `frontend/style.css` — reformatted by Prettier.

## Lint rules

- `eqeqeq` (error) — require `===`/`!==`
- `no-undef` (error) — catch typos and undeclared globals
- `no-var` (error) — `let`/`const` only
- `prefer-const` (warn)
- `no-unused-vars` (warn, ignoring `_`-prefixed args)

## Usage

```bash
npm install          # one-time

./scripts/format.sh  # auto-format + auto-fix
./scripts/quality.sh # verify only (CI / pre-commit)

# or directly:
npm run format       # Prettier --write
npm run format:check # Prettier --check
npm run lint         # ESLint
npm run lint:fix     # ESLint --fix
npm run quality      # format:check + lint
```

## Reformatting: what actually changed

The reformatting is **cosmetic only — no behavior changes**. Verified with `node --check` (syntax OK) and by reviewing the whitespace-insensitive diff (`git diff -w`). The non-whitespace changes are all formatting normalizations:

**JavaScript**
- Arrow-function params always parenthesized: `title =>` → `(title) =>`
- ES5 trailing commas added in multi-line object and argument lists
- Stray consecutive blank lines and trailing whitespace removed
- The long welcome-message `addMessage(...)` call wrapped across lines

**HTML**
- `<!DOCTYPE html>` → `<!doctype html>` (Prettier's normalization; semantically identical)
- Void elements self-closed: `<meta ...>` → `<meta ... />`
- Attribute-heavy tags (`<svg>`, the suggested-question `<button>`s) split one attribute per line
- One `data-question` value switched from `&quot;`-escaped double quotes to a single-quoted attribute — the attribute's decoded value is unchanged, and it is read via `getAttribute()`, so the queries sent to `/api/query` are identical
- Button label text moved onto its own line. This adds surrounding whitespace inside the element, but the labels are display-only and HTML collapses whitespace, so rendering is unaffected

**CSS**
- Consistent 2-space indent, one declaration per line, normalized spacing around `{`, `:`, and commas

## Verification

`./scripts/quality.sh` passes clean: Prettier reports "All matched files use Prettier code style!" and ESLint reports zero errors and zero warnings.

## Scope

Front-end only. No backend, Python, or RAG logic was modified, and no runtime dependency was added to the served page — `frontend/` is still static files with no build step.
