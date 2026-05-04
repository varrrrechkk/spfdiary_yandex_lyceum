from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

    sessions = db.relationship("SunSession", backref="user", lazy=True)


class SunSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(100), nullable=False)
    date = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.String(10), nullable=False)
    duration = db.Column(db.Integer, nullable=False, default=0)
    was_outside = db.Column(db.Boolean, default=False)
    used_spf = db.Column(db.Boolean, default=False)
    had_tan = db.Column(db.Boolean, default=False)
    skin_type = db.Column(db.String(2), nullable=False, default="II")
    uv_index = db.Column(db.Float)
    notes = db.Column(db.Text)
    photo_path = db.Column(db.String(255))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "location": self.location,
            "date": self.date,
            "start_time": self.start_time,
            "duration": self.duration,
            "was_outside": self.was_outside,
            "used_spf": self.used_spf,
            "had_tan": self.had_tan,
            "skin_type": self.skin_type,
            "uv_index": self.uv_index,
            "notes": self.notes,
            "photo_path": self.photo_path,
            "user_id": self.user_id,
        }
