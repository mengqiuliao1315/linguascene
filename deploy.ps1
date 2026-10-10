<#
.SYNOPSIS
    把当前仓库的源码部署到线上服务器 forddream.icu/linguascene。

.DESCRIPTION
    服务器的 /opt/linguascene 不是 git 仓库，所以不能用 git pull 部署，
    必须由本地把源码推上去。本脚本用 `git archive HEAD` 打包（只含 git 跟踪的源码，
    自动排除 .env / linguascene.db / storage / node_modules / .next 等），
    上传解包后重建前端并重启两个服务。

    后端重启时会执行 apply_schema，新增的数据库表会自动创建。

.EXAMPLE
    .\deploy.ps1                 # 完整部署：上传 + 重建前端 + 重启服务
    .\deploy.ps1 -SkipBuild      # 只改了后端时用，跳过前端构建（更快）
    .\deploy.ps1 -SkipRestart    # 只上传，不动服务
#>
param(
    [string]$Server = "root@47.105.122.135",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\aliyun_sink",
    [string]$RemotePath = "/opt/linguascene",
    [string]$BackendService = "linguascene-backend",
    [string]$FrontendService = "linguascene-frontend",
    [string]$BasePath = "/linguascene",
    [string]$Ref = "HEAD",
    [switch]$SkipBuild,
    [switch]$SkipRestart,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"

$ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
$scp = "C:\Windows\System32\OpenSSH\scp.exe"
foreach ($exe in @($ssh, $scp)) {
    if (-not (Test-Path $exe)) { throw "找不到 $exe" }
}

function Invoke-Remote {
    param([Parameter(Mandatory)][string]$Script, [int]$TimeoutSec = 120)
    $Script | & $ssh -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 $Server "bash -s"
    if ($LASTEXITCODE -ne 0) { throw "远程命令执行失败（exit $LASTEXITCODE）" }
}

# 1. 前置检查：已跟踪文件必须已提交，否则打包的是旧的 HEAD。
#    未跟踪文件（git status 里的 ??）不影响部署，git archive 本来就不会打包。
git diff --quiet HEAD --
if ($LASTEXITCODE -ne 0 -and -not $AllowDirty) {
    Write-Host "以下已跟踪文件尚未提交，git archive 只会打包已提交的内容：" -ForegroundColor Yellow
    git diff --name-only HEAD -- | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    throw "请先提交，或用 -AllowDirty 明确接受「只部署已提交内容」。"
}

$sha = (git rev-parse --short $Ref).Trim()
$subject = (git log -1 --format=%s $Ref).Trim()
Write-Host "部署 $Ref -> $sha  $subject" -ForegroundColor Cyan

# 2. 打包源码（git 跟踪的文件，天然排除 .env / 数据库 / node_modules / .next）
$tar = Join-Path $env:TEMP "linguascene-$sha.tar"
if (Test-Path $tar) { Remove-Item $tar -Force }
git archive --format=tar -o $tar $Ref
Write-Host ("打包完成：{0:N2} MB" -f ((Get-Item $tar).Length / 1MB))

# 3. 上传
$remoteTar = "/tmp/linguascene-deploy.tar"
& $scp -i $KeyPath -o BatchMode=yes $tar "${Server}:${remoteTar}"
if ($LASTEXITCODE -ne 0) { throw "上传失败" }

# 4. 解包（先验证压缩包可用，再解包，避免半途失败留下损坏的目录）
Invoke-Remote @"
set -e
cd $RemotePath || exit 1
tar -tf $remoteTar > /dev/null || { echo TAR_INVALID; exit 1; }
tar -xf $remoteTar -C $RemotePath
rm -f $remoteTar
echo UNPACK_OK
echo -n "reading_service: "; grep -c PARAGRAPH_MARKER backend/app/services/reading_service.py || true
"@

if ($SkipBuild -and $SkipRestart) {
    Remove-Item $tar -Force
    Write-Host "已上传源码，按要求未重建/未重启。" -ForegroundColor Green
    return
}

# 5. 重建前端 + 重启服务 + 自检
#    注意：NEXT_PUBLIC_* 是构建期内联的，build 时必须带上，只给 start 设置无效。
$buildStep = if ($SkipBuild) {
    'echo "== 跳过前端构建 =="; build_rc=0'
} else {
    @"
echo "== 重建前端 =="
export NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
export NEXT_BASE_PATH=$BasePath NEXT_PUBLIC_BASE_PATH=$BasePath NEXT_PUBLIC_API_BASE=$BasePath
cd $RemotePath/frontend
/usr/local/bin/node node_modules/next/dist/bin/next build
build_rc=`$?
cd $RemotePath
echo "BUILD_RC=`$build_rc"
"@
}

$restartStep = if ($SkipRestart) {
    'echo "== 跳过重启 =="'
} else {
    @"
echo "== 重启服务 =="
systemctl restart $BackendService
systemctl restart $FrontendService
sleep 5
echo -n "backend="; systemctl is-active $BackendService
echo -n "frontend="; systemctl is-active $FrontendService
"@
}

Invoke-Remote @"
$buildStep

$restartStep

echo "== 线上自检 =="
curl -s -o /dev/null -w "root=%{http_code}\n" https://forddream.icu$BasePath/ -k
curl -s -o /dev/null -w "reading=%{http_code}\n" https://forddream.icu$BasePath/reading -k
echo "== 近期错误日志 =="
journalctl -u $BackendService -u $FrontendService --since "3 min ago" --no-pager 2>/dev/null | grep -iE "error|traceback|exception" | tail -5
echo DEPLOY_DONE
"@ -TimeoutSec 900

Remove-Item $tar -Force
Write-Host "部署完成：$sha" -ForegroundColor Green
Write-Host "浏览器请按 Ctrl+Shift+R 硬刷新，清掉旧的 JS 缓存。" -ForegroundColor Green