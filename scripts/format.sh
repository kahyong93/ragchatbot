#!/bin/bash
# Auto-format the front-end and apply safe ESLint fixes in place.
set -e

cd "$(dirname "$0")/.."

if [ ! -d "node_modules" ]; then
    echo "Installing front-end dev dependencies..."
    npm install
fi

echo "==> Formatting frontend/ (Prettier)"
npm run format

echo "==> Applying ESLint auto-fixes"
npm run lint:fix

echo ""
echo "Front-end formatting complete."
