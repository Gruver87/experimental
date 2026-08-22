param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function Test-RocksBuildPrereqs {
    if (Get-Command llvm-ar -ErrorAction SilentlyContinue) { return $true }
    if (Get-Command lib.exe -ErrorAction SilentlyContinue) { return $true }
    $llvmAr = @(
        "${env:ProgramFiles}\LLVM\bin\llvm-ar.exe",
        "${env:ProgramFiles(x86)}\LLVM\bin\llvm-ar.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($llvmAr) {
        $llvmBin = Split-Path $llvmAr -Parent
        $env:PATH = "$llvmBin;$env:PATH"
        return $true
    }
    Write-Host "WARN: LLVM/MSVC binutils not found. Install LLVM (winget install LLVM.LLVM) for RocksDB native build." -ForegroundColor Yellow
    return $false
}

$crate = Join-Path $ProjectRoot "native\abs_native"
Push-Location $crate
try {
    if (-not (Test-RocksBuildPrereqs)) {
        Write-Host "Skipping maturin build - RocksEngine will be unavailable on this host." -ForegroundColor Yellow
        exit 0
    }
    python -m pip install --upgrade maturin
    $wheelDir = Join-Path $crate "target\wheels"
    python -m maturin build --release --features pyo3/extension-module,libp2p --out $wheelDir
    $wheel = Get-ChildItem $wheelDir -Filter "*.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $wheel) {
        throw "abs_native wheel was not produced"
    }
    python -m pip install --force-reinstall $wheel.FullName
    python -c "import abs_native; print('abs_native OK:', abs_native.sha256_hex(b'absolute')[:16]); assert hasattr(abs_native, 'evm_run_until_halt'); rocks=hasattr(abs_native,'RocksEngine'); print('RocksEngine:', rocks); assert rocks or __import__('sys').platform!='linux', 'RocksEngine missing on Linux CI'; assert hasattr(abs_native,'libp2p_available') and abs_native.libp2p_available(), 'libp2p_available() false - rebuild with Cargo feature libp2p'"
}
finally {
    Pop-Location
}
