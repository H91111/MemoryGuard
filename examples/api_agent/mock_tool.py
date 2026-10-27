"""Independent local simulator; never sends network requests or correct args."""


def mock_api_call(spec, args):
    if not isinstance(args, dict):
        return {"ok": False, "code": "PROTOCOL_ERROR"}
    if any(k not in args for k in ("project", "version", "operation", "path", "auth_field", "payload")):
        return {"ok": False, "code": "PROTOCOL_ERROR"}
    if args["operation"] != "login" or not isinstance(args["payload"], dict):
        return {"ok": False, "code": "PROTOCOL_ERROR"}
    matches = [s for s in spec if s["project"] == args["project"] and s["version"] == args["version"]]
    if len(matches) != 1:
        return {"ok": False, "code": "TOOL_REJECTED"}
    expected = matches[0]
    for attr in ("path", "auth_field", "timeout", "retries", "anonymous"):
        if attr in expected and args.get(attr) != expected[attr]:
            return {"ok": False, "code": "TOOL_REJECTED"}
    return {"ok": True, "code": "OK", "result": {"session": "simulated-session", "network_requests": 0}}
