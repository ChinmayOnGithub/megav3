#!/bin/bash
# Cleanup script - removes unnecessary documentation files
# Keeps only functional code

echo "Removing unnecessary documentation files..."

# Remove all documentation files
rm -f COMMAND_SUMMARY.txt
rm -f EXECUTION_CHECKLIST.md
rm -f EXECUTION_COMMANDS.sh
rm -f PERMANENT_SETUP_COMMANDS.txt
rm -f QUICK_COMMANDS.txt
rm -f START_HERE.md
rm -f STEP_BY_STEP_COMMANDS.txt

# Remove empty directories
rmdir mega 2>/dev/null

echo "✅ Cleanup complete!"
echo ""
echo "Remaining essential files:"
ls -1 *.py *.txt 2>/dev/null | grep -v requirements.txt
echo ""
echo "Essential directories:"
echo "  app/        - Application code"
echo "  scaler/     - Scaling logic"
echo "  k8s/        - Kubernetes manifests"
