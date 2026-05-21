"""Extract clean text from a manifesto PDF using Claude's native PDF support.

Why this exists: pdftotext mangles multi-column print layouts by reading
row-by-row across columns. The resulting text breaks the verbatim-quote
guard in classify_candidates.py, so stance extraction returns
"not_addressed" for content that's actually clearly stated in the document.
Claude reads PDFs with vision + text and handles column flow correctly.

Cost: ~$0.30-0.60 per ~30-page PDF on Sonnet 4.5. One-time per PDF —
store the extracted text and reuse forever.

Usage:
    python pipeline/extract_pdf_claude.py <pdf_path> [<output_path>]

Or as a library:
    from pipeline.extract_pdf_claude import extract_pdf
    text = extract_pdf("/path/to/manifesto.pdf")

Constraints:
- Anthropic supports PDFs up to 32MB / 100 pages per request.
- Large manifestos may need pagination across multiple calls (not
  implemented here; raise output_tokens or split the PDF if needed).
"""
import argparse
import base64
import os
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

MODEL = "claude-sonnet-4-5"

EXTRACT_PROMPT = """You are extracting the full text of a political manifesto from a PDF for downstream LLM analysis. The PDF has a multi-column print layout; pdftotext mangles it by reading across column boundaries.

Your task: produce a faithful, plain-text transcription of the manifesto's substantive content, in correct reading order.

Rules:
1. Read each column top-to-bottom, then move to the next column. Never read across column boundaries on a single line.
2. Preserve paragraph breaks. Use a single blank line between paragraphs.
3. Preserve bullet lists. Use "- " prefix for each item.
4. Preserve headings on their own line. Use markdown headers (# / ## / ###) by depth.
5. Skip page numbers, repeating headers/footers, repeated copyright lines, and table-of-contents listings — those add noise.
6. Do NOT summarize, paraphrase, or interpret. Transcribe exactly what's printed.
7. Do not add commentary, introductions, or notes — output the manifesto text only.
8. Use UK English as written.

Start with the document title and foreword, then proceed in document order through all substantive sections."""


def extract_pdf(pdf_path: str, max_tokens: int = 16000) -> str:
    """Extract clean text from a PDF via Claude. Returns the transcribed text."""
    with open(pdf_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        },
                    },
                    {"type": "text", "text": EXTRACT_PROMPT},
                ],
            }
        ],
    )
    if resp.stop_reason == "max_tokens":
        print(
            f"WARNING: hit max_tokens ({max_tokens}). Output likely truncated; "
            "consider raising max_tokens or splitting the PDF.",
            file=sys.stderr,
        )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", help="Path to the PDF file to extract")
    parser.add_argument("out_path", nargs="?", help="Output text file (default: <pdf>.txt)")
    parser.add_argument("--max-tokens", type=int, default=16000)
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).resolve()
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}")
    out_path = Path(args.out_path) if args.out_path else pdf_path.with_suffix(".txt")

    print(f"Extracting {pdf_path} ({pdf_path.stat().st_size} bytes) via {MODEL}...")
    text = extract_pdf(str(pdf_path), max_tokens=args.max_tokens)
    words = len(re.findall(r"\w+", text))
    print(f"Got {len(text)} chars, {words} words")
    out_path.write_text(text)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
