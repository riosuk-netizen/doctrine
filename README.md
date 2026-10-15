# Rift Watch Fleet Doctrines

A Flask site for the Rift Watch corp's fleet doctrines. Editors paste in EVE fits (EFT format) and every pilot can browse them with in-game icons, see the skills each fit needs, and copy fits straight into EVE.

Live at https://doctrine-li9g.onrender.com/

## What it does

**For pilots**
* **Search** on the front page: type a ship, ship class (Frigate, Interceptor...), fit or doctrine name, role, module or author and matching fits appear as you type. Several words narrow it down, Enter opens the top result, Escape clears it, and `/` jumps to the box.
* Doctrine pages show each fit with the ship render and every module, charge and drone as its in-game icon, grouped into High, Mid, Low, Rigs, Subsystems, Drones and Cargo.
* **Copy for EVE** copies the fit and opens a pop-up explaining how to import it (Fitting window, Import & Export button bottom left, Import from Clipboard). Pilots can tick "Don't show this again".
* **Download all (XML)** imports a whole doctrine at once via Import & Export > Import from File.
* Each fit has three tabs: **Fit**, **Required skills** and **Module list**.
* **Required skills** lists every skill needed including prerequisites, with five level pips per skill. Levels an alpha clone can't train are gold, and each fit gets an **Alpha OK** or **Omega** badge. **Copy as skill plan** copies the plan for EVE's skill planner.
* **Fitting skills:** the minimum skills cover using each module, not fitting them all at once. When editing a fit, editors click levels for the seven skills that change CPU and power grid (CPU Management, Power Grid Management, Weapon Upgrades, Advanced Weapon Upgrades, Shield Upgrades, Energy Grid Upgrades, Electronics Upgrades). These show in their own **Fitting skills** section under the minimum skills, and are included in the skill plan and the Alpha/Omega badge. Boxes above the alpha limit have a gold outline.
* Fits can have several role tags, separated by commas (e.g. `EWAR, DPS`).

**For editors**
* Log in with the editor password, then **+ New doctrine** or **Edit / add fits**.
* Paste one or more EFT fits; each starts with its `[Ship, Fit name]` line. A role in brackets at the end of the fit name, like `(Logi)`, becomes a role tag.
* Doctrines have an **Author** (exact in-game character name, which shows their portrait linked to zKillboard) and show **Updated x ago**, which changes whenever anything in the doctrine changes.
* Descriptions and fit notes take Discord formatting: `**bold**`, `*italic*`, `__underline__`, `~~strike~~`, `` `code` ``, `- bullets`, `1. numbers`, `#` headings, `-#` small text, `>` quotes and links. Copy a Discord message with **Copy Text** to keep the formatting.

**Look and sharing**
* Branded as Rift Watch with the animated logo (a still version is used for anyone with reduced motion turned on).
* Sharing a link in Discord gives a preview card with the banner image. Doctrine links show the doctrine name, fit count and ships.

## Where the data comes from

* **Item names to type IDs and icons:** ESI's public `/universe/ids/` and `/universe/types/` endpoints (no login), cached in the database. Images come from `images.evetech.net`.
* **Skill requirements:** dogma attributes on each type and skill from ESI, cached in the database.
* **Alpha clone skill caps:** CCP's clone grade data published at `https://sde.hoboleaks.space/tq/clonestates.json`, cached for a day with the last good copy kept in the database.
* **Author portraits:** character ID looked up through ESI `/universe/ids/`.

## Files

| File | What it does |
|---|---|
| `app.py` | Routes, editor login, template helpers (`asset()` cache-busting, date and tag filters), startup column migrations |
| `models.py` | Database tables: Doctrine, Fit, TypeInfo, TypeReqs, SkillInfo, KV |
| `eft.py` | EFT parsing, slot layout, XML export |
| `esi.py` | Name to type ID lookup, character lookup |
| `skills.py` | Required skills, prerequisites, alpha caps, skill plan text |
| `markup.py` | Discord-style formatting to safe HTML |
| `templates/` | Pages: base, index, doctrine, doctrine_form, fit_form, login |
| `static/` | `style.css`, `app.js`, logo (gif and png), share banner `og-banner.png` |

## Hosting (Render + Neon)

* **Render web service**, Python. Build `pip install -r requirements.txt`, start `gunicorn app:app --bind 0.0.0.0:$PORT`. `render.yaml` has the same settings for a Blueprint deploy.
* **Environment variables:**
  * `ADMIN_PASSWORD`: the editor password. If it's empty, anyone can edit and a warning banner shows.
  * `SECRET_KEY`: any long random string.
  * `DATABASE_URL`: Postgres connection string from Neon (free, doesn't expire). Without it the site falls back to SQLite, which Render wipes on every redeploy.
* New tables are created automatically on start, and new columns added in later versions (author, author_id) are added to existing tables automatically, so updates never need a manual database step.
* Free Render plans sleep after about 15 minutes idle; the first visit after that takes up to a minute. The $7 a month instance keeps it awake.

## Updating through GitHub

* Python files go at the top level of the repo, HTML in `templates/`, CSS, JS and images in `static/`.
* When uploading folders, drag the folder itself so the structure is kept.
* If a change touches `app.py` and a template together, upload them in one commit, as templates can depend on new helpers in `app.py`.

## Running locally

```
pip install -r requirements.txt
ADMIN_PASSWORD=changeme python app.py
```

Then open http://127.0.0.1:5000.
