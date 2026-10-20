import yaml

ALLOWED_ROUTERS = {
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
}

ALLOWED_ACTIONS = {
    "restconf": {"status", "plan", "apply"},
    "netconf": {"status", "plan", "apply"},
    "ansible": {"apply"},
    "netmiko-textfsm": {"status", "delete"},
}

ADMIN_STATES = {"up", "down"}


def _error(code):
    return {"status": "error", "result": code}


def _absent(value):
    """A value counts as missing when it is None or an empty string."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    # Root must be a mapping.
    if not isinstance(data, dict):
        return _error("invalid_yaml")

    # 1. version: must be the integer 1 (bool is a subclass of int, so
    #    exclude it explicitly; 1.0 and "1" are rejected by the type check).
    version = data.get("version")
    if type(version) is not int or version != 1:
        return _error("invalid_version")

    # 2. router
    router = data.get("router")
    if _absent(router):
        return _error("missing_router")
    if not isinstance(router, str) or router not in ALLOWED_ROUTERS:
        return _error("invalid_router")

    # 3. method
    method = data.get("method")
    if _absent(method):
        return _error("missing_method")
    if not isinstance(method, str) or method not in ALLOWED_ACTIONS:
        return _error("invalid_method")

    # 4. action (checked against the selected method)
    action = data.get("action")
    if _absent(action):
        return _error("missing_action")
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS[method]:
        return _error("invalid_action")

    # 5. desired / interface / name
    desired = data.get("desired")
    if not isinstance(desired, dict):
        return _error("missing_desired")

    interface = desired.get("interface")
    if not isinstance(interface, dict):
        return _error("missing_interface")

    if _absent(interface.get("name")):
        return _error("missing_interface_name")

    # 6. complete interface definition: plan and apply only
    if action in ("plan", "apply"):
        if _absent(interface.get("ipv4")):
            return _error("missing_ipv4")
        if _absent(interface.get("description")):
            return _error("missing_description")
        admin_state = interface.get("admin_state")
        if _absent(admin_state):
            return _error("missing_admin_state")
        if not isinstance(admin_state, str) or admin_state not in ADMIN_STATES:
            return _error("invalid_admin_state")

    return {"status": "ok", "result": "accepted"}


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        return _error("invalid_yaml")

    return validate_request(data)