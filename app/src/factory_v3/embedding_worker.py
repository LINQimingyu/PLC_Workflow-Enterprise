"""Optional isolated local-only encoder. stdin JSON -> stdout JSON."""
import os
import sys
import json
if sys.path and os.path.abspath(sys.path[0])==os.path.dirname(os.path.abspath(__file__)):
    sys.path.pop(0)  # Do not shadow stdlib http with the operator HTTP facade.
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
os.environ.update(HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",DO_NOT_TRACK="1")
if __name__=="__main__":
    import socket
    def blocked(*args,**kwargs): raise PermissionError("embedding worker network disabled")
    socket.create_connection=blocked
    socket.socket.connect=blocked
    from sentence_transformers import SentenceTransformer
    model=SentenceTransformer(sys.argv[1],device="cpu",local_files_only=True,trust_remote_code=False)
    texts=json.load(sys.stdin)
    vectors=model.encode(texts,normalize_embeddings=True,show_progress_bar=False).tolist()
    print(json.dumps(vectors,allow_nan=False))
