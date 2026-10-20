MANAGED_FIELDS = ("ipv4", "description", "admin_state")


def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    # create: the interface does not exist yet
    if current_interface is None:
        return {
            "status": "ok",
            "result": "planned",
            "operation": "create",
            "changes": {
                field: {"to": desired_interface[field]}
                for field in MANAGED_FIELDS
            },
        }

    # update / no_change: only fields whose values differ
    changes = {}
    for field in MANAGED_FIELDS:
        if current_interface.get(field) != desired_interface[field]:
            changes[field] = {
                "from": current_interface.get(field),
                "to": desired_interface[field],
            }

    return {
        "status": "ok",
        "result": "planned",
        "operation": "update" if changes else "no_change",
        "changes": changes,
    }