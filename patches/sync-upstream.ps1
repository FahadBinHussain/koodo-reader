# sync-upstream.ps1 - bring dev in line with upstream/dev, then reapply the premium patch
#
# Workflow: this repo keeps the premium-unlock changes OUT of dev's committed tree.
# dev = upstream/dev + patch infra only (patches/ + package.json scripts).
# The patch is applied at build time via the prebuild hook (node patches/apply-patch.js).
#
# When upstream advances:
#   1. fetch upstream
#   2. reset local dev to upstream/dev  (discards any locally-committed patch tree)
#   3. re-add the patch infra (patches/ + package.json scripts + .gitattributes)
#   4. verify the patch applies cleanly (git apply --check)
#   5. commit
#
# If the patch no longer applies cleanly (upstream changed a patched file), this
# script stops and tells you to update patches/premium-unlock.patch manually.

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$UpstreamBranch = "upstream/dev"
$InfraFiles = @(
  "patches/apply-patch.js",
  "patches/premium-unlock.patch",
  "package.json",
  ".gitattributes"
)

Write-Host "== fetch upstream =="
git fetch upstream
if ($LASTEXITCODE -ne 0) { throw "fetch failed" }

Write-Host "== reset dev to $UpstreamBranch =="
git checkout dev
git reset --hard "$UpstreamBranch"
if ($LASTEXITCODE -ne 0) { throw "reset failed" }

Write-Host "== verify patch applies cleanly on the fresh upstream tree =="
git apply --check patches/premium-unlock.patch
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "PATCH DOES NOT APPLY CLEANLY. Upstream changed a patched file."
  Write-Host "Fix patches/premium-unlock.patch against upstream/dev, then run:"
  Write-Host "  git apply patches/premium-unlock.patch"
  Write-Host "  npm run premium:apply"
  exit 1
}

Write-Host "== apply patch (should apply cleanly) =="
git apply patches/premium-unlock.patch
if ($LASTEXITCODE -ne 0) { throw "apply failed" }

Write-Host "== verify markers present =="
git diff --stat
Select-String -Path "src/utils/request/user.ts" -Pattern "Pro unlock" -Quiet
if (-not $?) { throw "patch markers missing - did apply really succeed?" }

Write-Host ""
Write-Host "Patch applied cleanly. Review the diff, then commit + push:"
Write-Host "  git add -A"
Write-Host "  git commit -m \"sync with upstream + reapply premium patch\""
Write-Host "  git push origin dev"
Write-Host ""
Write-Host "NOTE: dev is NOT the deploy branch's source of truth for patched code;"
Write-Host "the prebuild hook (node patches/apply-patch.js) applies it during build."
