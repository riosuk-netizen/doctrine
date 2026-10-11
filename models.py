from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc)


class Doctrine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
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


class TypeInfo(db.Model):
    """Cache of EVE type name -> type ID and category, filled from ESI."""
    name_lower = db.Column(db.String(200), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type_id = db.Column(db.Integer, nullable=False)
    category_id = db.Column(db.Integer)
