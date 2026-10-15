import json
import os
import re
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)

import esi
import markup
import skills
import sso
from eft import (DISPLAY_ORDER, LABELS, EFTError, all_names, build_layout,
                 doctrine_xml, parse_fit, split_fits)
from werkzeug.middleware.proxy_fix import ProxyFix

from sqlalchemy import inspect, text

from models import Access, Deleted, Doctrine, Fit, db, now

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # Render sits behind a proxy: keep links https
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
db_url = os.environ.get("DATABASE_URL", "sqlite:///doctrines.db")
for prefix in ("postgres://", "postgresql://"):
    if db_url.startswith(prefix):
        db_url = "postgresql+psycopg2://" + db_url[len(prefix):]
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
# owners named in Render (comma separated character names); more owners and editors are added on the Access page
OWNER_LIST = [n.strip() for n in os.environ.get("OWNER_CHARACTERS", "").split(",") if n.strip()]
OWNER_NAMES = {n.lower() for n in OWNER_LIST}
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # sent on the EVE login return trip, not on other sites' form posts
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))  # https only once live on Render

db.init_app(app)
with app.app_context():
    db.create_all()
    # add columns that newer versions introduced to tables made by older ones
    _new_cols = (
        ("doctrine", "author", "VARCHAR(120) DEFAULT ''"),
        ("doctrine", "author_id", "INTEGER"),
        ("type_reqs", "meta_group", "INTEGER"),
        ("type_reqs", "reqs_pending", "BOOLEAN DEFAULT FALSE"),
        ("fit", "fitting_skills", "TEXT DEFAULT ''"),
    )
    for _table, _name, _sql in _new_cols:
        if _name not in {c["name"] for c in inspect(db.engine).get_columns(_table)}:
            try:
                with db.engine.begin() as _conn:
                    _conn.execute(text(f"ALTER TABLE {_table} ADD COLUMN {_name} {_sql}"))
            except Exception:  # another worker got there first
                pass
    # one-off: forget tech/faction results saved by earlier versions, which missed some Navy ships
    try:
        with db.engine.begin() as _conn:
            if not _conn.execute(text("SELECT 1 FROM kv WHERE key = 'meta_cache_v3'")).first():
                _conn.execute(text("UPDATE type_reqs SET meta_group = NULL"))
                _conn.execute(text("INSERT INTO kv (key, value, updated_at) VALUES ('meta_cache_v3', '1', CURRENT_TIMESTAMP)"))
    except Exception:  # another worker did it first
        pass

IMG = "https://images.evetech.net/types"
app.jinja_env.filters["md"] = markup.render
app.jinja_env.filters["plain"] = markup.plain


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


def ukdate(dt):
    """11 Oct 2026"""
    dt = _aware(dt)
    return f"{dt.day} {dt:%b %Y}" if dt else ""


def ago(dt):
    """'just now', '5 minutes ago', '3 days ago', or the date once it's over a month."""
    dt = _aware(dt)
    if not dt:
        return ""
    secs = max(0, (datetime.now(timezone.utc) - dt).total_seconds())
    for limit, size, unit in ((60, 1, None), (3600, 60, "minute"), (86400, 3600, "hour"), (86400 * 31, 86400, "day")):
        if secs < limit:
            if unit is None:
                return "just now"
            n = int(secs // size)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return f"on {ukdate(dt)}"


app.jinja_env.filters["ukdate"] = ukdate
app.jinja_env.filters["fromjson"] = json.loads
app.jinja_env.filters["ago"] = ago
META_NAMES = {2: "Tech II", 3: "Storyline", 4: "Faction", 5: "Officer", 6: "Deadspace", 14: "Tech III"}
app.jinja_env.globals["META_NAMES"] = META_NAMES
app.jinja_env.filters["tags"] = lambda s: [t.strip() for t in (s or "").split(",") if t.strip()]


def set_author(d, name):
    name = (name or "").strip()[:120]
    if name != (d.author or ""):
        d.author = name
        d.author_id = esi.character_id(name) if name else None
    elif name and not d.author_id:
        d.author_id = esi.character_id(name)


# ---------- helpers ----------

def role():
    """'owner', 'editor' or None for the pilot logged in with EVE."""
    if "role" not in g:
        pilot = sso.character(session)
        r = None
        if pilot:
            if pilot["name"].strip().lower() in OWNER_NAMES:
                r = "owner"
            else:
                row = db.session.get(Access, pilot["id"])
                r = row.role if row else None
        g.role = r
    return g.role


def is_admin():
    return role() in ("owner", "editor")


def is_owner():
    return role() == "owner"


def _needs(check, what):
    def deco(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if not sso.character(session):
                flash(f"Log in with EVE to {what}.", "warn")
                return redirect(url_for("sso_login", next=request.path))
            if not check():
                flash(f"{session.get('sso_char_name')} doesn't have access to {what}. Ask an owner to add you on the Access page.", "warn")
                return redirect(url_for("index"))
            return view(*a, **kw)
        return wrapped
    return deco


admin_required = _needs(is_admin, "edit doctrines")
owner_required = _needs(is_owner, "manage access")


@app.context_processor
def inject():
    def icon(type_id, size=64):
        return f"{IMG}/{type_id}/icon?size={size}"

    def render_img(type_id, size=256):
        return f"{IMG}/{type_id}/render?size={size}"

    def asset(filename):
        """Static file URL stamped with the file's age, so browsers fetch fresh copies after each deploy."""
        try:
            v = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            v = 0
        return url_for("static", filename=filename, v=v)

    no_owner = not OWNER_NAMES and not Access.query.filter_by(role="owner").first()
    return {"asset": asset, "is_admin": is_admin(), "is_owner": is_owner(), "role": role(), "no_owner": no_owner, "icon": icon,
            "render_img": render_img, "ORDER": DISPLAY_ORDER, "LABELS": LABELS,
            "sso_on": sso.enabled(), "pilot": sso.character(session),
            "pilot_skills_ok": sso.can_read_skills(session)}


def layouts_for(fits):
    parsed = {}
    names = set()
    for f in fits:
        try:
            p = parse_fit(f.eft)
        except EFTError:
            p = {"ship": f.ship, "name": f.name, "sections": []}
        parsed[f.id] = p
        names |= all_names(p)
    info = esi.resolve(names)
    return {fid: build_layout(p, info) for fid, p in parsed.items()}


def add_fits_from_text(doctrine, text):
    """Parse pasted EFT text into Fit rows. Returns (added count, error messages)."""
    blocks = split_fits(text)
    if not blocks:
        return 0, ["No fits found. Each fit should start with a line like [Ship, Fit name]."]
    errors, added = [], []
    start = len(doctrine.fits)
    for i, block in enumerate(blocks):
        try:
            p = parse_fit(block)
        except EFTError as e:
            errors.append(str(e))
            continue
        role = ""
        m = re.search(r"\(([^)]{1,40})\)\s*$", p["name"])  # "Fit name (Logi)" -> role Logi
        if m:
            role = m.group(1)
        fit = Fit(name=p["name"][:120], ship=p["ship"][:120], role=role, eft=block, position=start + i)
        doctrine.fits.append(fit)
        added.append(p)
    # warm the type cache and report anything ESI could not match
    names = set().union(*(all_names(p) for p in added)) if added else set()
    info = esi.resolve(names)
    missing = sorted(n for n in names if n.lower() not in info)
    if missing:
        errors.append("Couldn't match these names (typo, or ESI unreachable): " + ", ".join(missing[:15]))
    return len(added), errors


# ---------- pages ----------

@app.route("/")
def index():
    doctrines = Doctrine.query.order_by(Doctrine.updated_at.desc()).all()
    all_fits = [f for d in doctrines for f in d.fits]
    info = esi.resolve({f.ship for f in all_fits})
    ship_ids = {f.id: (info.get(f.ship.lower()).type_id if info.get(f.ship.lower()) else None) for f in all_fits}
    ship_meta = skills.meta_groups(set(ship_ids.values()))
    classes = skills.ship_classes(set(ship_ids.values()))
    # whether the logged-in pilot can fly each fit: "ready", "short" (missing skills) or "clone" (needs Omega)
    ready, fly = {}, {}
    pd = sso.pilot_data(session) if all_fits else None
    have = pd["skills"] if pd else None
    if have is not None:
        views = skills.fit_skills(layouts_for(all_fits), {f.id: f.fitting_levels() for f in all_fits}, have)
        for f in all_fits:
            me = views.get(f.id, {}).get("me")
            if me:
                fly[f.id] = "ready" if me["ready"] else "short" if me["short"] else "clone"
        for d in doctrines:
            ready[d.id] = sum(1 for f in d.fits if fly.get(f.id) == "ready")
    search_fits = []
    for d in doctrines:
        for f in d.fits:
            try:
                modules = sorted(all_names(parse_fit(f.eft)) - {f.ship})
            except EFTError:
                modules = []
            sid = ship_ids.get(f.id)
            search_fits.append({
                "doctrine": d.name, "url": url_for("doctrine", did=d.id) + f"#fit-{f.id}",
                "fit": f.name, "ship": f.ship, "cls": classes.get(sid, ""), "roles": app.jinja_env.filters["tags"](f.role),
                "author": d.author or "", "modules": modules,
                "icon": f"{IMG}/{sid}/icon?size=64" if sid else "", "meta": ship_meta.get(sid, 0) if sid else 0,
                "fly": fly.get(f.id, ""),
            })
    search_doctrines = [{"name": d.name, "url": url_for("doctrine", did=d.id), "author": d.author or "",
                         "desc": markup.plain(d.description or "")[:300], "fits": len(d.fits)} for d in doctrines]
    return render_template("index.html", doctrines=doctrines, ship_ids=ship_ids, ship_meta=ship_meta, ready=ready,
                           search_data={"fits": search_fits, "doctrines": search_doctrines, "meta": META_NAMES,
                                        "skills_known": have is not None})


@app.route("/doctrine/<int:did>")
def doctrine(did):
    d = db.get_or_404(Doctrine, did)
    layouts = layouts_for(d.fits)
    ship_meta = skills.meta_groups({L["ship_id"] for L in layouts.values()})
    fitting = {f.id: f.fitting_levels() for f in d.fits}
    pd = sso.pilot_data(session)
    have = pd["skills"] if pd else None
    return render_template("doctrine.html", d=d, layouts=layouts,
                           skill_views=skills.fit_skills(layouts, fitting, have, pd["attrs"] if pd else None),
                           ship_meta=ship_meta, have_skills=have is not None)


@app.route("/doctrine/<int:did>/xml")
def doctrine_export(did):
    d = db.get_or_404(Doctrine, did)
    lays = layouts_for(d.fits)
    xml = doctrine_xml([(f, lays[f.id]) for f in d.fits], d.description)
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", d.name) or "doctrine"
    return Response(xml, mimetype="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.xml"'})


@app.route("/doctrine/new", methods=["GET", "POST"])
@admin_required
def doctrine_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Give the doctrine a name.", "warn")
            return render_template("doctrine_form.html", d=None, form=request.form)
        d = Doctrine(name=name[:120], description=request.form.get("description", "").strip())
        set_author(d, request.form.get("author", ""))
        db.session.add(d)
        n, errors = add_fits_from_text(d, request.form.get("eft", ""))
        if n == 0:
            db.session.rollback()
            for e in errors:
                flash(e, "warn")
            return render_template("doctrine_form.html", d=None, form=request.form)
        db.session.commit()
        for e in errors:
            flash(e, "warn")
        flash(f"Doctrine created with {n} fit{'s' if n != 1 else ''}.", "ok")
        return redirect(url_for("doctrine", did=d.id))
    return render_template("doctrine_form.html", d=None, form={"author": session.get("sso_char_name", "")})


@app.route("/doctrine/<int:did>/edit", methods=["GET", "POST"])
@admin_required
def doctrine_edit(did):
    d = db.get_or_404(Doctrine, did)
    if request.method == "POST":
        d.name = request.form.get("name", d.name).strip()[:120] or d.name
        d.description = request.form.get("description", "").strip()
        set_author(d, request.form.get("author", ""))
        d.updated_at = now()
        n, errors = (0, [])
        if request.form.get("eft", "").strip():
            n, errors = add_fits_from_text(d, request.form["eft"])
        db.session.commit()
        for e in errors:
            flash(e, "warn")
        flash("Doctrine updated" + (f", {n} fit{'s' if n != 1 else ''} added." if n else "."), "ok")
        return redirect(url_for("doctrine", did=d.id))
    return render_template("doctrine_form.html", d=d, form={"name": d.name, "description": d.description, "author": d.author or ""})


@app.post("/doctrine/<int:did>/delete")
@admin_required
def doctrine_delete(did):
    d = db.get_or_404(Doctrine, did)
    item = _to_bin("doctrine", d.name, d.id, d.name, _doctrine_data(d))
    db.session.delete(d)
    db.session.commit()
    _undo_flash(f"Deleted {d.name}.", item)
    return redirect(url_for("index"))


# ---------- the bin: deleted doctrines and fits can be restored ----------

def _iso(dt):
    return dt.isoformat() if dt else None


def _from_iso(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def _fit_data(f):
    return {"id": f.id, "name": f.name, "ship": f.ship, "role": f.role, "notes": f.notes, "eft": f.eft,
            "position": f.position, "fitting_skills": f.fitting_skills or ""}


def _doctrine_data(d):
    return {"id": d.id, "name": d.name, "description": d.description, "author": d.author, "author_id": d.author_id,
            "created_at": _iso(d.created_at), "updated_at": _iso(d.updated_at), "fits": [_fit_data(f) for f in d.fits]}


def _to_bin(kind, name, did, dname, data):
    item = Deleted(kind=kind, name=name[:200], doctrine_id=did, doctrine_name=(dname or "")[:120],
                   data=json.dumps(data), deleted_by=session.get("sso_char_name", ""))
    db.session.add(item)
    return item


def _undo_flash(text, item):
    db.session.flush()
    flash(json.dumps({"text": text, "id": item.id}), "undo")


def _make_fit(fd, doctrine_id):
    keep_id = fd.get("id") if fd.get("id") and not db.session.get(Fit, fd["id"]) else None
    return Fit(id=keep_id, doctrine_id=doctrine_id, name=fd["name"], ship=fd["ship"], role=fd.get("role") or "",
               notes=fd.get("notes") or "", eft=fd["eft"], position=fd.get("position") or 0,
               fitting_skills=fd.get("fitting_skills") or "")


@app.route("/deleted")
@admin_required
def deleted():
    items = Deleted.query.order_by(Deleted.deleted_at.desc()).all()
    fit_counts = {i.id: len(json.loads(i.data).get("fits", [])) for i in items if i.kind == "doctrine"}
    live = {d.id for d in Doctrine.query.with_entities(Doctrine.id)}
    return render_template("deleted.html", items=items, fit_counts=fit_counts, live=live)


@app.post("/deleted/<int:bid>/restore")
@admin_required
def deleted_restore(bid):
    item = db.get_or_404(Deleted, bid)
    data = json.loads(item.data)
    if item.kind == "doctrine":
        keep_id = data.get("id") if data.get("id") and not db.session.get(Doctrine, data["id"]) else None
        d = Doctrine(id=keep_id, name=data["name"], description=data.get("description") or "",
                     author=data.get("author") or "", author_id=data.get("author_id"),
                     created_at=_from_iso(data.get("created_at")) or now())
        db.session.add(d)
        db.session.flush()
        for fd in data.get("fits", []):
            db.session.add(_make_fit(fd, d.id))
        d.updated_at = now()
        db.session.delete(item)
        db.session.commit()
        flash(f"Restored {d.name}.", "ok")
        return redirect(url_for("doctrine", did=d.id))
    d = db.session.get(Doctrine, item.doctrine_id) if item.doctrine_id else None
    if not d:
        flash(f"{item.doctrine_name or 'The doctrine this fit was in'} has been deleted. Restore it first, then restore this fit.", "warn")
        return redirect(url_for("deleted"))
    f = _make_fit(data, d.id)
    db.session.add(f)
    fits = sorted(d.fits + ([f] if f not in d.fits else []), key=lambda x: (x.position or 0, x is f))
    for pos, x in enumerate(fits):
        x.position = pos
    d.updated_at = now()
    db.session.delete(item)
    db.session.commit()
    flash(f"Restored {f.name} to {d.name}.", "ok")
    return redirect(url_for("doctrine", did=d.id) + f"#fit-{f.id}")


@app.post("/deleted/<int:bid>/purge")
@owner_required
def deleted_purge(bid):
    item = db.get_or_404(Deleted, bid)
    db.session.delete(item)
    db.session.commit()
    flash(f"{item.name} deleted for good.", "ok")
    return redirect(url_for("deleted"))


def fitting_form(f, form=None):
    """Data for the clickable fitting skill boxes on the edit form."""
    current = f.fitting_levels()
    if form is not None:
        current = {}
        for sid, _ in skills.FITTING_SKILLS:
            try:
                current[sid] = int(form.get(f"fs_{sid}", 0) or 0)
            except ValueError:
                pass
    caps = skills.alpha_caps() or {}
    tinfo = skills.train_infos({sid for sid, _ in skills.FITTING_SKILLS})
    rows = []
    for sid, name in skills.FITTING_SKILLS:
        t = tinfo.get(sid)
        rows.append({"id": sid, "name": name, "level": current.get(sid, 0), "cap": caps.get(sid),
                     "rank": t[0] if t else None, "desc": t[3] if t else "",
                     "attrs": " / ".join(a.capitalize() for a in t[1:3] if a) if t else ""})
    return {"fitting_rows": rows}


@app.route("/fit/<int:fid>/edit", methods=["GET", "POST"])
@admin_required
def fit_edit(fid):
    f = db.get_or_404(Fit, fid)
    if request.method == "POST":
        eft_text = request.form.get("eft", "").strip()
        try:
            p = parse_fit(eft_text)
        except EFTError as e:
            flash(str(e), "warn")
            return render_template("fit_form.html", f=f, form=request.form, **fitting_form(f, request.form))
        f.eft, f.ship = eft_text, p["ship"][:120]
        f.name = request.form.get("name", "").strip()[:120] or p["name"][:120]
        f.role = request.form.get("role", "").strip()[:60]
        f.notes = request.form.get("notes", "").strip()
        chosen = {}
        for sid, _ in skills.FITTING_SKILLS:
            try:
                lvl = int(request.form.get(f"fs_{sid}", 0) or 0)
            except ValueError:
                lvl = 0
            if 1 <= lvl <= 5:
                chosen[str(sid)] = lvl
        f.fitting_skills = json.dumps(chosen)
        f.doctrine.updated_at = now()
        db.session.commit()
        flash("Fit saved.", "ok")
        return redirect(url_for("doctrine", did=f.doctrine_id) + f"#fit-{f.id}")
    return render_template("fit_form.html", f=f, form={"name": f.name, "role": f.role, "notes": f.notes, "eft": f.eft},
                           **fitting_form(f))


@app.post("/fit/<int:fid>/move/<direction>")
@admin_required
def fit_move(fid, direction):
    f = db.get_or_404(Fit, fid)
    fits = list(f.doctrine.fits)
    i = fits.index(f)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(fits):
        fits[i], fits[j] = fits[j], fits[i]
        for pos, x in enumerate(fits):
            x.position = pos
        f.doctrine.updated_at = now()
        db.session.commit()
    return redirect(url_for("doctrine", did=f.doctrine_id) + f"#fit-{f.id}")


@app.post("/fit/<int:fid>/delete")
@admin_required
def fit_delete(fid):
    f = db.get_or_404(Fit, fid)
    did = f.doctrine_id
    item = _to_bin("fit", f.name, did, f.doctrine.name, _fit_data(f))
    f.doctrine.updated_at = now()
    db.session.delete(f)
    db.session.commit()
    _undo_flash(f"Removed {f.name}.", item)
    return redirect(url_for("doctrine", did=did))


@app.route("/admin/ship-check")
@admin_required
def ship_check():
    """Editors only: what each data source tells this server about a ship's tech/faction mark.
    Use as /admin/ship-check?ship=Federation Navy Comet"""
    from models import TypeReqs
    name = request.args.get("ship", "").strip()
    out = {"ship": name}
    info = esi.resolve({name}).get(name.lower()) if name else None
    if not info:
        out["error"] = "Ship name not found. Use the exact in-game name, e.g. ?ship=Federation Navy Comet"
        return jsonify(out)
    tid = info.type_id
    out["type_id"] = tid
    row = db.session.get(TypeReqs, tid)
    out["saved_meta_group"] = row.meta_group if row else None
    try:
        r = esi.session.get(f"{skills.REF_DATA}/{tid}", timeout=15)
        out["everef_status"] = r.status_code
        d = r.json() if r.ok else {}
        out["everef_meta_group"] = d.get("meta_group_id")
    except Exception as e:  # report, don't crash
        out["everef_error"] = repr(e)[:200]
    try:
        d = skills._get_type(tid)
        attrs = {a["attribute_id"]: a["value"] for a in d.get("dogma_attributes") or []}
        out["esi_metaGroupID_1692"] = attrs.get(1692)
        out["esi_techLevel_422"] = attrs.get(422)
        chain, gid = [], d.get("market_group_id")
        for _ in range(5):
            if not gid:
                break
            g = skills._market_group(gid)
            chain.append(g.get("name"))
            gid = g.get("parent_group_id")
        out["esi_market_tree"] = chain
    except Exception as e:
        out["esi_error"] = repr(e)[:200]
    try:
        out["fresh_lookup_result"] = skills._meta_lookup(tid)
    except Exception as e:
        out["fresh_lookup_error"] = repr(e)[:200]
    return jsonify(out)


@app.route("/login")
def login():
    """Old editor login address: editing now uses EVE login."""
    return redirect(url_for("sso_login", next=request.args.get("next", "")))


# ---------- who can edit ----------

@app.route("/access")
@owner_required
def access():
    rows = Access.query.order_by(Access.role.desc(), Access.name).all()
    return render_template("access.html", owners=[r for r in rows if r.role == "owner"],
                           editors=[r for r in rows if r.role == "editor"], env_owners=OWNER_LIST)


@app.post("/access/add")
@owner_required
def access_add():
    name = request.form.get("name", "").strip()
    new_role = "owner" if request.form.get("role") == "owner" else "editor"
    if not name:
        return redirect(url_for("access"))
    ch = esi.character(name)
    if not ch:
        flash(f"Couldn't find a character called {name}. Check the spelling (it must be the exact in-game name).", "warn")
        return redirect(url_for("access"))
    row = db.session.get(Access, ch["id"])
    if row:
        row.role, row.name = new_role, ch["name"]
        flash(f"{ch['name']} is now {'an owner' if new_role == 'owner' else 'an editor'}.", "ok")
    else:
        db.session.add(Access(char_id=ch["id"], name=ch["name"], role=new_role, added_by=session.get("sso_char_name", "")))
        flash(f"Added {ch['name']} as {'an owner' if new_role == 'owner' else 'an editor'}.", "ok")
    db.session.commit()
    return redirect(url_for("access"))


@app.post("/access/<int:cid>/remove")
@owner_required
def access_remove(cid):
    row = db.get_or_404(Access, cid)
    if cid == session.get("sso_char_id"):
        flash("You can't remove yourself. Ask another owner to do it.", "warn")
        return redirect(url_for("access"))
    db.session.delete(row)
    db.session.commit()
    flash(f"Removed {row.name}.", "ok")
    return redirect(url_for("access"))


# ---------- EVE login and Push to EVE ----------

def _safe_next(nxt):
    return nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else url_for("index")


@app.route("/sso/login")
def sso_login():
    if not sso.enabled():
        flash("EVE login isn't set up on this site yet.", "warn")
        return redirect(url_for("index"))
    session["sso_next"] = _safe_next(request.args.get("next", ""))
    return redirect(sso.login_url(session, url_for("sso_callback", _external=True)))


@app.route("/sso/callback")
def sso_callback():
    nxt = _safe_next(session.pop("sso_next", ""))
    if request.args.get("error") or not request.args.get("code"):
        flash("EVE login was cancelled.", "warn")
        return redirect(nxt)
    try:
        sso.finish_login(session, request.args["code"], request.args.get("state", ""))
    except ValueError as e:
        flash(str(e), "warn")
        return redirect(nxt)
    except Exception:
        app.logger.exception("EVE SSO login failed")
        flash("Couldn't log in with EVE just now. Please try again in a minute.", "warn")
        return redirect(nxt)
    session.permanent = True
    flash(f"Logged in as {session.get('sso_char_name')}. Push to EVE now puts fits straight into your fittings.", "ok")
    return redirect(nxt)


@app.route("/sso/logout")
def sso_logout():
    sso.logout(session)
    flash("Logged out of EVE.", "ok")
    return redirect(_safe_next(request.args.get("next", "")))


def _save_fits(fits, doctrine_name):
    """Save fits to the logged-in character. Returns a JSON response for the page script."""
    if not sso.enabled():
        return jsonify(ok=False, message="EVE login isn't set up on this site yet."), 400
    if not sso.character(session):
        return jsonify(ok=False, login=True, message="Log in with EVE first."), 401
    lays = layouts_for(fits)
    saved, failed, skipped = [], [], set()
    for f in fits:
        L = lays[f.id]
        if not L["ship_id"]:
            failed.append(f"{f.name}: ship not recognised")
            continue
        desc = markup.plain(f.notes or "").strip() or f"Rift Watch doctrine: {doctrine_name}"
        body, skip = sso.build_fitting(f.name, desc, L)
        skipped.update(skip)
        try:
            ok, msg = sso.save_fitting(session, body)
        except sso.NotLoggedIn:
            return jsonify(ok=False, login=True, saved=len(saved),
                           message="Your EVE login has run out. Log in again to carry on."), 401
        except Exception:
            app.logger.exception("Saving fit to EVE failed")
            ok, msg = False, "couldn't reach EVE"
        if ok:
            saved.append(f.name)
        else:
            failed.append(f"{f.name}: {msg}")
            if "full" in msg:
                break
    who = session.get("sso_char_name", "your character")
    if saved and not failed:
        message = (f"Pushed to {who}'s fittings. Find it in game under Fitting > Personal Fittings." if len(saved) == 1
                   else f"Pushed {len(saved)} fits to {who}'s fittings. Find them in game under Fitting > Personal Fittings.")
    elif saved:
        message = f"Pushed {len(saved)} of {len(fits)}. " + "; ".join(failed[:3])
    else:
        message = "Not pushed. " + "; ".join(failed[:3])
    if skipped and saved:
        message += " Left out (not allowed in saved fittings): " + ", ".join(sorted(skipped)[:5]) + "."
    return jsonify(ok=bool(saved) and not failed, saved=len(saved), message=message)


@app.post("/fit/<int:fid>/save-to-eve")
def fit_save_eve(fid):
    f = db.get_or_404(Fit, fid)
    return _save_fits([f], f.doctrine.name)


@app.post("/doctrine/<int:did>/save-to-eve")
def doctrine_save_eve(did):
    d = db.get_or_404(Doctrine, did)
    return _save_fits(list(d.fits), d.name)


@app.errorhandler(404)
def not_found(_):
    return render_template("base.html", not_found=True), 404


if __name__ == "__main__":
    app.run(debug=True)
