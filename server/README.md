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
| `BIREAD_BASE_URL` | Where this server is reachable, e.g. `http://<your-host>`. Used to build the OAuth callback and to refuse off-site redirects. |
| `BIREAD_GITHUB_CLIENT_ID` / `_SECRET` | From a GitHub OAuth App whose callback is `<base>/api/auth/github/callback`. |
| `BIREAD_SESSION_DAYS` | How long a sign-in lasts. Default 90. |

Sign-in is GitHub only for now, because Google will not accept a bare IP address
as a redirect target — it wants a domain and https. `auth.py` keeps the provider
in one place so the second one is a small addition, not a rewrite.

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
