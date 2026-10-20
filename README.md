# Rift Watch Fleet Doctrines

A Flask site for the Rift Watch corp's fleet doctrines. Editors paste in EVE fits (EFT format) and every pilot can browse them with in-game icons, see the skills each fit needs, and copy fits straight into EVE.

Live at https://doctrine-li9g.onrender.com/

## What it does

**For pilots**
* **Search** on the front page: type a ship, ship class (Frigate, Interceptor...), fit or doctrine name, role, module or author and matching fits appear as you type. Several words narrow it down, Enter opens the top result, Escape clears it, and `/` jumps to the box.
* **Only show fits I can fly:** a toggle under the search box. Logged-in pilots tick it to list just the fits their skills are ready for, and it works with search too (e.g. tick it and type `tackle`). Search results also show **Can fly**, **Missing skills** or **Needs Omega** on each fit. The toggle is remembered in that browser.
* Doctrine pages show each fit with the ship render and every module, charge and drone as its in-game icon, grouped into High, Mid, Low, Rigs, Subsystems, Drones and Cargo.
* **Copy for EVE** copies the fit and opens a pop-up explaining how to import it (Fitting window, Import & Export button bottom left, Import from Clipboard). Pilots can tick "Don't show this again".
* **Log in with EVE** (top bar) uses CCP's own login. Pilots then get **Push to EVE** on every fit and **Push all to EVE** on each doctrine, which put fits straight into their in-game Personal Fittings. The site only asks for permission to save fittings and read skills. The login sits in the pilot's browser session and nothing is stored in the database. Click the x by their name to log out. Copy for EVE still works without logging in.
* **Can I fly this?** Once logged in, each fit shows **You can fly this**, **Missing N skills** or **Needs Omega** (skills trained but held back by an alpha clone). The Required skills tab shows the pilot's own level against each skill, including the fitting skills, and **Copy what I'm missing** gives a skill plan with only the levels they still need. Doctrine cards on the front page show **You can fly X of Y**. Skills are read live from EVE (refreshed every 2 minutes) and never saved. Pilots who logged in before this was added are asked to log in once more to allow it.
* Loaded ammo isn't part of a saved fitting in EVE, so only ammo listed in the fit's cargo section goes across. Implants are left out too.
* **Download all (XML)** imports a whole doctrine at once via Import & Export > Import from File.
* Each fit has three tabs: **Fit**, **Required skills** and **Module list**.
* **Required skills** lists every skill needed including prerequisites, with five level pips per skill. Levels an alpha clone can't train are gold, and each fit gets an **Alpha OK** or **Omega** badge. **Copy as skill plan** copies the plan for EVE's skill planner.
* **Fitting skills:** the minimum skills cover using each module, not fitting them all at once. When editing a fit, editors click levels for the seven skills that change CPU and power grid (CPU Management, Power Grid Management, Weapon Upgrades, Advanced Weapon Upgrades, Shield Upgrades, Energy Grid Upgrades, Electronics Upgrades). These show in their own **Fitting skills** section under the minimum skills, and are included in the skill plan and the Alpha/Omega badge. Boxes above the alpha limit have a gold outline.
* **Skill descriptions:** hover over any skill name (tap on phones) to see EVE's own description, plus its rank and training attributes.
* **Training time:** the Required skills tab shows roughly how long the whole fit takes to train from a brand new character (Omega, average attributes, no implants). Logged-in pilots also see how long their missing skills will take with their own attributes, at half speed if they're on an alpha clone. Skill ranks and attributes come from ESI and are cached in the database.
* Each fit shows **Last edited by [character] · [time]** with their portrait, updated whenever a fit is added, edited or copied. Fits from before this was added show nothing until someone next edits them.
* **Fit cost:** each fit shows what to bring to buy it at Jita: the Jita total rounded up to the next whole million, plus 1 million spare (e.g. 45.3m shows as 47m). The exact Jita figure is on hover and in the Module list. Prices are (Jita 4-4 sell prices from Fuzzwork, or EVE's average price if that's down), with hull and modules split out on hover. The Module list tab shows the price of every item. Ammo loaded in guns isn't counted, ammo in the cargo is. Prices are cached for an hour.
* Fits can have several role tags, picked with buttons or typed separated by commas (e.g. `EWAR, DPS`).

**For editors**
* Editing uses EVE login, not a password. There are two roles:
  * **Owners** can edit, and can open the **Access** page (top bar) to add or remove owners and editors by exact character name. The first owner is set in Render with `OWNER_CHARACTERS`.
  * **Editors** can add, edit and delete doctrines and fits.
  * Anyone else who logs in can browse, push fits and check their skills, but sees no edit buttons. The top bar shows each person's role next to their name.
* **Deleted (bin icon):** anything deleted, a whole doctrine or a single fit, goes to the bin with who deleted it and when. Right after deleting, the message has an **Undo** button. On the Deleted page editors and owners can **Restore** it exactly as it was, at the same link. Only owners can **Delete for good**. A fit whose doctrine was also deleted needs the doctrine restored first.
* **Who can see a doctrine:** a three-way switch on each doctrine page and on the doctrine form: **Private** (only owners and editors, for drafts and testing; to anyone else it looks like it doesn't exist), **[Alliance]** (needs an EVE login with a character in the alliance or corps listed in `ALLIANCE_MEMBERS`, checked with EVE every 30 minutes) or **Public** (anyone with the link). Outsiders can't see the name, fits or search entries of alliance-only doctrines; the front page just says how many are hidden. New doctrines start as **Private**.
* **Show private doctrines:** private doctrines are hidden from the front page and search for everyone, editors included, until an editor ticks **Show private doctrines** under the search box. The choice is remembered in that browser.
* **Copy to...:** each fit has a Copy to button for editors. Pick any doctrine (or the same one, or a new one) and the fit is copied with its notes, roles and fitting skills, then you go straight to the copy's edit page. A new doctrine made this way starts as private.
* Then use **+ New doctrine** or **Edit / add fits**. The author box starts filled with your character name.
* The doctrine form has **one box per fit**, each with its own role tag buttons (DPS, Logi, Tackle and so on) and a box to type your own. **+ Add another fit** adds a box, and the x removes one. Each box takes an EFT fit starting with its `[Ship, Fit name]` line. Stray tag lines like `(Tackle)` in the pasted text are ignored instead of showing as unknown modules.
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
| `models.py` | Database tables: Doctrine, Fit, Access (owners and editors), Deleted (the bin), TypeInfo, TypeReqs, SkillInfo, KV |
| `eft.py` | EFT parsing, slot layout, XML export |
| `esi.py` | Name to type ID lookup, character lookup |
| `skills.py` | Required skills, prerequisites, alpha caps, skill plan text |
| `sso.py` | EVE login (SSO) and saving fits to a character's fittings through ESI |
| `prices.py` | Jita prices (Fuzzwork, ESI as backup) and fit costs |
| `markup.py` | Discord-style formatting to safe HTML |
| `templates/` | Pages: base, index, doctrine, doctrine_form, fit_form, access, deleted |
| `static/` | `style.css`, `app.js`, logo (gif and png), share banner `og-banner.png` |

## Hosting (Render + Neon)

* **Render web service**, Python. Build `pip install -r requirements.txt`, start `gunicorn app:app --bind 0.0.0.0:$PORT`. `render.yaml` has the same settings for a Blueprint deploy.
* **Environment variables:**
  * `OWNER_CHARACTERS`: your character name, plus any others separated by commas. These are owners who can't be removed from the site itself. If nobody is set as owner, nobody can edit and a banner says so.
  * `SECRET_KEY`: any long random string.
  * `EVE_CLIENT_ID` and `EVE_CLIENT_SECRET`: from the app at developers.eveonline.com, with the scopes `esi-fittings.write_fittings.v1` and `esi-skills.read_skills.v1` and the callback URL `https://<site address>/sso/callback`. Leave them out and the EVE login buttons simply don't show.
  * `ALLIANCE_MEMBERS`: the alliance name (or corp names, or EVE IDs) that counts as "us" for alliance-only doctrines, comma separated. Exact in-game names.
  * `ALLIANCE_LABEL`: optional short name shown on the site, e.g. `Watchpoint`. Defaults to the first name in `ALLIANCE_MEMBERS`.
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
OWNER_CHARACTERS="Your Character" EVE_CLIENT_ID=... EVE_CLIENT_SECRET=... python app.py
```

Then open http://127.0.0.1:5000.
