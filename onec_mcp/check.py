"""Проверка подключения к 1С без Claude: python -m onec_mcp.check"""

import json

from onec_mcp.server import check_connection

if __name__ == "__main__":
    print(json.dumps(check_connection(), ensure_ascii=False, indent=2))
