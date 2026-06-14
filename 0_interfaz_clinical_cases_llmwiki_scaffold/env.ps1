# Carga el Python del proyecto en la sesion actual de PowerShell.
#
# Por defecto usa el `python` que ya este en PATH. Si quieres fijar un
# interprete concreto, define la variable de entorno CLINICAL_CASES_PYTHON
# antes de cargar este script, por ejemplo:
#
#   $env:CLINICAL_CASES_PYTHON = "C:\ruta\a\Python311\python.exe"
#   . .\env.ps1

if ($env:CLINICAL_CASES_PYTHON) {
    Set-Alias -Name python -Value $env:CLINICAL_CASES_PYTHON -Scope Global
    Write-Host "python -> $env:CLINICAL_CASES_PYTHON"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    Write-Host "Usando el lanzador 'py -3' del sistema (alias no modificado)."
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host "Usando el 'python' del PATH: $((Get-Command python).Source)"
} else {
    Write-Warning "No se encontro Python. Instala Python 3.11+ o define CLINICAL_CASES_PYTHON."
}
