param([string]$Python = "$PSScriptRoot/.venv/Scripts/python.exe")
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath $Python)) { throw '请先安装 Python 3.12 x64 构建依赖。' }
& $Python tools/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw '许可证收集失败。' }
& $Python -m PyInstaller --noconfirm ATV-subshift.spec
if ($LASTEXITCODE -ne 0) { throw '打包失败。' }
& $Python tools/verify_release.py
if ($LASTEXITCODE -ne 0) { throw '成品自检失败。' }
Copy-Item -LiteralPath README.md,README.zh-CN.md,MODEL-CATALOG.md,MODEL-ATTRIBUTION.md,THIRD-PARTY-NOTICES.md,RELEASE-NOTES.zh-CN.md,LICENSE,RIGHTS-WAIVER.zh-CN.md,AI-GENERATED.md -Destination 'dist/ATV subshift'
Copy-Item -LiteralPath docs -Destination 'dist/ATV subshift/docs' -Recurse -Force
& $Python tools/package.py
if ($LASTEXITCODE -ne 0) { throw '压缩包生成失败。' }
