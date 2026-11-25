"""把 backend 目录加入 sys.path，保证 `import app...` 在任意 rootdir 下可导入。"""

import sys
from pathlib import Path

_根 = Path(__file__).resolve().parent
if str(_根) not in sys.path:
    sys.path.insert(0, str(_根))
