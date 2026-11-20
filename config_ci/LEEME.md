# Archivos de integración continua

Por seguridad, estos dos archivos no se pueden crear directamente en sus rutas finales desde la herramienta.
Muévelos así antes de subir el repositorio a GitHub:

| Archivo aquí | Ruta final |
|---|---|
| `ci.yml` | `.github/workflows/ci.yml` |
| `pre-commit-config.yaml` | `.pre-commit-config.yaml` (en la raíz del proyecto, con el punto inicial) |

En PowerShell, desde la carpeta del proyecto:
```powershell
New-Item -ItemType Directory -Force .github\workflows | Out-Null
Move-Item config_ci\ci.yml .github\workflows\ci.yml
Move-Item config_ci\pre-commit-config.yaml .pre-commit-config.yaml
```
