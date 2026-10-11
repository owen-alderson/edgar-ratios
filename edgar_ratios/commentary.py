"""Optional analyst commentary from Claude, written only from the computed ratios and checked against them."""

import re
from dataclasses import dataclass

import anthropic

from .ratios import Analysis
from .render import fmt_value

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are a financial analyst writing a short read-out of a company's ratios for a reader \
who knows the basics of accounting but not this company.

Write 150-220 words of plain prose, no headings or bullet points:
1. The two or three findings that matter most: strengths, concerns, and how they moved across the years.
2. The leverage and liquidity picture.
3. One question you would put to management.
When there are several companies, compare them instead of describing each in turn.

Use only the numbers given to you, written exactly as they appear (same rounding and units), and say \
which fiscal year each refers to. Do not calculate new numbers such as differences or averages. Skip \
ratios marked n/a. Companies' fiscal years end on different dates, so say "latest fiscal year" rather \
than implying the periods line up. This is analysis, not investment advice: no buy or sell views."""


class CommentaryError(Exception):
    pass


@dataclass
class Commentary:
    text: str
    unverified: list[str]


def build_prompt(analyses: list[Analysis]) -> str:
    lines = []
    for a in analyses:
        lines.append(f"{a.company.name} ({a.company.ticker})")
        for yr in a.years:
            shown = [f"{v.ratio.name} {fmt_value(v)}" for v in yr.values if v.value is not None]
            lines.append(f"  {yr.year.label} (ended {yr.year.end}): " + "; ".join(shown))
        lines.append("")
    return "Ratios computed from SEC 10-K filings:\n\n" + "\n".join(lines)


_NUMBER = re.compile(r"(?<![\w.])(-?\d+(?:,\d{3})*(?:\.\d+)?)(\s*(?:%|x\b|×|days?\b))?")


def unverified_numbers(text: str, analyses: list[Analysis]) -> list[str]:
    """Numbers in the commentary that don't match any computed ratio at the precision they're written in.

    Fiscal years and small counts ("two of three years") are ignored; everything with a unit or a
    decimal point must trace back to the table.
    """
    known = [v.value for a in analyses for yr in a.years for v in yr.values if v.value is not None]
    flagged = []
    for match in _NUMBER.finditer(text):
        raw, unit = match.group(1), (match.group(2) or "").strip()
        number = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if not unit and decimals == 0:
            continue  # years, counts
        tolerance = 0.5 * 10 ** -decimals + 1e-9
        if not any(abs(number - k) <= tolerance for k in known):
            flagged.append(match.group(0).strip())
    return list(dict.fromkeys(flagged))


class Commentator:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self._client, self.model = client, model

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def write(self, analyses: list[Analysis]) -> Commentary:
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(analyses)}],
                output_config={"effort": "medium"},
                # On a policy decline the API re-runs the request on a fallback model in the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as e:
            raise CommentaryError("Anthropic API key missing or invalid (set ANTHROPIC_API_KEY, "
                                  "or put it in ~/.edgar-ratios/.env).") from e
        except anthropic.RateLimitError as e:
            raise CommentaryError("Rate limited by the Anthropic API; try again in a minute.") from e
        except anthropic.APIStatusError as e:
            raise CommentaryError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise CommentaryError("Could not reach the Anthropic API.") from e

        if response.stop_reason == "refusal":
            raise CommentaryError("Claude declined to write commentary for these figures.")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "max_tokens" or not text:
            raise CommentaryError("Claude's commentary came back empty or cut off; try again.")
        return Commentary(text, unverified_numbers(text, analyses))
