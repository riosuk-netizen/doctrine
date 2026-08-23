from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from app import db
from app.models import Fit, FitModule, Category
from app.services.eft_parser import parse_eft, to_eft_string, EftParseError
from app.services.esi_client import resolve_names_to_ids

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    category_id = request.args.get("category", type=int)
    query = request.args.get("q", "").strip()

    fits_query = Fit.query
    if category_id:
        fits_query = fits_query.filter_by(category_id=category_id)
    if query:
        fits_query = fits_query.filter(
            db.or_(Fit.name.ilike(f"%{query}%"), Fit.ship_name.ilike(f"%{query}%"))
        )

    fits = fits_query.order_by(Fit.ship_name, Fit.name).all()
    categories = Category.query.order_by(Category.name).all()
    return render_template("index.html", fits=fits, categories=categories,
                            active_category=category_id, query=query)


def _arc_positions(count, center_deg, spread_deg):
    """Evenly space `count` items across an arc, returning a list of angles in degrees."""
    if count <= 0:
        return []
    if count == 1:
        return [center_deg]
    start = center_deg - spread_deg / 2
    step = spread_deg / (count - 1)
    return [start + i * step for i in range(count)]


@bp.route("/fit/<int:fit_id>")
def view_fit(fit_id):
    fit = Fit.query.get_or_404(fit_id)
    sections = {}
    for m in fit.modules:
        sections.setdefault(m.slot_section, []).append(m)

    # Wheel angles: highs arc across the top, lows arc across the bottom.
    # Mids and rigs are rendered as side stacks in the template, not on the ring.
    high_angles = _arc_positions(len(sections.get("high", [])), center_deg=-90, spread_deg=110)
    low_angles = _arc_positions(len(sections.get("low", [])), center_deg=90, spread_deg=110)

    return render_template(
        "fit_detail.html", fit=fit, sections=sections,
        high_angles=high_angles, low_angles=low_angles,
    )


@bp.route("/fit/<int:fit_id>/export")
def export_fit(fit_id):
    fit = Fit.query.get_or_404(fit_id)
    text = to_eft_string(fit)
    return Response(text, mimetype="text/plain",
                     headers={"Content-Disposition": f'attachment; filename="{fit.name}.eft"'})


@bp.route("/fit/<int:fit_id>/delete", methods=["POST"])
def delete_fit(fit_id):
    fit = Fit.query.get_or_404(fit_id)
    db.session.delete(fit)
    db.session.commit()
    flash(f'Deleted "{fit.name}".', "success")
    return redirect(url_for("main.index"))


@bp.route("/import", methods=["GET", "POST"])
def import_fit():
    categories = Category.query.order_by(Category.name).all()

    if request.method == "GET":
        return render_template("import.html", categories=categories)

    raw_text = request.form.get("eft_text", "").strip()

    uploaded = request.files.get("eft_file")
    if uploaded and uploaded.filename:
        try:
            raw_text = uploaded.read().decode("utf-8").strip()
        except UnicodeDecodeError:
            flash("Couldn't read that file — make sure it's a plain text .eft/.txt export.", "error")
            return render_template("import.html", categories=categories, raw_text=raw_text), 400

    if not raw_text:
        flash("Paste an EFT fit or choose a file to upload.", "error")
        return render_template("import.html", categories=categories), 400

    try:
        parsed = parse_eft(raw_text)
    except EftParseError as e:
        flash(f"Couldn't parse that fit: {e}", "error")
        return render_template("import.html", categories=categories, raw_text=raw_text), 400

    # Gather every item/charge name in the fit so we can resolve them in one ESI batch call.
    names_to_resolve = [parsed["ship_name"]]
    for entries in parsed["sections"].values():
        for entry in entries:
            names_to_resolve.append(entry["item"])
            if entry["charge"]:
                names_to_resolve.append(entry["charge"])

    name_to_id = resolve_names_to_ids(names_to_resolve)

    category_id = request.form.get("category_id", type=int)
    if category_id == 0:
        category_id = None

    fit = Fit(
        name=parsed["fit_name"],
        ship_name=parsed["ship_name"],
        ship_type_id=name_to_id.get(parsed["ship_name"]),
        raw_eft=raw_text,
        notes=request.form.get("notes", "").strip() or None,
        category_id=category_id,
    )
    db.session.add(fit)

    order = 0
    for section, entries in parsed["sections"].items():
        for entry in entries:
            db.session.add(FitModule(
                fit=fit,
                slot_section=section,
                slot_order=order,
                item_name=entry["item"],
                charge_name=entry["charge"],
                quantity=entry["qty"],
                type_id=name_to_id.get(entry["item"]),
            ))
            order += 1

    db.session.commit()
    flash(f'Imported "{fit.name}" ({fit.ship_name}).', "success")
    return redirect(url_for("main.view_fit", fit_id=fit.id))


@bp.route("/categories", methods=["GET", "POST"])
def manage_categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            existing = Category.query.filter_by(name=name).first()
            if not existing:
                db.session.add(Category(name=name))
                db.session.commit()
                flash(f'Added category "{name}".', "success")
            else:
                flash(f'Category "{name}" already exists.', "error")
        return redirect(url_for("main.manage_categories"))

    categories = Category.query.order_by(Category.name).all()
    return render_template("categories.html", categories=categories)


@bp.route("/categories/<int:category_id>/delete", methods=["POST"])
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    flash(f'Deleted category "{category.name}".', "success")
    return redirect(url_for("main.manage_categories"))


@bp.route("/api/fits")
def api_fits():
    """Simple JSON listing, handy if you want to pull this into other tools later."""
    fits = Fit.query.order_by(Fit.ship_name).all()
    return jsonify([{
        "id": f.id, "name": f.name, "ship_name": f.ship_name,
        "category": f.category.name if f.category else None,
        "module_count": f.module_count,
    } for f in fits])
