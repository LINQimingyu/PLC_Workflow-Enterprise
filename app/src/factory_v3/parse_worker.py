"""Local parsing subprocess: no network, macro execution or filesystem extraction."""
import base64
import json
import socket
import sys
def deny(*args,**kwargs): raise PermissionError("parser network disabled")
def main():
    sys.stdin.reconfigure(encoding="utf-8"); sys.stdout.reconfigure(encoding="utf-8")
    socket.socket.connect=deny; socket.create_connection=deny
    from cim.documents import parse
    data=json.load(sys.stdin)
    chunks,status=parse(data["name"],base64.b64decode(data["raw"],validate=True))
    print(json.dumps({"chunks":chunks,"status":status},ensure_ascii=True))
if __name__=="__main__": main()
