"""RunPod Serverless worker entry point."""

from typing import Any

import runpod


def handler(job: dict[str, Any]) -> dict[str, str]:
    """Handle one serverless job.

    The job payload is intentionally unused because this minimal worker always
    returns the same response.
    """
    del job
    return {"message": "Hello World"}


if __name__ == "__main__":
    # Start RunPod's event loop only when this module is executed directly.
    runpod.serverless.start({"handler": handler})
