import os
import sys

INSTANCE = os.getenv("PWN_COLLEGE_INSTANCE")
HOST_DATA_PATH = os.getenv("HOST_DATA_PATH")
BINARY_NINJA_API_KEY = os.getenv("BINARY_NINJA_API_KEY")

if not INSTANCE:
    raise RuntimeError(
        "Configuration Error: PWN_COLLEGE_INSTANCE must be set in the environment"
    )

if not HOST_DATA_PATH:
    raise RuntimeError(
        "Configuration Error: HOST_DATA_PATH must be set in the environment"
    )

if not BINARY_NINJA_API_KEY:
    print(
        "Configuration Warning: BINARY_NINJA_API_KEY is not set in the environment",
        file=sys.stderr,
    )
