"""Prepare local Compose secret files without printing credentials."""
from pathlib import Path
import secrets
from local_postgres import protect
root=Path(__file__).resolve().parents[1]/'.deployment';root.mkdir(exist_ok=True);protect(root)
for name in ['postgres-password','app-password','model-key']:
    path=root/name
    if not path.exists():path.write_text('' if name=='model-key' else secrets.token_urlsafe(36),encoding='utf-8');path.chmod(0o600)
print('Compose secret files prepared in .deployment; model key is empty until explicitly configured')
