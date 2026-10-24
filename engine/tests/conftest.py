import os
import sys
from pathlib import Path

# Engine modules use flat imports (`from protocol import ...`), as when run from engine/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# `make test` exports the root .env; a CAMERA there would have every test
# engine open the real webcam (and hang on it). Tests use the virtual table.
os.environ.pop("CAMERA", None)
