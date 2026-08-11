#!/bin/bash
# Front-end code quality checks (read-only).
# Verifies formatting with Prettier and lints JS with ESLint.
# Exits non-zero on the first failure so it can gate CI or a pre-commit hook.
set -e

cd "$(dirname "$0")/.."

if [ ! -d "node_modules" ]; then
    echo "Installing front-end dev dependencies..."
    npm install
fi

echo "==> Checking formatting (Prettier)"
npm run format:check

echo "==> Linting JavaScript (ESLint)"
npm run lint

echo ""
echo "All front-end quality checks passed."
