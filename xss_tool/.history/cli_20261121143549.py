# cli.py
import argparse
import json
import logging
import sys

from .session import create_session
from .orchestrator import XSSScanner
from .oast import SimpleOAST

def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url")
    src.add_argument("--urls-file")
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--fuzzdb")
    ap.add_argument("--no-dom", action="store_true")
    ap.add_argument("--no-blind", action="store_true")
    ap.add_argument("--oast-url")
    ap.add_argument("--oast-port", type=int, default=8888)
    ap.add_argument("--cookies")
    ap.add_argument("--output")
    args = ap.parse_args()

    session = create_session(args.cookies)

    if args.urls_file:
        with open(args.urls_file) as f:
            urls = [l.strip() for l in f if l.strip()]
    else:
        from .crawler import crawl
        urls = crawl(args.url, args.depth, session)

    oast = None
    if args.oast_url and not args.no_blind:
        oast = SimpleOAST(args.oast_url, args.oast_port)
        oast.start()

    scanner = XSSScanner(
        urls=urls, session=session, oast_client=oast,
        fuzzdb_path=args.fuzzdb, delay=args.delay,
        enable_dom=not args.no_dom, enable_blind=not args.no_blind,
    )
    findings = scanner.run()

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([x.to_dict() for x in findings], f, indent=2, ensure_ascii=False)

    return 0 if not findings else 1

if __name__ == "__main__":
    sys.exit(main())