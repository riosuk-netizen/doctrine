import hmac
import os
import re
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, Response, abort, flash, redirect, render_template,
                   request, session, url_for)

import esi
import markup
import skills
from eft import (DISPLAY_ORDER, LABELS, EFTError, all_names, build_layout,
                 doctrine_xml, parse_fit, split_fits)
from werkzeug.middleware.proxy_fix import ProxyFix

from sqlalchemy import inspect, text

from models import Doctrine, Fit, db, now

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # Render sits behind a proxy: keep links https
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
db_url = os.environ.get("DATABASE_URL", "sqlite:///doctrines.db")
for prefix in ("postgres://", "postgresql://"):
    if db_url.startswith(prefix):
        db_url = "postgresql+psycopg2://" + db_url[len(prefix):]
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

db.init_app(app)
with app.app_context():
    db.create_all()
    # add columns that newer versions introduced to tables made by older ones
    _new_cols = (
        ("doctrine", "author", "VARCHAR(120) DEFAULT ''"),
        ("doctrine", "author_id", "INTEGER"),
        ("type_reqs", "meta_group", "INTEGER"),
    )
    for _table, _name, _sql in _new_cols:
        if _name not in {c["name"] for c in inspect(db.engine).get_columns(_table)}:
            try:
                with db.engine.begin() as _conn:
                    _conn.execute(text(f"ALTER TABLE {_table} ADD COLUMN {_name} {_sql}"))
            except Exception:  # another worker got there first
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
app.jinja_env.filters["ago"] = ago
app.jinja_env.filters["tags"] = lambda s: [t.strip() for t in (s or "").split(",") if t.strip()]


def set_author(d, name):
    name = (name or "").strip()[:120]
    if name != (d.author or ""):
        d.author = name
        d.author_id = esi.character_id(name) if name else None
    elif name and not d.author_id:
        d.author_id = esi.character_id(name)


# ---------- helpers ----------

def is_admin():
    return not ADMIN_PASSWORD or session.get("admin") is True


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not is_admin():
            flash("Log in as an editor to do that.", "warn")
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


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

    return {"asset": asset, "is_admin": is_admin(), "open_mode": not ADMIN_PASSWORD, "icon": icon,
            "render_img": render_img, "ORDER": DISPLAY_ORDER, "LABELS": LABELS}


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
    return render_template("index.html", doctrines=doctrines, ship_ids=ship_ids)


@app.route("/doctrine/<int:did>")
def doctrine(did):
    d = db.get_or_404(Doctrine, did)
    layouts = layouts_for(d.fits)
    ship_meta = skills.meta_groups({L["ship_id"] for L in layouts.values()})
    return render_template("doctrine.html", d=d, layouts=layouts, skill_views=skills.fit_skills(layouts),
                           ship_meta=ship_meta)


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
    return render_template("doctrine_form.html", d=None, form={})


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
    db.session.delete(d)
    db.session.commit()
    flash(f"Deleted {d.name}.", "ok")
    return redirect(url_for("index"))


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
            return render_template("fit_form.html", f=f, form=request.form)
        f.eft, f.ship = eft_text, p["ship"][:120]
        f.name = request.form.get("name", "").strip()[:120] or p["name"][:120]
        f.role = request.form.get("role", "").strip()[:60]
        f.notes = request.form.get("notes", "").strip()
        f.doctrine.updated_at = now()
        db.session.commit()
        flash("Fit saved.", "ok")
        return redirect(url_for("doctrine", did=f.doctrine_id) + f"#fit-{f.id}")
    return render_template("fit_form.html", f=f, form={"name": f.name, "role": f.role, "notes": f.notes, "eft": f.eft})


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
    f.doctrine.updated_at = now()
    db.session.delete(f)
    db.session.commit()
    flash(f"Removed {f.name}.", "ok")
    return redirect(url_for("doctrine", did=did))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not ADMIN_PASSWORD:
        return redirect(url_for("index"))
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            session.permanent = True
            flash("Editor mode on.", "ok")
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("index"))
        flash("Wrong password.", "warn")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.errorhandler(404)
def not_found(_):
    return render_template("base.html", not_found=True), 404


if __name__ == "__main__":
    app.run(debug=True)
