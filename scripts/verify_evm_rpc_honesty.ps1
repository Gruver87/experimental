# Formatter-only EVM RPC honesty checks (Experimental).
# Does not rebuild native, bake Docker, or probe the 3-node mesh.
# Soak is not started by this script.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

python -m pytest tests/unit/test_evm_rpc_compat.py tests/unit/test_rpc_methods.py tests/unit/test_rpc_adr0011.py tests/unit/test_silent_except_honesty.py tests/unit/test_eth_get_logs.py tests/unit/test_cors_receipt_ready_honesty.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python scripts/industrial_gate.py
exit $LASTEXITCODE
