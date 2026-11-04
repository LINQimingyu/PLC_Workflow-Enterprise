"""One classification boundary shared by HTTP, bundles, retrieval and MCP."""
LEVELS = {"public": 0, "internal": 1, "restricted": 2, "pending": 3}


class PolicyDenied(PermissionError):
    pass


def classification(value):
    if value not in LEVELS:
        raise ValueError("资料分级必须为 public/internal/restricted/pending")
    return value


def inherited(*values):
    return max((classification(v) for v in values), key=LEVELS.get, default="pending")


def allow(level, destination):
    classification(level)
    if destination not in {"internal", "external"}:
        raise ValueError("必须指定 internal 或 external 目的地")
    if level == "pending" or (destination == "external" and level != "public"):
        raise PolicyDenied("资料待分级，或目的地不允许接收该级别的资料")
