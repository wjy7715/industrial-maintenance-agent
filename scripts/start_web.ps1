$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ParentVenv = Join-Path (Split-Path -Parent $ProjectRoot) ".venv\Scripts\streamlit.exe"
$LocalVenv = Join-Path $ProjectRoot ".venv\Scripts\streamlit.exe"

if (Test-Path -LiteralPath $LocalVenv) {
    $Streamlit = $LocalVenv
} elseif (Test-Path -LiteralPath $ParentVenv) {
    $Streamlit = $ParentVenv
} else {
    throw "未找到 Streamlit。请创建虚拟环境并运行 pip install -r requirements.txt"
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
& $Streamlit run (Join-Path $ProjectRoot "app.py") --server.port 8502
