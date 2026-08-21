#!/usr/bin/env python3
"""Convert a LaTeX cookbook (using recipePMG.cls) to HTML via pandoc.

Preprocesses custom commands into standard LaTeX, then invokes pandoc.

Usage:
    python convert.py NewCookbook.tex output.html
"""

import datetime
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Fraction command -> Unicode replacement
FRACTION_MAP = {
    r"\half": "½",
    r"\quarter": "¼",
    r"\third": "⅓",
    r"\twothirds": "⅔",
    r"\threequarters": "¾",
    r"\eighth": "⅛",
    r"\threeeights": "⅜",
    r"\fiveeights": "⅝",
    r"\seveneights": "⅞",
    r"\sixth": "⅙",
    r"\sixteenth": "¹⁄₁₆",
    r"\threesixteenths": "³⁄₁₆",
    r"\threehalves": "1½",
}


def expand_fractions(text: str) -> str:
    """Replace custom fraction commands with Unicode characters."""
    for cmd, char in FRACTION_MAP.items():
        # Match the command optionally followed by \, (thin space) and
        # word-boundary-ish context (space, digit, letter, brace, etc.)
        pattern = re.escape(cmd) + r"(?:\s*\\,)?"
        text = re.sub(pattern, char, text)
    return text


def parse_ingredients_body(body: str) -> str:
    """Convert the body of an \\ingredients{...} command into LaTeX itemize lists.

    Handles:
    - Items separated by ; or ending with .
    - Multi-section ingredients with \\\\ and \\textsc{Section --} headers
    """
    # Split on \\ (LaTeX line breaks) to find sections
    # The pattern: two or more backslashes used as line breaks
    segments = re.split(r"\\\\", body)

    output_parts = []
    current_items = []

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        # Check if this segment starts with a \textsc{...} section header
        textsc_match = re.match(r"\\textsc\s*\{", segment)
        if textsc_match:
            brace_pos = textsc_match.end() - 1
            header_body, close_pos = extract_braced(segment, brace_pos)
            if header_body is not None:
                # Flush any pending items
                if current_items:
                    output_parts.append(items_to_itemize(current_items))
                    current_items = []
                header_text = header_body.strip().rstrip(" -\u2013")
                output_parts.append(f"\\textbf{{{header_text}}}\n\n")
                remainder = segment[close_pos + 1 :].strip()
                if remainder:
                    current_items.extend(split_items(remainder))
        else:
            current_items.extend(split_items(segment))

    if current_items:
        output_parts.append(items_to_itemize(current_items))

    return "".join(output_parts)


def split_items(text: str) -> list[str]:
    """Split ingredient text on ; or terminal . into individual items."""
    # Split on semicolons
    parts = re.split(r";", text)
    items = []
    for part in parts:
        part = part.strip().rstrip(".")
        if part:
            items.append(part)
    return items


def items_to_itemize(items: list[str]) -> str:
    """Convert a list of ingredient strings to a LaTeX itemize block."""
    if not items:
        return ""
    lines = ["\\begin{itemize}"]
    for item in items:
        lines.append(f"\\item {item}")
    lines.append("\\end{itemize}\n")
    return "\n".join(lines)


def expand_ingredients(text: str) -> str:
    """Find and expand \\ingredients{...} commands."""
    return _expand_braced_command(
        text, r"\ingredients", "Ingredients"
    )


def expand_equipment(text: str) -> str:
    """Find and expand \\equilpment{...} commands."""
    return _expand_braced_command(
        text, r"\equilpment", "Equipment"
    )


def _expand_braced_command(
    text: str, command: str, heading: str
) -> str:
    """Generic expander for \\command{body} patterns with balanced braces."""
    cmd_escaped = re.escape(command)
    result = []
    i = 0
    while i < len(text):
        match = re.search(cmd_escaped + r"\s*\{", text[i:])
        if not match:
            result.append(text[i:])
            break
        # Append everything before the command
        result.append(text[i : i + match.start()])
        # Find the matching closing brace
        brace_start = i + match.end() - 1  # position of the opening {
        body, end_pos = extract_braced(text, brace_start)
        if body is None:
            # Couldn't find matching brace, leave as-is
            result.append(text[i + match.start() : i + match.end()])
            i = i + match.end()
            continue
        # Build replacement
        parsed = parse_ingredients_body(body)
        replacement = f"\\textbf{{{heading}:}}\n\n{parsed}"
        result.append(replacement)
        i = end_pos + 1  # skip past closing brace
    return "".join(result)


def extract_braced(text: str, pos: int) -> tuple[str | None, int]:
    """Extract content between balanced braces starting at pos (which should be '{').

    Returns (body, end_position) where end_position is the index of the closing '}'.
    Returns (None, -1) if braces are unbalanced.
    """
    if pos >= len(text) or text[pos] != "{":
        return None, -1
    depth = 0
    start = pos + 1
    i = pos
    while i < len(text):
        if text[i] == "{" and (i == 0 or text[i - 1] != "\\"):
            depth += 1
        elif text[i] == "}" and (i == 0 or text[i - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return text[start:i], i
        i += 1
    return None, -1


def expand_today(text: str) -> str:
    r"""Replace \today with a long-form date, e.g. "August 20, 2026"."""
    today = datetime.date.today()
    formatted = f"{today:%B} {today.day}, {today.year}"
    return re.sub(r"\\today\b", formatted, text)


def expand_recipe(text: str) -> str:
    r"""Replace \recipe{X} with \subsection*{X}."""
    return re.sub(
        r"\\recipe\{",
        r"\\subsection*{",
        text,
    )


def preprocess(text: str) -> str:
    """Apply all preprocessing transformations to the LaTeX source."""
    # Replace document class
    text = re.sub(
        r"\\documentclass\[.*?\]\{recipePMG\}",
        r"\\documentclass{book}",
        text,
    )

    # Remove \bsi command definitions and usages
    # Remove the \newcommand definition
    text = re.sub(
        r"\\newcommand\{\\bsi\}\[2\]\{[^}]*\{[^}]*\}[^}]*\}",
        "",
        text,
    )
    # Remove \bsi{...}{...} usages
    text = re.sub(r"\\bsi\{[^}]*\}\{[^}]*\}", "", text)

    # Remove \rechead, \inghead, \equhead renewcommands (handled by preprocessing)
    text = re.sub(
        r"\\renewcommand\{\\rechead\}\{[^}]*(?:\{[^}]*\}[^}]*)?\}",
        "",
        text,
    )
    text = re.sub(r"\\renewcommand\{\\inghead\}\{[^}]*\}", "", text)
    text = re.sub(r"\\renewcommand\{\\equhead\}\{[^}]*\}", "", text)

    # Remove fraction command definitions (they're being replaced with Unicode)
    text = re.sub(
        r"\\newcommand\{\\(?:half|quarter|third|twothirds|threequarters|"
        r"eighth|threeeights|fiveeights|seveneights|sixth|sixteenth|"
        r"threesixteenths|threehalves)\}\{[^}]*\}",
        "",
        text,
    )

    # Remove \HRule definitions and usages
    text = re.sub(r"\\newcommand\{\\HRule\}\[1\]\{[^}]*\}", "", text)
    text = re.sub(r"\\HRule\{[^}]*\}", "", text)

    # Remove \deg renewcommand definition
    text = re.sub(r"\\renewcommand\{\\deg\}\{[^}]*\}", "", text)

    # Replace \deg with degree symbol
    text = re.sub(r"\\deg\b", "°", text)

    # Replace \today with a long-form date
    text = expand_today(text)

    # Expand fraction commands (before other expansions since they appear inside
    # \ingredients bodies)
    text = expand_fractions(text)

    # Expand \recipe, \ingredients, \equilpment
    text = expand_recipe(text)
    text = expand_ingredients(text)
    text = expand_equipment(text)

    # Remove \newpage
    text = re.sub(r"\\newpage\b", "", text)

    # Remove \hyperref[TOC]{Table of Contents} links
    text = re.sub(r"\\hyperref\[TOC\]\{Table of Contents\}", "", text)

    # Remove all \makeatletter ... \makeatother blocks (contain internal LaTeX
    # redefinitions that pandoc doesn't need: \l@subsubsection, \printtitle, etc.)
    text = re.sub(
        r"\\makeatletter\b.*?\\makeatother\b",
        "",
        text,
        flags=re.DOTALL,
    )

    # Remove \printtitle and \printauthor invocations
    text = re.sub(r"\\printtitle\b", "", text)
    text = re.sub(r"\\printauthor\b", "", text)

    # Remove \thispagestyle{empty}
    text = re.sub(r"\\thispagestyle\{empty\}", "", text)

    # Remove \vfill
    text = re.sub(r"\\vfill\b", "", text)

    # Clean up the conditional hyperref loading - replace with simple version
    text = re.sub(
        r"\\ifdefined\\HCode.*?\\fi\s",
        r"\\usepackage[colorlinks=true,linkcolor=blue]{hyperref}" + "\n",
        text,
        flags=re.DOTALL,
    )

    # Remove multiple consecutive blank lines (cleanup)
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text


def convert(input_path: str, output_path: str) -> None:
    """Preprocess a LaTeX file and convert to HTML via pandoc."""
    source = Path(input_path).read_text(encoding="utf-8")
    processed = preprocess(source)

    # Inject macros.tex content into the preamble if it exists
    macros_path = Path(__file__).parent / "macros.tex"
    if macros_path.exists():
        macros_content = macros_path.read_text(encoding="utf-8")
        # Insert macros just before \begin{document}
        processed = processed.replace(
            r"\begin{document}",
            macros_content + "\n" + r"\begin{document}",
        )

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".tex",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(processed)
        tmp_path = tmp.name

    try:
        cmd = [
            "pandoc",
            tmp_path,
            "-f",
            "latex",
            "-t",
            "html5",
            "--standalone",
            "--toc",
            "--css=style.css",
        ]

        # Inject the floating "back to contents" button, if present
        toc_button_path = Path(__file__).parent / "toc-button.html"
        if toc_button_path.exists():
            cmd.append(f"--include-after-body={toc_button_path}")

        cmd += ["-o", output_path]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"pandoc error:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)
        if result.stderr:
            print(f"pandoc warnings:\n{result.stderr}", file=sys.stderr)
        print(f"Converted {input_path} -> {output_path}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python convert.py input.tex output.html")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
