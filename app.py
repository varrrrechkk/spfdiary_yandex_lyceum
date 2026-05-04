import os
import re
from datetime import date
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_restful import Api, Resource, abort as api_abort
from sqlalchemy import inspect, text

from forms import SKIN_TYPE_OPTIONS, clean_skin_type, clean_text, to_bool, to_int
from models import SunSession, User, db
from services import MAX_MONTHS_BACK, SunDiaryService, build_calendar, get_month_title, month_to_value, shift_month

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "simple-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tanning.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

db.init_app(app)
api = Api(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def ensure_upload_folder():
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


def clean_filename(filename):
    filename = os.path.basename(str(filename or "")).strip()
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    return filename.strip("._")


def allowed_file(filename):
    return bool(filename and "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS)


def save_photo(file_obj):
    if not file_obj or not file_obj.filename:
        return None

    filename = clean_filename(file_obj.filename)
    if not allowed_file(filename):
        return None

    path = UPLOAD_FOLDER / filename
    index = 1
    stem, ext = os.path.splitext(filename)
    while path.exists():
        path = UPLOAD_FOLDER / f"{stem}_{index}{ext}"
        index += 1
    file_obj.save(path)
    return path.name


def build_session_payload(form, files):
    location = clean_text(form.get("location"))
    date_value = clean_text(form.get("date"))
    start_time = clean_text(form.get("start_time"))
    if not location or not date_value or not start_time:
        return None, "Заполни место, дату и время."

    duration = to_int(form.get("duration"), 0)
    was_outside = to_bool(form.get("was_outside"))
    used_spf = to_bool(form.get("used_spf"))
    had_tan = to_bool(form.get("had_tan"))
    skin_type = clean_skin_type(form.get("skin_type"))
    notes = clean_text(form.get("notes"))

    was_outside, used_spf, had_tan, duration = SunDiaryService.normalize_session_values(
        was_outside,
        used_spf,
        had_tan,
        duration,
    )
    if was_outside and had_tan and duration <= 0:
        return None, "Если загар отмечен, длительность должна быть больше нуля."

    context, error = SunDiaryService.validate_location_datetime(location, date_value, start_time)
    if error:
        return None, error

    uv_data = SunDiaryService.get_uv_for_day(location, date_value, start_time, context=context)

    return {
        "location": location,
        "date": date_value,
        "start_time": start_time,
        "duration": duration,
        "was_outside": was_outside,
        "used_spf": used_spf,
        "had_tan": had_tan,
        "skin_type": skin_type,
        "uv_index": uv_data["uv"] if uv_data else None,
        "notes": notes,
        "photo_path": save_photo(files.get("photo")),
    }, None


def save_session(payload, user_id):
    session = SunSession(user_id=user_id, **payload)
    db.session.add(session)
    db.session.commit()
    return session


class SessionsListResource(Resource):
    def get(self):
        if not current_user.is_authenticated:
            api_abort(401, message="Сначала нужно войти в аккаунт.")
        sessions = SunSession.query.filter_by(user_id=current_user.id).order_by(SunSession.id.desc()).all()
        return {"sessions": [session.to_dict() for session in sessions]}

    def post(self):
        if not current_user.is_authenticated:
            api_abort(401, message="Сначала нужно войти в аккаунт.")
        payload, error = build_session_payload(request.form, request.files)
        if error:
            api_abort(400, message=error)
        session = save_session(payload, current_user.id)
        return {"id": session.id, "session": session.to_dict()}


class SessionResource(Resource):
    def get(self, session_id):
        if not current_user.is_authenticated:
            api_abort(401, message="Сначала нужно войти в аккаунт.")
        session = SunSession.query.filter_by(id=session_id, user_id=current_user.id).first()
        if not session:
            api_abort(404, message="Запись не найдена.")
        return {"session": session.to_dict()}

    def delete(self, session_id):
        if not current_user.is_authenticated:
            api_abort(401, message="Сначала нужно войти в аккаунт.")
        session = SunSession.query.filter_by(id=session_id, user_id=current_user.id).first()
        if not session:
            api_abort(404, message="Запись не найдена.")
        db.session.delete(session)
        db.session.commit()
        return {"message": "Запись удалена."}


class CurrentWeatherResource(Resource):
    def get(self):
        label = clean_text(request.args.get("label"))
        location = clean_text(request.args.get("location"))
        country = clean_text(request.args.get("country"))

        place = None
        context = None
        if request.args.get("latitude") and request.args.get("longitude"):
            try:
                place = {
                    "latitude": float(request.args["latitude"]),
                    "longitude": float(request.args["longitude"]),
                    "name": label or location or "Локация",
                    "country": country,
                }
            except ValueError:
                place = None
        if place is None and location:
            context = SunDiaryService.get_location_context(location)
            place = context or SunDiaryService.resolve_location(location)

        weather = SunDiaryService.get_current_weather_for_place(place) if place else None
        if not weather:
            api_abort(404, message="Не удалось получить текущую погоду.")

        return {
            "ok": True,
            "weather": weather,
            "location": place.get("name") if place else weather.get("location"),
            "country": place.get("country", "") if place else weather.get("country", ""),
            "local_now": context.get("local_now") if context else None,
        }


class UVResource(Resource):
    def get(self):
        weather = SunDiaryService.get_uv_for_day(
            clean_text(request.args.get("location")),
            clean_text(request.args.get("date")),
            clean_text(request.args.get("time")),
        )
        if not weather:
            api_abort(404, message="Не удалось получить UV-индекс.")
        return {"weather": weather}


class LocationContextResource(Resource):
    def get(self):
        context = SunDiaryService.get_location_context(clean_text(request.args.get("location")))
        if not context:
            api_abort(404, message="Не удалось определить локацию.")

        return {
            "ok": True,
            "location": context.get("name"),
            "country": context.get("country", ""),
            "latitude": context.get("latitude"),
            "longitude": context.get("longitude"),
            "timezone": context.get("timezone"),
            "local_now": context.get("local_now"),
        }


api.add_resource(SessionsListResource, "/api/sessions")
api.add_resource(SessionResource, "/api/sessions/<int:session_id>")
api.add_resource(CurrentWeatherResource, "/api/current-weather")
api.add_resource(UVResource, "/api/uv")
api.add_resource(LocationContextResource, "/api/location-context")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("diary"))

    if request.method == "POST":
        username = clean_text(request.form.get("username"))
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not username or not password or not password2:
            flash("Заполни все поля.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("Такой пользователь уже есть.", "danger")
        elif password != password2:
            flash("Пароли не совпадают.", "danger")
        else:
            db.session.add(User(username=username, password=password))
            db.session.commit()
            flash("Аккаунт создан. Теперь можно войти.", "success")
            return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("diary"))

    if request.method == "POST":
        username = clean_text(request.form.get("username"))
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.password == password:
            login_user(user)
            return redirect(url_for("diary"))
        flash("Неверный логин или пароль.", "danger")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/diary")
@login_required
def diary():
    month_value = clean_text(request.args.get("month"))
    today = date.today()
    current_year, current_month = today.year, today.month
    earliest_year, earliest_month = shift_month(current_year, current_month, -MAX_MONTHS_BACK)

    try:
        year, month = (int(x) for x in month_value.split("-")) if month_value else (current_year, current_month)
    except ValueError:
        year, month = current_year, current_month

    if (year, month) < (earliest_year, earliest_month):
        year, month = earliest_year, earliest_month
    if (year, month) > (current_year, current_month):
        year, month = current_year, current_month

    prefix = f"{year}-{month:02d}"
    sessions = SunSession.query.filter_by(user_id=current_user.id).filter(
        SunSession.date.like(f"{prefix}%")
    ).order_by(
        SunSession.date.desc(),
        SunSession.start_time.desc(),
        SunSession.id.desc(),
    ).all()

    return render_template(
        "diary.html",
        sessions=sessions,
        calendar_weeks=build_calendar(sessions, year, month),
        month_title=get_month_title(year, month),
        prev_month=None if (year, month) == (earliest_year, earliest_month) else month_to_value(*shift_month(year, month, -1)),
        next_month=None if (year, month) == (current_year, current_month) else month_to_value(*shift_month(year, month, 1)),
    )


@app.route("/diary/add", methods=["GET", "POST"])
@login_required
def add_session():
    if request.method == "POST":
        payload, error = build_session_payload(request.form, request.files)
        if error:
            flash(error, "danger")
        else:
            save_session(payload, current_user.id)
            flash("Запись сохранена.", "success")
            return redirect(url_for("diary"))

    return render_template("add_session.html", skin_types=SKIN_TYPE_OPTIONS)


@app.route("/diary/delete/<int:session_id>", methods=["POST"])
@login_required
def delete_session(session_id):
    session = SunSession.query.filter_by(id=session_id, user_id=current_user.id).first()
    if not session:
        flash("Запись не найдена.", "danger")
        return redirect(url_for("diary"))
    db.session.delete(session)
    db.session.commit()
    flash("Запись удалена.", "success")
    return redirect(url_for("diary"))


@app.route("/analytics")
@login_required
def analytics():
    sessions = SunSession.query.filter_by(user_id=current_user.id).order_by(
        SunSession.date.desc(),
        SunSession.start_time.desc(),
        SunSession.id.desc(),
    ).all()
    return render_template("analytics.html", stats=SunDiaryService.build_analytics_stats(sessions))


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


def ensure_schema():
    inspector = inspect(db.engine)
    try:
        columns = {column["name"] for column in inspector.get_columns("sun_session")}
    except Exception:
        columns = set()
    if "skin_type" not in columns:
        db.session.execute(text("ALTER TABLE sun_session ADD COLUMN skin_type VARCHAR(2) NOT NULL DEFAULT 'II'"))
        db.session.commit()


with app.app_context():
    ensure_upload_folder()
    db.create_all()
    ensure_schema()


if __name__ == "__main__":
    app.run(debug=True)
