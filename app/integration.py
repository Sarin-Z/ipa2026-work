"""Part 4 student implementation."""

import yaml

from app.core import validate_request
from app.dispatcher import dispatch_request

from app.request_handler import validate_webex_envelope


def process_request(mentioned_people, attachment_path, bot_person_id):
    # 1. mention + attachment envelope
    error = validate_webex_envelope(
        mentioned_people, attachment_path, bot_person_id
    )
    if error is not None:
        return error

    # 2. load the YAML once
    try:
        with open(attachment_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        return {"status": "error", "result": "invalid_yaml"}

    # 3. validate the parsed request
    validation = validate_request(data)
    if validation != {"status": "ok", "result": "accepted"}:
        return validation

    # 4. dispatch accepted requests only; return the backend response as is
    return dispatch_request(data)