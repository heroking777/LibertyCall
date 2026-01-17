"""pytest設定ファイル."""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from console_backend.database import Base, engine
    import console_backend.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
except Exception:
    # Allow tests that don't need the DB to proceed even if setup fails.
    pass

