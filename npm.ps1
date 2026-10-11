# npm inside a container, in web/: Node.js is not installed on the PC.
# Usage: .\npm.ps1 install      .\npm.ps1 test      .\npm.ps1 run dev
# "run dev" serves the page on http://127.0.0.1:5174 and takes everything under /api from the running app.
$tty = if ([Console]::IsInputRedirected) { '-i' } else { '-it' }
$dev = @()
if ($args -contains 'dev') {
    # a fixed name, so that a dev server left behind is replaced instead of blocking the port
    docker rm -f regista-web-dev 2>$null | Out-Null
    $dev = '--name', 'regista-web-dev', '-p', '127.0.0.1:5174:5173',
           '-e', 'API_URL=http://host.docker.internal:8090', '-e', 'WATCH_BY_POLLING=1'
}
docker run --rm $tty @dev `
    -v "$PSScriptRoot\web:/app" `
    -v regista-node-modules:/app/node_modules `
    -w /app node:24-alpine npm @args
