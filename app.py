#!/usr/bin/env python3
"""Development entrypoint for the novel writing application."""

import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

from novel_app import create_app


app = create_app()
app_config = app.extensions["novel_config"]["app_config"]


if __name__ == "__main__":
    app.run(
        host=app_config["host"],
        port=int(app_config["port"]),
        debug=bool(app_config["debug"]),
    )
