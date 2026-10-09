import logging

import uvicorn

from .config import load_settings
from .main import create_app


def build_server(settings):
    logging.basicConfig(level=settings.log_level, format='%(message)s')
    config = uvicorn.Config(create_app(settings), host=settings.backend_host, port=settings.backend_port,
                            workers=1, timeout_graceful_shutdown=5, access_log=False, log_level=settings.log_level.lower())
    return uvicorn.Server(config)


def main():
    build_server(load_settings()).run()


if __name__ == '__main__':
    main()
