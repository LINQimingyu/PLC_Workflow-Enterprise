import json
import uuid
from datetime import datetime, timezone


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
