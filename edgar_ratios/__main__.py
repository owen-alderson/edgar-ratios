"""edgar-ratios AAPL [MSFT ...]: financial ratios from SEC filings, every input traceable to its filing."""

import argparse
import sys
from datetime import date
from pathlib import Path

from rich.console import Console

from . import __version__, config
from .ratios import Price, analyze
from .sec import Sec, SecError

EPILOG = """examples:
  edgar-ratios AAPL                      five fiscal years of ratios
  edgar-ratios AAPL --price 227.50       add valuation ratios at your price
  edgar-ratios AAPL MSFT NVDA            compare the latest fiscal year side by side
  edgar-ratios AAPL MSFT --price AAPL=227.50 --price MSFT=510
  edgar-ratios AAPL --sources            show the XBRL concept and filing behind every input
  edgar-ratios AAPL --html aapl.html     self-contained report with links to each filing
  edgar-ratios AAPL --format json        everything, with provenance, for scripts
"""


class UsageError(Exception):
    pass


def parse_prices(raw: list[str], tickers: list[str], today: date) -> dict[str, Price]:
    """`--price 227.5` for a single ticker, or `--price AAPL=227.5` per ticker."""
    prices: dict[str, Price] = {}
    for item in raw:
        ticker, sep, value = item.rpartition("=")
        if not sep:
            if len(tickers) != 1:
                raise UsageError("With several tickers, give each price as TICKER=PRICE (e.g. --price AAPL=227.50).")
            ticker = tickers[0]
        ticker = ticker.strip().upper()
        if ticker not in tickers:
            raise UsageError(f"--price names {ticker}, which isn't one of the tickers asked for.")
        try:
            number = float(value.replace(",", "").lstrip("$"))
        except ValueError:
            raise UsageError(f"Not a price: {value!r}.") from None
        if number <= 0:
            raise UsageError(f"Price must be positive (got {value}).")
        prices[ticker] = Price(number, today)
    return prices


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="edgar-ratios",
        description="Financial ratios from SEC EDGAR filings. Every input is traced to the 10-K it came from; "
                    "anything that can't be found is shown as n/a with the reason, never guessed.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("tickers", nargs="*", metavar="TICKER", help="one ticker for its history, several to compare")
    p.add_argument("--years", type=int, default=5, help="fiscal years to show for one ticker (default 5)")
    p.add_argument("--price", action="append", default=[], metavar="[TICKER=]PRICE",
                   help="share price for the valuation ratios (SEC filings contain no prices)")
    p.add_argument("--format", choices=["table", "json", "csv"], default="table", help="output format (default table)")
    p.add_argument("--html", type=Path, metavar="FILE", help="also write a self-contained HTML report")
    p.add_argument("--sources", action="store_true", help="show where every input figure came from")
    p.add_argument("--commentary", action="store_true", help="add a short read-out written by Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--refresh", action="store_true", help="ignore the local cache and refetch from the SEC")
    p.add_argument("--set-user-agent", metavar='"NAME EMAIL"', help="save the name and email sent to the SEC, then exit")
    p.add_argument("--version", action="version", version=f"edgar-ratios {__version__}")
    return p


def main(argv: list[str] | None = None, sec: Sec | None = None, console: Console | None = None,
         commentator=None, today: date | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = console or Console()
    err = Console(stderr=True)
    try:
        if args.set_user_agent:
            config.save_user_agent(args.set_user_agent)
            console.print(f"Saved. Requests to the SEC will identify as: {args.set_user_agent.strip()}")
            return 0
        if not args.tickers:
            raise UsageError("Give at least one ticker, e.g. edgar-ratios AAPL")
        if args.years < 1:
            raise UsageError("--years must be at least 1.")
        tickers = list(dict.fromkeys(t.strip().upper() for t in args.tickers))
        prices = parse_prices(args.price, tickers, today or date.today())
        if sec is None:
            sec = Sec(config.user_agent(), config.cache_dir(), refresh=args.refresh)
        years = args.years if len(tickers) == 1 else 1
        analyses = [analyze(sec, t, years=years, price=prices.get(t)) for t in tickers]

        commentary = None
        if args.commentary:
            config.load_env()
            from .commentary import Commentator, CommentaryError

            try:
                commentary = (commentator or Commentator()).write(analyses)
            except CommentaryError as e:
                err.print(f"[red]error:[/red] {e}")
                return 1

        if args.format == "json":
            from .export import to_json

            sys.stdout.write(to_json(analyses) + "\n")
        elif args.format == "csv":
            from .export import to_csv

            sys.stdout.write(to_csv(analyses))
        else:
            from .render import print_all

            print_all(analyses, args.sources, console)
            if commentary:
                _print_commentary(console, commentary)
        if args.html:
            from .report import to_html

            args.html.write_text(to_html(analyses, commentary.text if commentary else None))
            err.print(f"Wrote {args.html}")
        return 0
    except (UsageError, config.ConfigError, SecError) as e:
        err.print(f"[red]error:[/red] {e}")
        return 2 if isinstance(e, UsageError) else 1


def _print_commentary(console: Console, commentary) -> None:
    console.print("[bold]Commentary[/bold] [dim](Claude, from the numbers above)[/dim]")
    console.print(commentary.text)
    if commentary.unverified:
        console.print(f"[yellow]Not in the table above, check before relying on them:[/yellow] "
                      f"{', '.join(commentary.unverified)}")
    console.print()


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
