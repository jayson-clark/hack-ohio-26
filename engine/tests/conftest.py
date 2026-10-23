import sys
from pathlib import Path

# Engine modules use flat imports (`from protocol import ...`), as when run from engine/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
