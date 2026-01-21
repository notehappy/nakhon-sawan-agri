#!/bin/bash

# --- Configuration ---
PROJECT_DIR="/home/main-server/2025_GIZ/nakhonsawan_activefire"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

# 1. Navigate to the project folder
echo "📂 Navigating to: $PROJECT_DIR"
cd "$PROJECT_DIR" || { echo "❌ Error: Directory not found!"; exit 1; }

# 2. Stage all changes
echo "➕ Adding files..."
git add .

# 3. Commit with a dynamic timestamp
echo "💾 Committing changes..."
git commit -m "Update data/script - $TIMESTAMP"

# 4. Push to GitHub
echo "🚀 Pushing to GitHub..."
git push

echo "✅ Success! Streamlit will update automatically in ~2 minutes."