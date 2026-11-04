import os
import sys
from pathlib import Path
os.environ["HAYSTACK_TELEMETRY_ENABLED"]="false"
os.environ["DO_NOT_TRACK"]="1"
os.environ["HF_HUB_OFFLINE"]="1"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
