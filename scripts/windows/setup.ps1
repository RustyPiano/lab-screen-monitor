
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$configPath  = Join-Path $projectRoot "config.local.json"
$venvPython  = Join-Path $projectRoot ".venv\Scripts\python.exe"

# ── 辅助函数 ──────────────────────────────────────────────────────────────────

function Write-Title($text) {
    Write-Host ""
    Write-Host "══════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "══════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step($num, $total, $text) {
    Write-Host ""
    Write-Host "[$num/$total] $text" -ForegroundColor Yellow
}

function Write-OK($text) {
    Write-Host "  √ $text" -ForegroundColor Green
}

function Write-Fail($text) {
    Write-Host "  × $text" -ForegroundColor Red
}

# 必填输入：为空则循环重问
function Prompt-Required($prompt) {
    do {
        $value = Read-Host "  $prompt"
    } until (-not [string]::IsNullOrWhiteSpace($value))
    return $value.Trim()
}

# 带默认值输入：直接回车使用默认
function Prompt-WithDefault($prompt, $default) {
    $value = Read-Host "  $prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($value)) { return $default }
    return $value.Trim()
}

# 是/否提示，$defaultYes=$true 表示默认是
function Prompt-YesNo($prompt, $defaultYes) {
    $hint = if ($defaultYes) { "[Y/n]" } else { "[y/N]" }
    $value = Read-Host "  $prompt $hint"
    if ([string]::IsNullOrWhiteSpace($value)) { return $defaultYes }
    return $value -match "^[yY]"
}

# ── 主流程 ────────────────────────────────────────────────────────────────────

Write-Title "自动截屏发送 - 安装向导"

# ── [1/5] 检查 Python ─────────────────────────────────────────────────────────

Write-Step 1 5 "检查 Python 环境..."

$py     = Get-Command py     -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue

if ($py) {
    $ver = & py -3 --version 2>&1
    Write-OK $ver
} elseif ($python) {
    $ver = & python --version 2>&1
    Write-OK $ver
} else {
    Write-Fail "未找到 Python，请先安装 Python 3.10+ 并确保 py 或 python 命令可用"
    Read-Host "`n  按回车退出"
    exit 1
}

# ── [2/5] 配置 ────────────────────────────────────────────────────────────────

Write-Step 2 5 "配置推送设置"

$doConfig    = $true
$enableLaser = $false
$providerStr = "wecom"

if (Test-Path $configPath) {
    Write-Host "  检测到已有配置文件 config.local.json" -ForegroundColor DarkYellow
    $doConfig = Prompt-YesNo "  是否重新填写配置？" $false
}

if ($doConfig) {
    Write-Host ""
    Write-Host "  选择推送渠道：" -ForegroundColor White
    Write-Host "    1. 企业微信（推荐，配置简单）"
    Write-Host "    2. 飞书"
    do {
        $pc = (Read-Host "  请输入 [1/2]").Trim()
    } until ($pc -eq "1" -or $pc -eq "2")

    $config = [ordered]@{}

    if ($pc -eq "1") {
        $providerStr                  = "wecom"
        $config["PUSH_PROVIDER"]      = "wecom"
        Write-Host ""
        $webhook = Prompt-Required "企业微信 Webhook URL（不能为空）"
        $config["WECOM_WEBHOOK_URL"]  = $webhook
        $config["APP_ID"]             = ""
        $config["APP_SECRET"]         = ""
        $config["RECEIVE_ID_TYPE"]    = "chat_id"
        $config["RECEIVE_ID"]         = ""
    } else {
        $providerStr               = "feishu"
        $config["PUSH_PROVIDER"]   = "feishu"
        Write-Host ""
        $appId     = Prompt-Required "飞书 App ID"
        $appSecret = Prompt-Required "飞书 App Secret"
        Write-Host "  接收者类型：1. 群 (chat_id)   2. 个人 (open_id)"
        $idChoice = (Read-Host "  请输入 [1/2]（默认 1）").Trim()
        $idType   = if ($idChoice -eq "2") { "open_id" } else { "chat_id" }
        $receiveId = Prompt-Required "接收者 ID"
        $config["APP_ID"]           = $appId
        $config["APP_SECRET"]       = $appSecret
        $config["RECEIVE_ID_TYPE"]  = $idType
        $config["RECEIVE_ID"]       = $receiveId
        $config["WECOM_WEBHOOK_URL"] = ""
    }

    Write-Host ""
    Write-Host "  可选设置（直接回车使用默认值）：" -ForegroundColor DarkGray
    $intervalMin = Prompt-WithDefault "截图发送间隔（分钟）" "30"
    $config["INTERVAL_SECONDS"] = [int]$intervalMin * 60

    $prefix = Prompt-WithDefault "消息前缀" "实验截图"
    $config["TEXT_PREFIX"] = $prefix

    $enableLaser = Prompt-YesNo "是否启用激光亮点检测（需要相机输入）？" $false

    # 固定默认值
    $config["ROI"]                            = $null
    $config["CAMERA_ROI"]                     = $null
    $config["SPOT_SEARCH_ROI"]                = $null
    $config["DETECT_INTERVAL_SECONDS"]        = 5
    $config["BASELINE_INIT_FRAMES"]           = 15
    $config["INTENSITY_DROP_RATIO_THRESHOLD"] = 0.05
    $config["AREA_DROP_RATIO_THRESHOLD"]      = 0.05
    $config["ALERT_CONSECUTIVE_FRAMES"]       = 3
    $config["ALERT_COOLDOWN_SECONDS"]         = 300
    $config["SEND_TEXT_BEFORE_IMAGE"]         = $true
    $config["SAVE_DIR"]                       = "runtime/screenshots"
    $config["LOG_LEVEL"]                      = "INFO"

    $config | ConvertTo-Json -Depth 5 | Set-Content -Path $configPath -Encoding UTF8
    Write-OK "配置已保存到 config.local.json"

} else {
    # 读取现有配置的 provider 和激光开关，用于后续步骤
    try {
        $existing    = Get-Content $configPath -Raw | ConvertFrom-Json
        $providerStr = if ($existing.PUSH_PROVIDER) { $existing.PUSH_PROVIDER } else { "wecom" }
        $enableLaser = ($null -ne $existing.CAMERA_ROI -or $null -ne $existing.SPOT_SEARCH_ROI)
    } catch {
        Write-Host "  读取现有配置失败，将按 wecom 安装依赖" -ForegroundColor DarkYellow
        $providerStr = "wecom"
    }
    Write-OK "沿用现有 config.local.json"
}

# ── [3/5] 安装依赖 ────────────────────────────────────────────────────────────

Write-Step 3 5 "安装 Python 依赖（渠道：$providerStr）..."

$installScript = Join-Path $PSScriptRoot "install.ps1"
& powershell -ExecutionPolicy Bypass -File $installScript -Provider $providerStr

if ($LASTEXITCODE -ne 0) {
    Write-Fail "依赖安装失败，请查看上方错误信息"
    Read-Host "`n  按回车退出"
    exit 1
}
Write-OK "依赖安装完成"

# ── [4/5] 环境检查 ────────────────────────────────────────────────────────────

Write-Step 4 5 "环境检查..."

Push-Location $projectRoot
& $venvPython -m screenshot_sender --check --config $configPath
$checkCode = $LASTEXITCODE
Pop-Location

if ($checkCode -ne 0) {
    Write-Fail "环境检查未通过，请根据上方提示修复后重新运行安装向导"
    Read-Host "`n  按回车退出"
    exit 1
}
Write-OK "环境检查通过"

# ── [5/5] 可选操作 ────────────────────────────────────────────────────────────

Write-Step 5 5 "可选操作"
Write-Host ""

if ($enableLaser) {
    $doRoi = Prompt-YesNo "是否现在框选摄像头区域（ROI）？（激光检测必须）" $true
    if ($doRoi) {
        Push-Location $projectRoot
        & $venvPython -m screenshot_sender --select-roi --config $configPath
        Pop-Location
        Write-OK "ROI 已保存"
    }
}

$doTest = Prompt-YesNo "是否发送一次测试截图验收？" $true
if ($doTest) {
    Push-Location $projectRoot
    & $venvPython -m screenshot_sender --once --config $configPath
    Pop-Location
}

# ── 完成 ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  安装完成！" -ForegroundColor Green
Write-Host "  日常使用请双击根目录的  菜单.bat" -ForegroundColor Green
Write-Host "══════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Read-Host "  按回车退出"
