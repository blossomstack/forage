import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "forage.app:app",
        host=os.environ.get("FORAGE_HOST", "0.0.0.0"),  # noqa: S104 - it runs in a container
        port=int(os.environ.get("FORAGE_PORT", 8080)),
        log_level=os.environ.get("FORAGE_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
