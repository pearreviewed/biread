#!/usr/bin/env bash
# Turn on GitHub sign-in, without the secret ever touching shell history, a file
# in the repo, or anyone's transcript. Run it on the server:
#
#   ssh -t -i ~/.ssh/id_ed25519_ovh <your-user>@<your-host> \
#       /srv/apps/biread/server/deploy/enable-signin.sh
#
# Register the OAuth App first — the callback must be exactly:
#   https://vps-bab9636f.vps.ovh.net/api/auth/github/callback
set -euo pipefail

ENV=/etc/biread/sync.env
BASE=$(sudo grep -oP '^BIREAD_BASE_URL=\K.*' "$ENV")

echo "Setting up GitHub sign-in for $BASE"
echo

read -rp "Client ID: " CLIENT_ID
read -rsp "Client secret (not shown): " CLIENT_SECRET
echo
echo

[ -n "$CLIENT_ID" ] || { echo "No client ID given — nothing changed." >&2; exit 1; }
[ -n "$CLIENT_SECRET" ] || { echo "No secret given — nothing changed." >&2; exit 1; }

sudo cp "$ENV" "$ENV.bak"
sudo sed -i "s|^BIREAD_GITHUB_CLIENT_ID=.*|BIREAD_GITHUB_CLIENT_ID=$CLIENT_ID|" "$ENV"
# The secret goes in through a file descriptor rather than a command line, so it
# never appears in the process table for anyone else on the box to read.
sudo sh -c "sed -i \"s|^BIREAD_GITHUB_CLIENT_SECRET=.*|BIREAD_GITHUB_CLIENT_SECRET=\$(cat)|\" '$ENV'" <<<"$CLIENT_SECRET"

sudo systemctl restart biread-sync
sleep 2

if curl -fsS "$BASE/api/health" | grep -q '"signIn":"github"'; then
    echo "Sign-in is on. Open a book and look at the foot of the Bookmarks panel:"
    echo "  $BASE/books/candide.html"
else
    echo "The service came back but still reports no sign-in. Check:" >&2
    echo "  sudo journalctl -u biread-sync -n 40" >&2
    echo "The previous configuration is at $ENV.bak" >&2
    exit 1
fi
