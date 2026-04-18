#!/bin/bash
# ============================================================
#  OMNIX — Push to GitHub + Enable GitHub Pages
#  Run this on your local machine (not in a container)
# ============================================================
#
#  Prerequisites:
#    1. Install GitHub CLI: https://cli.github.com
#    2. Run: gh auth login
#
#  Usage:
#    chmod +x DEPLOY.sh && ./DEPLOY.sh
# ============================================================

set -e

echo ""
echo "=========================================="
echo "  OMNIX Deployment Script"
echo "=========================================="
echo ""

# ── Step 1: Check gh is installed and authenticated ──
if ! command -v gh &> /dev/null; then
    echo "ERROR: GitHub CLI (gh) is not installed."
    echo "Install it from: https://cli.github.com"
    echo ""
    echo "  macOS:   brew install gh"
    echo "  Windows: winget install GitHub.cli"
    echo "  Linux:   https://github.com/cli/cli/blob/trunk/docs/install_linux.md"
    exit 1
fi

echo "Checking GitHub authentication..."
if ! gh auth status 2>/dev/null; then
    echo ""
    echo "You need to log in first. Running: gh auth login"
    gh auth login
fi

GITHUB_USER=$(gh api user -q .login)
echo "Authenticated as: $GITHUB_USER"
echo ""

# ── Step 2: Create the repo ──
REPO_NAME="omnix"
echo "Creating public repo: $GITHUB_USER/$REPO_NAME"

if gh repo view "$GITHUB_USER/$REPO_NAME" &>/dev/null; then
    echo "Repo already exists! Using existing repo."
else
    gh repo create "$REPO_NAME" --public --description "OMNIX — One App. Any Robot. Zero Limits. Universal robotics control platform." --homepage "https://$GITHUB_USER.github.io/$REPO_NAME"
    echo "Repo created!"
fi

# ── Step 3: Push the code ──
echo ""
echo "Pushing code to GitHub..."
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/$GITHUB_USER/$REPO_NAME.git"
git push -u origin main

echo "Code pushed!"

# ── Step 4: Enable GitHub Pages ──
echo ""
echo "Enabling GitHub Pages (serving from main branch, root)..."

# Enable Pages via the API
gh api repos/$GITHUB_USER/$REPO_NAME/pages \
    --method POST \
    -f "build_type=workflow" \
    -f "source[branch]=main" \
    -f "source[path]=/" 2>/dev/null || \
gh api repos/$GITHUB_USER/$REPO_NAME/pages \
    --method PUT \
    -f "build_type=legacy" \
    -f "source[branch]=main" \
    -f "source[path]=/frontend" 2>/dev/null || \
echo "(Pages may need to be enabled manually — see instructions below)"

# ── Step 5: Create GitHub Pages workflow ──
mkdir -p .github/workflows

cat > .github/workflows/pages.yml << 'WORKFLOW_EOF'
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Pages
        uses: actions/configure-pages@v5
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: 'frontend'
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
WORKFLOW_EOF

git add .github/workflows/pages.yml
git commit -m "Add GitHub Pages deployment workflow"
git push

echo ""
echo "=========================================="
echo "  DONE!"
echo "=========================================="
echo ""
echo "  GitHub Repo:    https://github.com/$GITHUB_USER/$REPO_NAME"
echo ""
echo "  GitHub Pages (will be live in ~2 minutes):"
echo "    Landing:  https://$GITHUB_USER.github.io/$REPO_NAME/landing.html"
echo "    Demo:     https://$GITHUB_USER.github.io/$REPO_NAME/demo.html"
echo "    Stats:    https://$GITHUB_USER.github.io/$REPO_NAME/stats.html"
echo ""
echo "  To deploy the backend on Render (free):"
echo "    1. Go to https://dashboard.render.com"
echo "    2. Click 'New' → 'Web Service'"
echo "    3. Connect your GitHub repo: $GITHUB_USER/$REPO_NAME"
echo "    4. Render will auto-detect render.yaml — just click Deploy!"
echo ""
echo "  Or on Railway:"
echo "    1. Go to https://railway.app"
echo "    2. Click 'New Project' → 'Deploy from GitHub repo'"
echo "    3. Select $GITHUB_USER/$REPO_NAME"
echo "    4. Railway will auto-detect railway.json"
echo ""
