# Changes — API Testing Infrastructure

Scope note: the requested work is backend test infrastructure. No frontend files
(`frontend/*.html|css|js`) were modified. This file records the changes as instructed.

## New files

### `backend/tests/__init__.py`
Makes the test directory a package.

### `backend/tests/conftest.py`
Shared fixtures:

- **Test data** — `sample_lessons`, `sample_course`, `sample_chunks`,
  `sample_query_response` (the `(answer, sources)` tuple `RAGSystem.query` returns),
  `sample_analytics`.
- **Mocks** — `mock_rag_system` (a `MagicMock` preconfigured with `query`,
  `get_course_analytics`, and `session_manager.create_session`), `mock_vector_store`.
- **App under test** — `create_test_app(rag_system)` rebuilds `/api/query`,
  `/api/courses`, and `/` with the same Pydantic models and handler logic as
  `backend/app.py`, but **without** `app.mount("/", StaticFiles(directory="../frontend"))`.
  That mount raises at import time whenever pytest runs from the repo root, which is
  why the routes are defined inline rather than imported. `/` returns a small JSON
  stand-in for the static frontend.
- **Client** — `test_app` and `client` (`TestClient` as a context manager, so
  lifespan events run).

`conftest.py` also prepends `backend/` to `sys.path` so the flat imports
(`config`, `models`, `rag_system`) resolve regardless of invocation directory.

### `backend/tests/test_api_endpoints.py`
15 tests, all marked `@pytest.mark.api`:

- **`/api/query`** — returns answer/sources/session_id; creates a session when none is
  supplied; reuses a supplied `session_id`; 422 on missing `query`; 422 on wrong type;
  empty query string accepted; empty sources serialize as `[]`; RAG exception → 500 with
  the message in `detail`; GET → 405.
- **`/api/courses`** — returns stats; handles an empty catalog; analytics exception → 500;
  POST → 405.
- **`/`** — reachable and returns JSON; unknown path → 404.

## Modified files

### `pyproject.toml`
Added a `[dependency-groups] dev` group (`pytest>=8.0`, `httpx>=0.27` — required by
`TestClient`) and `[tool.pytest.ini_options]`:

- `testpaths = ["backend/tests"]` and `pythonpath = ["backend"]` so `uv run pytest`
  works from the repo root.
- `addopts = ["-q", "--strict-markers", "--tb=short"]`.
- Registered markers: `api`, `unit`, `integration`.
- Warning filters for the noisy `DeprecationWarning`/`UserWarning` from chromadb and
  sentence-transformers.

## Running

```bash
uv sync            # installs the dev group
uv run pytest      # from the repo root
uv run pytest -m api
```

Result: **15 passed**.

---

# Frontend Changes — Dark/Light Theme Toggle

Adds an icon-based theme toggle in the top-right corner that switches the UI between the existing dark theme and a new light theme. Front-end only; no backend files touched.

## Files changed

- `frontend/index.html`
- `frontend/style.css`
- `frontend/script.js`

## `frontend/index.html`

- Added a `<button id="themeToggle" class="theme-toggle">` as the first child of `.container`, containing two inline SVGs: a sun (`.theme-icon-sun`) and a moon (`.theme-icon-moon`).
  - `type="button"`, `role="switch"`, `aria-checked`, `aria-label`, and `title` — the label/checked state are updated in JS on every toggle.
  - Both SVGs are `aria-hidden="true"` so screen readers announce only the button label.
- Added a small inline script in `<head>` that reads the stored preference (or the OS `prefers-color-scheme`) and sets `data-theme` on `<html>` **before first paint**, preventing a flash of the wrong theme.
- Bumped the cache-busting query strings on `style.css` and `script.js` from `v=9` to `v=10`.

## `frontend/style.css`

- Added `--code-bg` to `:root` and replaced the two hardcoded `rgba(0,0,0,0.2)` code/pre backgrounds with it (the hardcoded value looked wrong on a light background).
- Added a `[data-theme="light"]` block redefining the full variable palette (background, surface, surface-hover, text, borders, shadow, focus ring, welcome colors, code background). The dark values stay on `:root`, so dark remains the default with no attribute set.
- Added `.theme-toggle` styles: fixed to `top: 1.25rem; right: 1.25rem`, 44×44 circular button using the existing `--surface` / `--border-color` / `--shadow` tokens, matching the app's rounded, subtle-elevation aesthetic. Hover lifts and tints toward `--primary-color`; `:active` scales down slightly; `:focus-visible` uses the same `--focus-ring` treatment as the chat input and send button.
- Icon transition: both icons are absolutely positioned and crossfade with a rotate+scale over 0.3s — sun visible in dark mode (click → light), moon visible in light mode.
- Added a 0.3s `background-color`/`color`/`border-color` transition to `body` and the main themed surfaces (sidebar, chat areas, messages, stat items, suggested items, chat input) so the theme swap animates smoothly rather than snapping.
- Added a `prefers-reduced-motion: reduce` rule that disables the toggle's transitions.

## `frontend/script.js`

- Added `themeToggle` to the DOM element list, resolved on `DOMContentLoaded`.
- `initTheme()` runs before `setupEventListeners()`: reads `localStorage.themePreference`, falls back to the OS `prefers-color-scheme`, defaults to dark.
- `applyTheme(theme)` sets `data-theme` on `<html>` and syncs `aria-checked` (checked = dark) plus a descriptive `aria-label`/`title` ("Switch to light theme" / "Switch to dark theme").
- `toggleTheme()` flips the theme and persists it to `localStorage`.
- All `localStorage` access is wrapped in `try/catch` so private-browsing mode degrades to a session-only theme instead of throwing.
- The toggle is wired with a single `click` listener. Because it is a native `<button>`, Enter and Space activate it automatically and it is in the normal tab order — no custom key handling needed.

## Accessibility notes

- Native `<button>`: keyboard focusable, activated by Enter/Space, exposed as a switch with its on/off state.
- Visible focus ring via `:focus-visible`, consistent with existing controls.
- Label text changes to describe the action the button will perform.
- Motion respects `prefers-reduced-motion`.

---

# Part 2 — Light Theme Palette Completion & Full Tokenization

A follow-up pass covering the light-theme variable set, contrast/accessibility, and making *every* existing element theme-aware. The toggle button, `data-theme` attribute, click handler, and transitions were already delivered in Part 1; this pass closes the gaps where hardcoded colors bypassed the variable system.

## Additional theme tokens (`frontend/style.css`)

Colors that were hardcoded in rules — and therefore frozen at their dark-theme values — are now tokens defined in both `:root` (dark) and `[data-theme="light"]`:

| Token | Dark | Light | Used by |
|---|---|---|---|
| `--on-primary` | `#ffffff` | `#ffffff` | user message bubble text, send button icon |
| `--welcome-shadow` | `rgba(0,0,0,.2)` | `rgba(15,23,42,.08)` | welcome message card |
| `--primary-glow` | `rgba(37,99,235,.3)` | `rgba(37,99,235,.25)` | send button hover shadow |
| `--error-bg` / `--error-border` / `--error-text` | red tints, `#f87171` | softer tints, `#b91c1c` | `.error-message` |
| `--success-bg` / `--success-border` / `--success-text` | green tints, `#4ade80` | softer tints, `#15803d` | `.success-message` |

The status text colors are the important ones: `#f87171` and `#4ade80` are light-on-dark tints that drop to roughly 2:1 on a white background. The light theme substitutes darker variants (`#b91c1c`, `#15803d`) that pass AA.

## Bugs found and fixed

- **`.message-content blockquote` referenced `var(--primary)`, which is not defined anywhere** (the token is `--primary-color`). The border-left color silently fell back to `currentColor`. Pre-existing in both themes; now points at `--primary-color`.
- **`--assistant-message` was declared but never used** — assistant bubbles used `--surface`, making them identical to the sidebar. Now wired to `.message.assistant .message-content`, so the user/assistant distinction holds in both themes.
- **`--welcome-bg` / `--welcome-border` were declared but never used** — the welcome card used `--surface` / `--border-color`. Now wired up, restoring its intended emphasis treatment in both themes.

## Elements verified theme-aware

After this pass, the only remaining literal colors in the stylesheet are inside the two variable blocks, plus the `header h1` gradient — and `header` is `display: none`, so it renders in neither theme and was intentionally left untouched rather than churning dead styles.

## Accessibility verification (measured, not assumed)

WCAG 2.1 contrast ratios computed for both palettes, with alpha-tinted backgrounds composited against their parent surface first:

| Pair | Light | Dark |
|---|---|---|
| text-primary on background | 17.85 (AAA) | 16.30 (AAA) |
| text-secondary on background | 7.58 (AAA) | 6.96 (AA) |
| text-secondary on surface | 6.92 (AA) | 5.71 (AA) |
| primary-color on background | 5.17 (AA) | — |
| on-primary on user bubble | 5.17 (AA) | — |
| text-primary on assistant bubble | 14.48 (AAA) | 9.41 (AAA) |
| text-primary on welcome-bg | 14.97 (AAA) | 10.50 (AAA) |
| error-text on error-bg | 5.83 (AA) | 5.92 (AA) |
| success-text on success-bg | 4.60 (AA) | 8.81 (AAA) |

**Every pair meets or exceeds WCAG AA (4.5:1) in both themes.** The tightest margin is light-theme success text at 4.60.

## Design language preserved

The light theme reuses the same slate ramp as the dark theme (Tailwind-style `#f1f5f9` / `#e2e8f0` / `#cbd5e1` / `#475569` / `#0f172a`), inverted rather than re-invented. Primary blue `#2563eb` and hover `#1d4ed8` are unchanged across both themes, so brand color, spacing, radii, and visual hierarchy stay identical — only the surface/text polarity flips.

## Verification status

- Contrast ratios: **computed and confirmed** via a WCAG luminance script (all AA or better).
- Variable coverage: **confirmed** by grepping the stylesheet for literal color values; none remain outside the theme blocks.
- Browser rendering: **not run.** To check manually: `./run.sh`, open `http://localhost:8000`, toggle the top-right icon, and confirm the palette swaps smoothly, the icon crossfades, and the choice survives a reload.

---

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
