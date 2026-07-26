"""Milestone 1 – verify OpenRouter connectivity with GPT OSS."""

from __future__ import annotations

import time

from openai import OpenAI

from src.config import get_settings, reload_settings

MAX_ATTEMPTS = 3


def main() -> None:
    """Call OpenRouter with the research model and print a Hello World check."""
    reload_settings()
    settings = get_settings().llm
    api_key = settings.require_api_key()
    model = settings.research_model

    client = OpenAI(api_key=api_key, base_url=settings.base_url)
    text = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with the words Hello World only.",
                }
            ],
            temperature=0,
            max_tokens=128,
        )
        text = (completion.choices[0].message.content or "").strip()
        if "Hello World" in text:
            break
        if attempt < MAX_ATTEMPTS:
            time.sleep(1.5)

    print("Model: GPT OSS")
    print(text or "(empty response)")

    if "Hello World" not in text:
        raise SystemExit(
            f"Milestone 1 failed after {MAX_ATTEMPTS} attempts: {text!r}"
        )

    print("Success")


if __name__ == "__main__":
    main()
