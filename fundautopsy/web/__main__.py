"""Launch Fund Autopsy dashboard: python -m fundautopsy.web"""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("FUNDAUTOPSY_PORT", "8000"))
    reload = os.environ.get("FUNDAUTOPSY_RELOAD", "").lower() in ("1", "true", "yes")
    print(f"\n  Fund Autopsy Dashboard — http://localhost:{port}\n")
    uvicorn.run("fundautopsy.web.app:app", host="0.0.0.0", port=port, reload=reload)
