import re

from app.backends.common import (
    error_response,
    exception_response,
    not_found_response,
    router_credentials,
)

TIMEOUT = 10


# ---------- real transport (used only when no callable is injected) ----------

def _connect(router):
    from netmiko import ConnectHandler

    user, password = router_credentials()
    return ConnectHandler(
        device_type="cisco_ios",
        host=router,
        username=user,
        password=password,
        conn_timeout=TIMEOUT,
        auth_timeout=TIMEOUT,
    )


def _read(connection, interface_name):
    """Run the two read-only commands and return parsed (ip_info, descriptions)."""
    ip_info = connection.send_command(
        f"show ip interface {interface_name}", use_textfsm=True
    )
    descriptions = connection.send_command(
        "show interfaces description", use_textfsm=True
    )

    # Netmiko returns the raw text when TextFSM cannot parse it. For a missing
    # interface IOS prints an error, which simply means "not found".
    if isinstance(ip_info, str):
        if "invalid" in ip_info.lower():
            return [], []
        raise RuntimeError("could not parse 'show ip interface'")
    if isinstance(descriptions, str):
        raise RuntimeError("could not parse 'show interfaces description'")

    return ip_info, descriptions


def _netmiko_get(router, interface_name):
    with _connect(router) as connection:
        return _read(connection, interface_name)


def _netmiko_delete(router, interface_name):
    with _connect(router) as connection:
        ip_info, descriptions = _read(connection, interface_name)
        if _build_state(interface_name, ip_info, descriptions) is None:
            return "not_found"

        connection.send_config_set([f"no interface {interface_name}"])

        ip_info, descriptions = _read(connection, interface_name)
        if _build_state(interface_name, ip_info, descriptions) is not None:
            raise RuntimeError("interface is still present after delete")

    return "deleted"


# ---------- status ----------

def _split(name):
    """'Loopback123' -> ('loopback', '123'); 'Lo123' -> ('lo', '123')."""
    match = re.match(r"^([A-Za-z\-]+)\s*(\d.*)$", str(name).strip())
    if not match:
        return str(name).strip().lower(), ""
    return match.group(1).lower(), match.group(2)


def _same_interface(full_name, port_name):
    """Match 'Loopback123' against an abbreviated name such as 'Lo123'."""
    full_letters, full_number = _split(full_name)
    port_letters, port_number = _split(port_name)
    return full_number == port_number and full_letters.startswith(port_letters)


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _build_state(interface_name, ip_info, descriptions):
    record = next(
        (
            item
            for item in ip_info
            if str(item.get("interface", "")).lower() == interface_name.lower()
        ),
        None,
    )
    if record is None:
        return None

    ip = _first(record.get("ip_address"))
    prefix = _first(record.get("prefix_length"))
    ipv4 = f"{ip}/{prefix}" if ip and prefix else None

    link_status = str(record.get("link_status", "")).lower()
    admin_state = "down" if "administratively down" in link_status else "up"

    description = None
    for item in descriptions:
        if _same_interface(interface_name, item.get("port", "")):
            description = item.get("description") or None
            break

    return {
        "name": interface_name,
        "ipv4": ipv4,
        "description": description,
        "admin_state": admin_state,
    }


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""
    netmiko_get = netmiko_get or _netmiko_get

    try:
        ip_info, descriptions = netmiko_get(router, interface_name)
        state = _build_state(interface_name, ip_info, descriptions)

        if state is None:
            return not_found_response()

        return {"status": "ok", "result": "found", "interface": state}
    except Exception as exc:
        return exception_response(exc)


# ---------- delete ----------

def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""
    netmiko_delete = netmiko_delete or _netmiko_delete

    try:
        outcome = netmiko_delete(router, interface_name)
    except Exception as exc:
        return exception_response(exc)

    if outcome == "deleted":
        return {"status": "ok", "result": "deleted"}
    if outcome == "not_found":
        return not_found_response()
    return error_response("backend_failed")