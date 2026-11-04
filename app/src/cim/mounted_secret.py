"""Read-only, endpoint-bound planner credential supplied by the deployment owner."""
from pathlib import Path


class MountedPlannerSecret:
    read_only = True

    def __init__(self, path, target):
        self.path = Path(path)
        self.target = target

    def read(self, target):
        if target != self.target:
            return ""
        with self.path.open("rb") as stream:
            raw = stream.read(2402)
        try:
            value = raw.decode("utf-8").strip()
        except UnicodeError:
            raise OSError("规划密钥文件须为 UTF-8 文本") from None
        if not value or len(raw) > 2401 or len(value.encode("utf-8")) > 2400 or "\n" in value or "\r" in value:
            raise OSError("规划密钥文件须为单行 API Key")
        return value

    def write(self, target, value):
        raise PermissionError("部署密钥为只读挂载")

    def delete(self, target):
        raise PermissionError("部署密钥为只读挂载")
