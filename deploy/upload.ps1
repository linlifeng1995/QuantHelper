# upload.ps1 — 将本地项目打包并上传到腾讯云服务器
# 用法: .\deploy\upload.ps1 -ServerIP 1.2.3.4 [-SshUser root] [-AppDir /app/my_quant]
# 前置条件: 本机已安装 OpenSSH (Win10/11 内置) 且已配置 SSH 公钥免密登录
#   免密登录设置: ssh-copy-id root@<服务器IP>  (或手动将 ~/.ssh/id_rsa.pub 追加到服务器 ~/.ssh/authorized_keys)

param(
    [Parameter(Mandatory)]
    [string]$ServerIP,
    [string]$SshUser = "root",
    [string]$AppDir  = "/app/my_quant"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root       = Split-Path -Parent $PSScriptRoot
$remoteStr  = "${SshUser}@${ServerIP}"
$remotePath = "${remoteStr}:${AppDir}"

Write-Host "上传目标: $remotePath"
Write-Host ""

# ── 1. 排除列表 ─────────────────────────────
# rsync 风格的排除，通过 .rsync-exclude 临时文件传给 scp 替代方案
# 这里用 robocopy 先打一个干净的临时目录，再 tar+scp 上传

$tmpDir = Join-Path $env:TEMP "myquant_deploy_$(Get-Date -Format yyyyMMddHHmmss)"
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
Write-Host "[1/4] 创建临时目录: $tmpDir"

# 排除的文件夹/文件（不上传到服务器）
$excludeDirs  = @("node_modules", ".venv", ".venv312", ".git", "__pycache__", ".next", "*.egg-info")
$excludeFiles = @("*.pyc", "*.pyo")

# 复制代码（不含数据文件）
$robocopyArgs = @($root, $tmpDir, "/E", "/NP", "/NFL", "/NDL")
foreach ($d in $excludeDirs) { $robocopyArgs += "/XD"; $robocopyArgs += $d }
foreach ($f in $excludeFiles) { $robocopyArgs += "/XF"; $robocopyArgs += $f }
Write-Host "[2/4] 复制代码文件..."
$rc = (Start-Process robocopy -ArgumentList $robocopyArgs -Wait -PassThru).ExitCode
if ($rc -ge 8) { throw "robocopy 失败，退出码 $rc" }

# ── 2. 打 tar 包 ─────────────────────────────
Write-Host "[3/4] 打包..."
$tarFile = Join-Path $env:TEMP "myquant_deploy.tar.gz"
if (Test-Path $tarFile) { Remove-Item $tarFile -Force }
# 需要 tar（Win10+ 内置）
Push-Location $tmpDir
tar -czf $tarFile .
Pop-Location
Remove-Item -Recurse -Force $tmpDir
$sizeMB = [math]::Round((Get-Item $tarFile).Length / 1MB, 1)
Write-Host "  包大小: ${sizeMB} MB"

# ── 3. 上传代码包 ───────────────────────────
Write-Host "[4/4] 上传代码包到服务器..."
ssh "${remoteStr}" "mkdir -p ${AppDir}"
scp $tarFile "${remoteStr}:/tmp/myquant_deploy.tar.gz"
ssh "${remoteStr}" "cd ${AppDir} && tar -xzf /tmp/myquant_deploy.tar.gz && rm /tmp/myquant_deploy.tar.gz"
Remove-Item $tarFile -Force
Write-Host "  代码上传完成"

# ── 4. 上传数据文件（单独上传，较大）──────────
Write-Host ""
Write-Host "正在上传数据文件（price_cache 可能较大，请稍候）..."
$cacheDir = Join-Path $root "outputs\cache"
$dataFiles = @(
    "price_cache.parquet",
    "myquant.db",
    "tushare_token.txt"
)
ssh "${remoteStr}" "mkdir -p ${AppDir}/outputs/cache"
foreach ($f in $dataFiles) {
    $localPath = Join-Path $cacheDir $f
    if (Test-Path $localPath) {
        $sz = [math]::Round((Get-Item $localPath).Length / 1MB, 1)
        Write-Host "  上传 $f ($sz MB)..."
        scp $localPath "${remoteStr}:${AppDir}/outputs/cache/$f"
    } else {
        Write-Host "  跳过 $f (文件不存在)"
    }
}

# ── 5. 修正服务器权限 ───────────────────────
Write-Host ""
Write-Host "修正服务器目录权限..."
ssh "${remoteStr}" "chown -R myquant:myquant ${AppDir} 2>/dev/null || true"

# ── 完成提示 ─────────────────────────────────
Write-Host ""
Write-Host "========================================"
Write-Host " 上传完成！"
Write-Host "========================================"
Write-Host ""
Write-Host "下一步，在服务器上执行:"
Write-Host "  ssh $remoteStr"
Write-Host "  bash ${AppDir}/deploy/server-setup-2.sh"
Write-Host ""
