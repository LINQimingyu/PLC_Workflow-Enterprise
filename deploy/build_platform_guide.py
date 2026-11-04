"""Build generic, reflowable guides. Never reads a business workspace or private case."""
from pathlib import Path
import hashlib, html, json, re

ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/'app/resources/platform-guide'
CONTROLS='''<div class="reading-controls" role="group" aria-label="字体大小"><span>字体</span><button type="button" data-font-action="decrease" aria-label="缩小字体">A−</button><output data-font-output aria-label="字体比例" aria-live="polite">100%</output><button type="button" data-font-action="increase" aria-label="放大字体">A＋</button><button type="button" data-font-action="reset" aria-label="恢复默认字体">默认</button></div>'''

def inline(text):
    value=html.escape(text)
    value=re.sub(r'\*\*(.*?)\*\*',r'<strong>\1</strong>',value)
    return re.sub(r'`([^`]+)`',r'<code>\1</code>',value)

def markdown(text):
    out=[];toc=[];lines=text.splitlines();i=0;listing=False;heading=0
    while i<len(lines):
        line=lines[i]
        if not line.startswith('- ') and listing:out.append('</ul>');listing=False
        if line.startswith('|') and i+1<len(lines) and re.match(r'^\|[\s:|-]+\|$',lines[i+1]):
            headers=[x.strip() for x in line.strip('|').split('|')]
            out.append('<div class="table-wrap" tabindex="0" role="region" aria-label="可横向滚动的表格"><table><thead><tr>'+''.join('<th>'+inline(c)+'</th>' for c in headers)+'</tr></thead><tbody>');i+=2
            while i<len(lines) and lines[i].startswith('|'):
                out.append('<tr>'+''.join('<td>'+inline(c.strip())+'</td>' for c in lines[i].strip('|').split('|'))+'</tr>');i+=1
            out.append('</tbody></table></div>');continue
        match=re.match(r'^(#{1,3}) (.*)',line)
        if match:
            heading+=1;level=len(match[1]);anchor='section-'+str(heading)
            if level==2:toc.append((anchor,match[2]))
            out.append(f'<h{level} id="{anchor}">'+inline(match[2])+f'</h{level}>')
        elif line.strip()=='>':pass
        elif line.startswith('> '):out.append('<aside class="notice">'+inline(line[2:])+'</aside>')
        elif line.startswith('- '):
            if not listing:out.append('<ul>');listing=True
            out.append('<li>'+inline(line[2:])+'</li>')
        elif line.strip():out.append('<p>'+inline(line)+'</p>')
        i+=1
    if listing:out.append('</ul>')
    return ''.join(out),toc

def document(title,body,extra_script=''):
    css=(PUBLIC/'reading.css').read_text(encoding='utf-8')
    script=(PUBLIC/'reading.js').read_text(encoding='utf-8')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+css+'</style></head><body>'+body+'<script>'+script+'</script>'+(('<script>'+extra_script+'</script>') if extra_script else '')+'</body></html>'

def header(title):
    return '<header class="guide-header"><div><h1>'+html.escape(title)+'</h1><p>整体架构与工程交付</p></div>'+CONTROLS+'</header>'

def main():
    for ident,title in [('architecture','整体架构总览'),('workflow','工程交付工作流')]:
        body=header(title)+(PUBLIC/(ident+'-body.html')).read_text(encoding='utf-8')
        body+='<div class="standalone-actions"><button type="button" data-print>打印／另存为 PDF</button></div><footer class="guide-footer">静态、编译、仿真、现场与效果证据分别记录。</footer>'
        script="document.querySelector('[data-print]').addEventListener('click',()=>window.print());"
        (PUBLIC/(ident+'.html')).write_text(document(title,body,script),encoding='utf-8',newline='\n')
        content,toc=markdown((ROOT/'docs/平台说明'/('整体架构.md' if ident=='architecture' else '工作流.md')).read_text(encoding='utf-8'))
        body=header(title+'详细说明')+'<div class="article-layout"><nav aria-label="内容目录">'+''.join('<a href="#'+anchor+'">'+html.escape(label)+'</a>' for anchor,label in toc)+'</nav><main>'+content+'</main></div>'
        (PUBLIC/(ident+'-note.html')).write_text(document(title+'详细说明',body),encoding='utf-8',newline='\n')
    body=header('AgentsPLC 平台说明')+'''<div class="guide-bar"><div role="tablist" aria-label="说明内容"><button role="tab" id="architecture-tab" data-id="architecture" aria-selected="true" aria-controls="document">整体架构总览</button> <button role="tab" id="workflow-tab" data-id="workflow" aria-selected="false" aria-controls="document" tabindex="-1">工程交付工作流</button></div><div class="guide-links"><a id="workbench" href="/" target="_blank" rel="noopener">打开项目工作台</a><a id="read" target="_blank" rel="noopener">阅读详细说明</a><a id="open" target="_blank" rel="noopener">独立打开／打印</a></div></div><p class="guide-note" id="note"></p><iframe class="guide-frame" id="document" title="整体架构总览" sandbox="allow-scripts" referrerpolicy="no-referrer" role="tabpanel" aria-labelledby="architecture-tab"></iframe>'''
    script='''(()=>{const local=location.protocol==='file:';
const routes=local?{architecture:'architecture.html',workflow:'workflow.html'}:{architecture:'/api/guides/architecture',workflow:'/api/guides/workflow'};
const notes=local?{architecture:'architecture-note.html',workflow:'workflow-note.html'}:{architecture:'/api/guides/architecture-note',workflow:'/api/guides/workflow-note'};
const copy={architecture:'按层阅读职责与执行关系，字体可调；说明中的项目示例已移至项目工作台。',workflow:'主线按编号顺序执行；缺项与修复条件就近说明，字体设置在切换后保留。'};
function show(id){document.querySelectorAll('[data-id]').forEach(b=>{b.setAttribute('aria-selected',String(b.dataset.id===id));b.tabIndex=b.dataset.id===id?0:-1;});const f=document.getElementById('document');f.src=routes[id];f.title=document.querySelector('[data-id="'+id+'"]').textContent;f.setAttribute('aria-labelledby',id+'-tab');document.getElementById('note').textContent=copy[id];document.getElementById('read').href=notes[id];document.getElementById('open').href=routes[id];}
document.querySelectorAll('[data-id]').forEach(b=>{b.addEventListener('click',()=>show(b.dataset.id));b.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const id=e.key==='Home'?'architecture':e.key==='End'?'workflow':b.dataset.id==='architecture'?'workflow':'architecture';show(id);document.querySelector('[data-id="'+id+'"]').focus();});});
if(local)document.getElementById('workbench').href='http://127.0.0.1:8774/';show('architecture');})();'''
    (PUBLIC/'index.html').write_text(document('AgentsPLC 平台说明',body,script),encoding='utf-8',newline='\n')
    names=['index.html','architecture.html','workflow.html','architecture-note.html','workflow-note.html']
    manifest={'schema':'local-guide-1','presentation':'reflowable-reading-2','files':{name:hashlib.sha256((PUBLIC/name).read_bytes()).hexdigest() for name in names}}
    (PUBLIC/'guide-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Built 5 generic guide pages; no private case read')

if __name__=='__main__':main()
