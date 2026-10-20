import xml.etree.ElementTree as ET
from ipaddress import IPv4Interface
from xml.sax.saxutils import escape

from app.backends.common import (
    applied_response,
    exception_response,
    not_found_response,
    router_credentials,
)
from app.backends.planning import plan_interface as build_interface_plan

IETF_INTERFACES_NS = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IETF_IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"
TIMEOUT = 10


# ---------- real transport (used only when no callable is injected) ----------

def _connect(router):
    from ncclient import manager

    user, password = router_credentials()
    return manager.connect(
        host=router,
        port=830,
        username=user,
        password=password,
        hostkey_verify=False,
        look_for_keys=False,
        allow_agent=False,
        timeout=TIMEOUT,
    )


def _netconf_get_config(router, filter_xml):
    with _connect(router) as session:
        reply = session.get_config(source="running", filter=("subtree", filter_xml))
        return reply.data_xml


def _netconf_edit_config(router, config_xml):
    with _connect(router) as session:
        session.edit_config(target="running", config=config_xml)


# ---------- status ----------

def _filter_xml(interface_name):
    return (
        f'<interfaces xmlns="{IETF_INTERFACES_NS}">'
        f"<interface><name>{escape(interface_name)}</name></interface>"
        f"</interfaces>"
    )


def _text(element, path, ns):
    node = element.find(path, ns)
    if node is None or node.text is None:
        return None
    return node.text.strip()


def _normalize(interface, ns):
    ipv4 = None
    ip = _text(interface, "ip:ipv4/ip:address/ip:ip", ns)
    netmask = _text(interface, "ip:ipv4/ip:address/ip:netmask", ns)
    if ip and netmask:
        ipv4 = str(IPv4Interface(f"{ip}/{netmask}"))

    return {
        "name": _text(interface, "if:name", ns),
        "ipv4": ipv4,
        "description": _text(interface, "if:description", ns) or None,
        "admin_state": (
            "up" if _text(interface, "if:enabled", ns) == "true" else "down"
        ),
    }


def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""
    netconf_get_config = netconf_get_config or _netconf_get_config

    try:
        xml_text = netconf_get_config(router, _filter_xml(interface_name))
        root = ET.fromstring(xml_text)
        ns = {"if": IETF_INTERFACES_NS, "ip": IETF_IP_NS}

        for interface in root.iter(f"{{{IETF_INTERFACES_NS}}}interface"):
            if _text(interface, "if:name", ns) == interface_name:
                return {
                    "status": "ok",
                    "result": "found",
                    "interface": _normalize(interface, ns),
                }

        return not_found_response()
    except Exception as exc:
        return exception_response(exc)


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""
    return build_interface_plan(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, netconf_get_config),
    )


# ---------- apply ----------

def _config_xml(desired_interface):
    number = int(desired_interface["name"][len("Loopback"):])
    ipv4 = IPv4Interface(desired_interface["ipv4"])
    shutdown = "<shutdown/>" if desired_interface["admin_state"] == "down" else ""

    return (
        '<config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" '
        'xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
        '<native xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-native">'
        "<interface>"
        '<Loopback nc:operation="replace">'
        f"<name>{number}</name>"
        f"<description>{escape(desired_interface['description'])}</description>"
        "<ip><address><primary>"
        f"<address>{ipv4.ip}</address>"
        f"<mask>{ipv4.network.netmask}</mask>"
        "</primary></address></ip>"
        f"{shutdown}"
        "</Loopback>"
        "</interface>"
        "</native>"
        "</config>"
    )


def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""
    netconf_edit_config = netconf_edit_config or _netconf_edit_config

    try:
        netconf_edit_config(router, _config_xml(desired_interface))
        return applied_response()
    except Exception as exc:
        return exception_response(exc)