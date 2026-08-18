"""Live entry point — initialise services and start the server."""

from dotenv import load_dotenv

from Live.Server import main as serve
from SharedParams.Config import load

load_dotenv()


def main() -> None:
    config = load()
    serve(config)


if __name__ == "__main__":
    main()
