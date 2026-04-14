import anthropic
import os
from pathlib import Path
from ratios import RatioResult, format_value, CATEGORIES


def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


SYSTEM_PROMPT = """You are a sharp investment analyst reviewing a company's financial ratios.

Write a concise analysis (150–200 words) covering:
1. The 2–3 most notable findings — strengths or concerns
2. What the leverage and liquidity picture looks like
3. One specific question you'd want answered in a management meeting

Tone: direct, analytical, no hedging. Write like you're presenting to a PE partner.
Do not restate every ratio — synthesize. Reference specific numbers.
Skip N/A ratios entirely.
"""


def get_commentary(company_name: str, results: list[RatioResult]) -> str:
    lines = [f"Company: {company_name or 'Unknown'}\n"]
    for cat in CATEGORIES:
        cat_results = [r for r in results if r.category == cat and r.value is not None]
        if not cat_results:
            continue
        lines.append(f"{cat}:")
        for r in cat_results:
            lines.append(f"  {r.name}: {format_value(r)}")
        lines.append("")

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(lines)}],
    )
    return message.content[0].text
