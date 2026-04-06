# Bridge Server 一键安装脚本 (Windows PowerShell)
# 使用方法：Invoke-WebRequest -Uri https://example.com/install.ps1 -OutFile install.ps1; .\install.ps1

$ErrorActionPreference = "Stop"

# 颜色函数
function Write-Info { Write-Host "[INFO] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[SUCCESS] $args" -ForegroundColor Green }
function Write-Warning { Write-Host "[WARNING] $args" -ForegroundColor Yellow }
function Write-Error-Custom { Write-Host "[ERROR] $args" -ForegroundColor Red }

# 检测管理员权限
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# 检查 Python
function Test-Python {
    Write-Info "检查 Python..."
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $version = python --version
        Write-Success "Python 已安装：$version"
        return $true
    } else {
        Write-Error-Custom "Python 未安装，请先安装 Python 3.8+"
        Write-Info "下载地址：https://www.python.org/downloads/"
        return $false
    }
}

# 创建目录
function New-BridgeDirectory {
    Write-Info "创建安装目录..."
    $installDir = "$env:USERPROFILE\.local\opt\bridge-server"
    $configDir = "$env:USERPROFILE\.bridge-server"
    
    if (!(Test-Path $installDir)) {
        New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    }
    if (!(Test-Path $configDir)) {
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    }
    
    Write-Success "目录创建完成"
    return $installDir
}

# 下载代码
function Get-BridgeCode {
    param($installDir)
    
    Write-Info "下载 Bridge Server..."
    
    # 这里使用本地文件，实际发布时应该从 GitHub 下载
    # Invoke-WebRequest -Uri "https://github.com/your-org/bridge-server/archive/refs/tags/v1.0.0.tar.gz" -OutFile "$env:TEMP\bridge-server.tar.gz"
    # Expand-Archive -Path "$env:TEMP\bridge-server.tar.gz" -DestinationPath $installDir
    
    # 临时使用本地文件（仅用于测试）
    Copy-Item -Path "/home/pi/.openclaw/workspace/bridge-server-product/*" -Destination $installDir -Recurse -Force
    
    Write-Success "代码下载完成：$installDir"
}

# 创建虚拟环境
function New-BridgeVenv {
    param($installDir)
    
    Write-Info "创建 Python 虚拟环境..."
    Set-Location $installDir
    python -m venv venv
    Write-Success "虚拟环境创建完成"
}

# 安装依赖
function Install-BridgeDependencies {
    param($installDir)
    
    Write-Info "安装 Python 依赖..."
    & "$installDir\venv\Scripts\pip.exe" install --upgrade pip
    & "$installDir\venv\Scripts\pip.exe" install -r "$installDir\requirements.txt"
    Write-Success "依赖安装完成"
}

# 创建配置文件
function New-BridgeConfig {
    Write-Info "创建配置文件..."
    $configDir = "$env:USERPROFILE\.bridge-server"
    $installDir = "$env:USERPROFILE\.local\opt\bridge-server"
    
    if (!(Test-Path "$configDir\config.yaml")) {
        Copy-Item "$installDir\config.yaml.example" "$configDir\config.yaml"
        Write-Success "配置文件已创建：$configDir\config.yaml"
    } else {
        Write-Warning "配置文件已存在，跳过"
    }
    
    if (!(Test-Path "$configDir\.env")) {
        Copy-Item "$installDir\.env.example" "$configDir\.env"
        Write-Success ".env 文件已创建：$configDir\.env"
        Write-Warning "请编辑 $configDir\.env，填入你的 API Key"
    } else {
        Write-Warning ".env 文件已存在，跳过"
    }
}

# 安装 CLI 工具
function Install-BridgeCLI {
    param($installDir)
    
    Write-Info "安装 CLI 工具..."
    
    # 创建启动脚本
    $cliScript = @"
@echo off
setlocal
set "VENV_PYTHON=$installDir\venv\Scripts\python.exe"
"%VENV_PYTHON%" "$installDir\cli\bridge-server.py" %*
"@
    
    $cliScript | Out-File -FilePath "$installDir\bridge-server.bat" -Encoding ASCII
    
    # 添加到 PATH
    $currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentPath -notlike "*$installDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$currentPath;$installDir", "User")
        Write-Info "已将 CLI 添加到 PATH"
    }
    
    Write-Success "CLI 工具安装完成"
}

# 显示完成信息
function Show-CompletionMessage {
    Write-Host ""
    Write-Success "🎉 Bridge Server 安装完成！"
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Write-Host ""
    Write-Host "下一步："
    Write-Host ""
    Write-Host "  1. 配置 API Key"
    Write-Host "     notepad $env:USERPROFILE\.bridge-server\.env"
    Write-Host ""
    Write-Host "  2. 运行配置向导（可选）"
    Write-Host "     bridge-server setup"
    Write-Host ""
    Write-Host "  3. 启动服务"
    Write-Host "     bridge-server start"
    Write-Host ""
    Write-Host "  4. 测试连接"
    Write-Host "     bridge-server test"
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Write-Host ""
    Write-Info "文档：https://docs.bridge-server.dev"
    Write-Info "支持：support@example.com"
    Write-Host ""
}

# 主函数
function Main {
    Write-Host ""
    Write-Host "🌉 Bridge Server 安装程序 (Windows)"
    Write-Host "版本：v1.0.0 Community Edition"
    Write-Host ""
    
    if (!(Test-Python)) {
        exit 1
    }
    
    $installDir = New-BridgeDirectory
    Get-BridgeCode -installDir $installDir
    New-BridgeVenv -installDir $installDir
    Install-BridgeDependencies -installDir $installDir
    New-BridgeConfig
    Install-BridgeCLI -installDir $installDir
    Show-CompletionMessage
}

# 运行主函数
Main
