"""Read-only generic guides with digest-bound scripts; project cases live in projects."""
from pathlib import Path
import base64,hashlib,json,re
from fastapi import Request
from fastapi.responses import Response

APP=Path(__file__).resolve().parents[2]
PUBLIC=APP/'resources/platform-guide'
FILES={
 'index':('index.html','text/html'),
 'architecture':('architecture.html','text/html'),
 'workflow':('workflow.html','text/html'),
 'architecture-note':('architecture-note.html','text/html'),
 'workflow-note':('workflow-note.html','text/html'),
}

def load(ident,resource_root=None):
    if ident not in FILES:raise KeyError('说明资料不存在')
    filename,media=FILES[ident]
    folder=Path(resource_root) if resource_root is not None else PUBLIC
    target=folder/filename
    if not target.is_file() or not (folder/'guide-manifest.json').is_file():raise KeyError('本机尚未安装这份说明资料')
    if target.stat().st_size>8*1024*1024:raise ValueError('说明资料超出大小边界')
    manifest=json.loads((folder/'guide-manifest.json').read_text(encoding='utf-8'))
    data=target.read_bytes()
    if manifest.get('schema')!='local-guide-1' or manifest['files'].get(filename)!=hashlib.sha256(data).hexdigest():
        raise ValueError('说明资料摘要不一致，请重新生成并核对')
    return filename,media,data


def html_policy(data):
    # Permit only the exact scripts from the hash-checked local HTML. No global unsafe-inline.
    tokens=[]
    for code in re.findall(rb'<script\b[^>]*>([\s\S]*?)</script\s*>',data,re.I):
        for value in {code,code.replace(b'\r\n',b'\n')}:
            tokens.append("'sha256-"+base64.b64encode(hashlib.sha256(value).digest()).decode()+"'")
    return ("default-src 'none'; script-src 'self' "+' '.join(sorted(set(tokens)))+
            "; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' blob: data:; "
            "frame-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")

def register_guides(app,resource_root=None):
    @app.get('/api/guides')
    def listing(request:Request):
        result=[]
        for ident,title in [('architecture','整体架构总览'),('workflow','工程交付工作流')]:
            available=False
            try:load(ident,resource_root);available=True
            except (KeyError,ValueError,FileNotFoundError):pass
            result.append({'id':ident,'title':title,'allowed':True,'available':available})
        return result

    @app.get('/api/guides/{ident}')
    def read(ident:str,request:Request):
        _,media,data=load(ident,resource_root)
        return Response(data,media_type=media,headers={'Content-Security-Policy':html_policy(data)})
