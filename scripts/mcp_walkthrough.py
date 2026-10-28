import asyncio
import json

from arena.config import Settings
from arena.walkthrough import walkthrough

if __name__ == "__main__":
    print(
        json.dumps(
            asyncio.run(walkthrough(Settings().data_dir / "mcp-walkthrough")), ensure_ascii=False, indent=2
        )
    )
