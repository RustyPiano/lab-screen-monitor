param(
    [ValidateSet("auto", "feishu", "wecom")]
    [string]$Provider = "auto"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$configPath = Join-Path $projectRoot "config.local.json"

if ($Provider -eq "auto" -and (Test-Path $configPath)) {
    try {
        $config = Get-Content $configPath -Raw | ConvertFrom-Json
        if ($config.PUSH_PROVIDER) {
            $Provider = $config.PUSH_PROVIDER
        }
    }
    catch {
        Write-Host "读取 config.local.json 失败，继续按 wecom 安装基础依赖。"
        $Provider = "wecom"
    }
}

if ($Provider -eq "auto") {
    $Provider = "wecom"
}

$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue

if ($py) {
    & py -3 -m venv (Join-Path $projectRoot ".venv")
}
elseif ($python) {
    & python -m venv (Join-Path $projectRoot ".venv")
}
else {
    throw "未找到 Python。请先安装 Python 3.10+，并确保 py 或 python 可用。"
}

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pipMirror = "-i https://pypi.tuna.tsinghua.edu.cn/simple"
& $pythonExe -m pip install --upgrade pip setuptools wheel $pipMirror

# ROI 框选依赖 OpenCV GUI 能力，Windows 交付包必须安装非 headless 版本。
& $pythonExe -m pip uninstall -y opencv-python-headless | Out-Null

$packages = @(
    "numpy",
    "opencv-python",
    "mss"
)

if ($Provider -eq "feishu") {
    $packages += "lark-oapi"
}

& $pythonExe -m pip install $pipMirror @packages

Write-Host ""
Write-Host "安装完成。"
Write-Host "项目目录: $projectRoot"
Write-Host "Python: $pythonExe"
Write-Host "推送渠道依赖: $Provider"
Write-Host "下一步:"
Write-Host "1. 复制 config.example.json 为 config.local.json 并填写配置"
Write-Host "2. 运行 scripts\\windows\\check.bat"
