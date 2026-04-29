# Persistance fichier rotatee (incident 2026-04-27) — survit aux container recreate.
# Le service_name est lu depuis env SERVICE_NAME (default "app").
import logging
try:
    from knowbase.common.logging import setup_root_file_logging
    setup_root_file_logging()
except Exception as _e:
    logging.getLogger(__name__).warning(f"[LOGGING] root file logging setup failed: {_e}")

from knowbase.api import create_app

app = create_app()
