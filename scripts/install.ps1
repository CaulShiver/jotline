# Install the latest published Jotline wheel on Windows.
# Linux and macOS use: curl -fsSL .../install.py | python3
$ErrorActionPreference = 'Stop'
$uri = 'https://github.com/CaulShiver/jotline/releases/latest/download/install.py'
$dest = Join-Path ([System.IO.Path]::GetTempPath()) 'jotline-install.py'
Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $dest
$py = @(
    (Get-Command py -ErrorAction SilentlyContinue),
    (Get-Command python3 -ErrorAction SilentlyContinue),
    (Get-Command python -ErrorAction SilentlyContinue)
) | Where-Object { $_ } | Select-Object -First 1
if (-not $py) {
    throw 'Jotline needs Python 3.11+ on PATH as py or python. Windows is supported; WSL is optional.'
}
if ($py.Name -eq 'py.exe' -or $py.Name -eq 'py') {
    & $py.Source -3 $dest @args
} else {
    & $py.Source $dest @args
}
exit $LASTEXITCODE
