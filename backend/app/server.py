import logging

import uvicorn

from .config import load_settings
from .main import create_app


def main():
    settings = load_settings()
    logging.basicConfig(level=settings.log_level, format='%(message)s')
    uvicorn.run(create_app(settings), host=settings.backend_host, port=settings.backend_port,
                workers=1, access_log=False, log_level=settings.log_level.lower())


if __name__ == '__main__':
    main()
