# Doctrine Vault

A small Flask site for your corp's doctrines. Paste in EFT fits, and each fit shows the ship render plus every module, charge and drone with its in-game icon. Pilots hit **Copy for EVE** and import straight into the client. No EVE login or API keys needed.

## Getting fits in

1. Click **Editor login** and enter the admin password.
2. **+ New doctrine**, give it a name and description.
3. Paste one or more EFT fits into the box (EVE client: Fitting window, select the fit, Copy to Clipboard. Pyfa: Export > EFT). Separate fits just by starting each one with its `[Ship, Fit name]` line.
4. Put a role in brackets at the end of a fit name, like `[Scimitar, Scimitar Logi (Logi)]`, and it becomes a role tag.

Use **Edit / add fits** on a doctrine to paste more fits in later. Each fit has its own Edit, reorder and remove buttons.

## Getting fits into EVE

* **One fit:** Copy for EVE, then in game: Fitting window > Import & Export > Import from Clipboard.
* **Whole doctrine:** Download all (XML), then Fitting window > Import & Export > Import from File.

## How the icons work

Item names are matched to EVE type IDs through ESI's public `/universe/ids/` lookup (no login), then cached in the database so it only happens once per item. Images come from `images.evetech.net`. If a name doesn't match (usually a typo) the tile shows a `?` and the fit lists what it couldn't find.

## Deploying on Render

1. Push this folder to a GitHub repo.
2. In Render: **New > Blueprint**, pick the repo. `render.yaml` creates the web service and a free Postgres database.
3. When prompted, set `ADMIN_PASSWORD`. `SECRET_KEY` is generated for you.

Note: Render's free Postgres expires after 30 days unless upgraded. If you'd rather use SQLite, add a persistent disk and set `DATABASE_URL=sqlite:////var/data/doctrines.db`.

## Running locally

```
pip install -r requirements.txt
ADMIN_PASSWORD=changeme python app.py
```

Then open http://127.0.0.1:5000. With no `ADMIN_PASSWORD` set, anyone can edit (a banner warns you).

## Files

* `app.py` routes and page logic
* `eft.py` EFT parsing, slot layout, XML export
* `esi.py` name to type ID lookup with caching
* `models.py` database tables (doctrines, fits, type cache)
* `templates/`, `static/` the pages, styling and copy button
