#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export AIRFLOW_HOME="$SCRIPT_DIR/airflow"
export PYTHONPATH="$SCRIPT_DIR/src"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export no_proxy="*"
export PATH="$SCRIPT_DIR/.venv/bin:$PATH"

echo "AIRFLOW_HOME=$AIRFLOW_HOME"
echo "Password file: $AIRFLOW_HOME/simple_auth_manager_passwords.json.generated"
echo ""
echo "Credentials:"
echo "  Username: admin"
echo "  Password: $(python3 -c "import json; print(json.load(open('$AIRFLOW_HOME/simple_auth_manager_passwords.json.generated'))['admin'])" 2>/dev/null || echo '(read file above)')"
echo ""

airflow standalone
