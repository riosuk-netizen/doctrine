from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc)


class Doctrine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    author = db.Column(db.String(120), default="")
    author_id = db.Column(db.Integer)  # EVE character ID, for the portrait
    created_at = db.Column(db.DateTime, default=now)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)
    fits = db.relationship("Fit", backref="doctrine", cascade="all, delete-orphan",
                           order_by="Fit.position, Fit.id")


class Fit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctrine_id = db.Column(db.Integer, db.ForeignKey("doctrine.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    ship = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(60), default="")
    notes = db.Column(db.Text, default="")
    eft = db.Column(db.Text, nullable=False)
    position = db.Column(db.Integer, default=0)


class TypeReqs(db.Model):
    """Skills a type directly needs, as JSON {skill_id: level}."""
    type_id = db.Column(db.Integer, primary_key=True)
    reqs = db.Column(db.Text, nullable=False, default="{}")
    meta_group = db.Column(db.Integer)  # EVE meta group (2 = Tech II, 4 = Faction...), 0 = none, NULL = not checked yet


class SkillInfo(db.Model):
    """Skill name, skill group and its own prerequisites (JSON {skill_id: level})."""
    type_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    group_name = db.Column(db.String(120), nullable=False, default="Other")
    reqs = db.Column(db.Text, nullable=False, default="{}")


class KV(db.Model):
    """Small key/value store for cached reference data (alpha clone skill caps)."""
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)


class TypeInfo(db.Model):
    """Cache of EVE type name -> type ID and category, filled from ESI."""
    name_lower = db.Column(db.String(200), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type_id = db.Column(db.Integer, nullable=False)
    category_id = db.Column(db.Integer)
