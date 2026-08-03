# biread-sync — the bookmark, never the book

The server side of [`design-reference/accounts-spec.md`](../design-reference/accounts-spec.md):
a reader signs in, and their reading position and their corrections follow them
to another device. What crosses the wire is a few hundred bytes per book.

It is deliberately small, and the smallness is the point. There is no column
anywhere in `schema.sql` that can hold a book. A shelf entry is a **hash of the
reader's file** plus a title, an author, and where they stopped; a correction is
the sentence *the reader themselves wrote*, keyed to a paragraph hash. The
paragraph it replaces is **not** stored — only a hash of it, which is all the
reader needs to know their fix is still aimed at the right text. So a full dump
of this database reconstructs nobody's book, which is the whole copyright
posture in one sentence.

## Running it

```sh
pip install -r requirements.txt
psql -d love -f schema.sql
BIREAD_GITHUB_CLIENT_ID=… BIREAD_GITHUB_CLIENT_SECRET=… \
  uvicorn biread_sync.app:app --port 8080
```

Configuration, all from the environment:

| Variable | Meaning |
|---|---|
| `BIREAD_DATABASE_URL` | libpq connection string. Default `dbname=love`, which is peer auth on the host. |
| `BIREAD_BASE_URL` | Where this server is reachable, e.g. `https://vps-bab9636f.vps.ovh.net`. Used to build the OAuth callback and to refuse off-site redirects. Its scheme also decides whether the session cookie is marked `Secure` — set on a plain-http origin the browser drops it, so sign-in would fail silently rather than insecurely. |
| `BIREAD_GITHUB_CLIENT_ID` / `_SECRET` | From a GitHub OAuth App whose callback is `<base>/api/auth/github/callback`. |
| `BIREAD_SESSION_DAYS` | How long a sign-in lasts. Default 90. |

Sign-in is GitHub only. Google needs a domain you can *prove is yours*, and the
name this box answers to — `vps-bab9636f.vps.ovh.net`, OVH's own — cannot be
verified by us. That is a fact about the address, not about the code: `auth.py`
keeps the provider in one place, so Google is a small addition the day there is
a domain to verify.

## Serving it

`deploy/nginx-biread.conf` is the live site file, certbot's lines and all:
static bundle at the root, this service at `/api/`, TLS on the OVH hostname, and
port 80 redirecting *everything* — including requests to the bare IP, which was
handed out before there was a certificate — to the https name. `deploy/
biread-sync.service` runs uvicorn on loopback as `love`.

## The API

Every route below `/api/shelf` needs the session cookie set by sign-in.

| Route | What it does |
|---|---|
| `GET /api/health` | Liveness, and whether sign-in is configured. |
| `GET /api/me` | Who you are, or `{"signedIn": false}`. |
| `GET /api/auth/github?next=…` | Starts sign-in. `next` must be on this origin. |
| `GET /api/auth/github/callback` | Finishes it and sets the cookie. |
| `POST /api/auth/signout` | Ends this session only. |
| `GET /api/shelf` | Every book on the shelf, with position and corrections. |
| `PUT /api/shelf/{book_id}` | Merges one book and returns the merged result. |
| `DELETE /api/shelf/{book_id}` | Takes a book off the shelf. |

**Merging is the only interesting logic** (`shelf.py`), and it is the rule from
the spec: a position is last-write-wins by the client's own `updatedAt`, while
corrections merge *per paragraph* — different paragraphs union, the same
paragraph is last-write-wins. Two devices reading the same book therefore
converge without any bespoke conflict handling, because every correction is
already keyed to the paragraph it belongs to.

A `PUT` may carry only part of a shelf entry; missing fields are left alone,
which is what lets a reader who only turned a page send only a position.
