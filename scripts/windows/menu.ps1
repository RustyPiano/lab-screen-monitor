
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venvPython  = Join-Path $projectRoot ".venv\Scripts\python.exe"
$configPath  = Join-Path $projectRoot "config.local.json"
$logPath     = Join-Path $projectRoot "runtime\sender.log"

function Show-Menu {
    Clear-Host
    Write-Host "╔══════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║      自动截屏发送 - 操作菜单         ║" -ForegroundColor Cyan
    Write-Host "╠══════════════════════════════════════╣" -ForegroundColor Cyan
    Write-Host "║  1. 启动（正式运行）                 ║"
    Write-Host "║  2. 环境检查                         ║"
    Write-Host "║  3. 重新框选 ROI 区域                ║"
    Write-Host "║  4. 发送一次测试截图                 ║"
    Write-Host "║  5. 查看日志                         ║"
    Write-Host "║  6. 重新安装 / 修改配置              ║"
    Write-Host "║  0. 退出                             ║"
    Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

# 检查环境是否就绪，未就绪时打印提示并返回 $false
function Test-Ready {
    if (-not (Test-Path $venvPython)) {
        Write-Host "`n  尚未完成安装，请先运行根目录的 安装.bat" -ForegroundColor Red
        Read-Host "  按回车返回菜单"
        return $false
    }
    if (-not (Test-Path $configPath)) {
        Write-Host "`n  未找到配置文件，请先运行根目录的 安装.bat" -ForegroundColor Red
        Read-Host "  按回车返回菜单"
        return $false
    }
    return $true
}

while ($true) {
    Show-Menu
    $choice = (Read-Host "请输入选项").Trim()

    switch ($choice) {
        "1" {
            if (-not (Test-Ready)) { break }
            Write-Host "`n  正在启动，按 Ctrl+C 停止运行..." -ForegroundColor DarkGray
            Push-Location $projectRoot
            & $venvPython -m screenshot_sender --config $configPath
            Pop-Location
            Read-Host "`n  程序已退出，按回车返回菜单"
        }
        "2" {
            if (-not (Test-Ready)) { break }
            Push-Location $projectRoot
            & $venvPython -m screenshot_sender --check --config $configPath
            Pop-Location
            Read-Host "`n  按回车返回菜单"
        }
        "3" {
            if (-not (Test-Ready)) { break }
            Write-Host "`n  将弹出窗口，请按提示用鼠标框选区域，完成后按回车确认。" -ForegroundColor DarkGray
            Push-Location $projectRoot
            & $venvPython -m screenshot_sender --select-roi --config $configPath
            Pop-Location
            Read-Host "`n  按回车返回菜单"
        }
        "4" {
            if (-not (Test-Ready)) { break }
            Push-Location $projectRoot
            & $venvPython -m screenshot_sender --once --config $configPath
            Pop-Location
            Read-Host "`n  按回车返回菜单"
        }
        "5" {
            if (Test-Path $logPath) {
                notepad $logPath
            } else {
                Write-Host "`n  日志文件尚不存在（程序运行后自动生成）：" -ForegroundColor Yellow
                Write-Host "  $logPath" -ForegroundColor DarkGray
                Read-Host "  按回车返回菜单"
            }
        }
        "6" {
            $setupScript = Join-Path $PSScriptRoot "setup.ps1"
            & powershell -ExecutionPolicy Bypass -File $setupScript
        }
        "0" {
            exit 0
        }
        default {
            Write-Host "`n  无效选项，请输入 0-6" -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
