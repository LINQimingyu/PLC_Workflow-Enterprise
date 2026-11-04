"""Source-only platform release. Never reads business workspace or secret settings."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
DIRS=['app/src','app/resources','app/agents','app/skills','app/enterprise_skills','app/process-packs','app/requirements',
      'app/evals','app/tests','app/web/src','app/web/tests','app/native_adapters','app/hardware_reader','app/simulator_gateway','docs']
FILES=['README.md','AGENTS.md','LICENSE','NOTICE','.gitignore','.dockerignore','Dockerfile','compose.yaml',
       '打开企业工作台.cmd','启动企业工作台.ps1','安装与构建.ps1','app/ENTERPRISE.json','app/LICENSE','app/NOTICE','app/LICENSE-SCOPE.md',
       'app/THIRD_PARTY_NOTICES.md','app/UPSTREAM.json','app/creation-agent.json','app/pytest.ini','app/requirements.txt',
       'app/web/package.json','app/web/package-lock.json','app/web/tsconfig.json','app/web/vite.config.ts','app/web/index.html','app/web/simulator.html']
DEPLOY=['build_platform_guide.py','source_release.py','local_postgres.py','backup.py','qa_browser.py','container_entry.py','prepare_docker.py','init_db.sh']
FORBIDDEN={'说明资料','.qa','.local','.runtime','.deployment','workspace','node_modules','__pycache__','.git','.pytest_cache','dist','backups'}
def main():
    files=set()
    for directory in DIRS:
        for p in (ROOT/directory).rglob('*'):
            if p.is_file() and not any(part in FORBIDDEN for part in p.relative_to(ROOT).parts) and p.suffix not in {'.pyc','.sqlite3','.log','.dump','.tsbuildinfo'}:
                files.add(p)
    for name in FILES+['deploy/'+p for p in DEPLOY]:
        p=ROOT/name
        if p.is_file():files.add(p)
        else:raise ValueError('Missing source release input: '+name)
    records=[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in sorted(files)]
    assert not any(any(x in FORBIDDEN for x in Path(r['path']).parts) for r in records)
    manifest={'schema':'enterprise-source-release-1','release':json.loads((ROOT/'app/ENTERPRISE.json').read_text(encoding='utf-8')),
              'upstream':json.loads((ROOT/'app/UPSTREAM.json').read_text(encoding='utf-8')),'files':records,
              'private_workspace_included':False,'credentials_included':False,'models_or_dependencies_included':False,'engineering_acceptance':False}
    out=ROOT/'.qa/release';out.mkdir(parents=True,exist_ok=True)
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    with ZipFile(out/'AgentsPLC-Enterprise-source.zip','w',ZIP_DEFLATED) as z:
        for p in sorted(files):z.write(p,p.relative_to(ROOT).as_posix())
        z.write(out/'manifest.json','RELEASE-MANIFEST.json')
    print(json.dumps({'files':len(files),'bytes':(out/'AgentsPLC-Enterprise-source.zip').stat().st_size,'private_data_included':False}))
if __name__=='__main__':main()
