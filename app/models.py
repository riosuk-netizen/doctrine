from datetime import datetime
from app import db


class Category(db.Model):
    """Doctrine grouping, e.g. 'Roaming', 'Home Defense', 'Capitals'."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    fits = db.relationship("Fit", backref="category", lazy=True)


class Fit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    ship_name = db.Column(db.String(100), nullable=False)
    ship_type_id = db.Column(db.Integer, nullable=True)  # resolved via ESI
    raw_eft = db.Column(db.Text, nullable=False)  # original pasted/uploaded text
    notes = db.Column(db.Text, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    modules = db.relationship("FitModule", backref="fit", lazy=True,
                               cascade="all, delete-orphan", order_by="FitModule.slot_order")

    @property
    def module_count(self):
        return len(self.modules)


class FitModule(db.Model):
    """One line item from an EFT fit: a module, charge, drone, or cargo entry."""
    id = db.Column(db.Integer, primary_key=True)
    fit_id = db.Column(db.Integer, db.ForeignKey("fit.id"), nullable=False)
    slot_section = db.Column(db.String(20), nullable=False)  # high/mid/low/rig/subsystem/drone/cargo
    slot_order = db.Column(db.Integer, nullable=False, default=0)
    item_name = db.Column(db.String(150), nullable=False)
    charge_name = db.Column(db.String(150), nullable=True)  # ammo/charge loaded, if any
    quantity = db.Column(db.Integer, nullable=True)  # for drones/cargo
    type_id = db.Column(db.Integer, nullable=True)  # resolved via ESI
