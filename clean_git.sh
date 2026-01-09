#!/bin/bash

# ---------------------------------------------
# Git cleanup & force push script
# Removes dangling commits, compresses repo,
# and force pushes to remote.
# ---------------------------------------------

echo "🚀 Cleaning Git repository..."

# Expire old reflog entries
git reflog expire --expire=now --all
echo "✅ Reflog expired"

# Aggressive garbage collection & prune unreachable objects
git gc --prune=now --aggressive
echo "✅ Garbage collection complete"

# Force push current branch to origin
git push --force
echo "✅ Force push complete"

echo "🎉 Git cleanup finished!"
