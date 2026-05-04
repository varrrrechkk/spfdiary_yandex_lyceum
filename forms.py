def clean_text(value):
    return "" if value is None else str(value).strip()


def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_bool(value):
    return str(value).lower() in {"1", "true", "yes", "on", "да"}


SKIN_TYPE_OPTIONS = {
    "I": "I — очень светлая кожа",
    "II": "II — светлая кожа",
    "III": "III — светло-смуглая кожа",
    "IV": "IV — смуглая кожа",
    "V": "V — тёмная кожа",
    "VI": "VI — очень тёмная кожа",
}


def clean_skin_type(value):
    value = clean_text(value).upper()
    return value if value in SKIN_TYPE_OPTIONS else "II"
