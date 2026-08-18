"""Live entry point — initialise services and start the server."""
import os
from dotenv import load_dotenv

load_dotenv()

from SharedParams.Config import load
from Live.Server import main as serve


def main() -> None:
    config = load()
    serve(config)


if __name__ == "__main__":
    main()
