"""Offline feature vectors, deliberately not described as semantic embeddings."""
import hashlib
import math
import re
from array import array

DIMENSIONS=128


def terms(text):
    words=re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+",text.casefold())
    return set(token for word in words for token in ([word] if not re.search(r"[\u4e00-\u9fff]",word) else [word]+[word[i:i+2] for i in range(len(word)-1)]))


def vector(text):
    result=array("f",[0.0]*DIMENSIONS)
    for term in terms(text):
        key=hashlib.blake2b(term.encode(),digest_size=8).digest()
        index=int.from_bytes(key[:4],"little")%DIMENSIONS
        result[index]+=1 if key[4]&1 else -1
    norm=math.sqrt(sum(x*x for x in result)) or 1
    return array("f",[x/norm for x in result])


def from_bytes(raw):
    result=array("f")
    result.frombytes(raw)
    return result


def similarity(a,b):
    return max(0.0,sum(x*y for x,y in zip(a,b)))
