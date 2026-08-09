"""
Code Hallucination Checker
---------------------------
Checks a single code file (or every code file in a folder) using the Gemini
API to detect "hallucinated" code: fabricated imports, non-existent
functions/methods, wrong signatures, made-up API endpoints/config keys, etc.

Reports, per file:
  - hallucination_percent  (0-100, how much of the file is affected)
  - a list of specific issues found
  - a corrected version of the file (written to an output folder)

Auth: uses a plain Gemini API key (no GCP project/ADC needed).
Get a key at https://aistudio.google.com/apikey and set it as an
environment variable before running:

    Windows (cmd):        set GEMINI_API_KEY=your_key_here
    Windows (PowerShell):  $env:GEMINI_API_KEY="your_key_here"
    macOS/Linux:           export GEMINI_API_KEY=your_key_here

Usage:
    python hallucination_checker.py path\\to\\file.py
    python hallucination_checker.py path\\to\\folder --output fixed --report report.json
"""

import os
import re
import json
import argparse
from pathlib import Path

from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Config - uses a plain Gemini API key (from Google AI Studio), not GCP/ADC
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GENAI_MODEL", "gemini-3.5-flash-lite")

CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb",
    ".cpp", ".c", ".h", ".cs", ".php", ".rs", ".kt", ".swift",
}

# Folders never worth scanning: dependencies, vendored code, VCS, caches.
EXCLUDED_DIR_NAMES = {
    "venv", ".venv", "env", ".env", "site-packages",
    "node_modules", ".git", ".hg", ".svn",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".tox",
    "dist", "build", ".idea", ".vscode", "corrected_output",
}

SYSTEM_INSTRUCTION = """You are a meticulous code reviewer whose ONLY job is to detect
"hallucinations" in code: things that look plausible but are actually wrong. Examples:
- imports of packages/modules that don't exist, or aren't the real package name
- calls to functions/methods/classes that don't exist in the library being used
- wrong function signatures (wrong arg names, wrong number/order of args, wrong return type usage)
- fabricated API endpoints, config keys, or environment variable names
- confidently wrong logic that relies on non-existent language features

Do NOT flag legitimate custom/user-defined code, project-specific helper functions,
reasonable style choices, or things you are merely unsure about. Only flag things
you are confident are factually incorrect for the language/library/framework in use.

Respond with STRICT JSON only. No markdown fences, no prose outside the JSON.
Schema:
{
  "hallucination_percent": <integer 0-100, how much of the file's substantive
     content is affected by hallucinated/incorrect code>,
  "issues": [
    {
      "line_hint": "<short quote or approximate line number>",
      "problem": "<what is wrong>",
      "confidence": "<low|medium|high>"
    }
  ],
  "corrected_code": "<the FULL corrected file content with hallucinations fixed;
     if there are no issues, return the original code unchanged>"
}
"""


def get_client():
    if not API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a key from https://aistudio.google.com/apikey "
            "and set it, e.g.:\n  set GEMINI_API_KEY=your_key_here   (Windows cmd)\n"
            "  $env:GEMINI_API_KEY=\"your_key_here\"   (PowerShell)"
        )
    return genai.Client(api_key=API_KEY)


def _is_excluded(path, root):
    """True if any parent directory (relative to root) is in EXCLUDED_DIR_NAMES."""
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts
    return any(part in EXCLUDED_DIR_NAMES for part in rel_parts)


def find_code_files(folder, extra_excludes=None):
    """Return a list of code files under `folder` (or [folder] if it's a single file)."""
    path = Path(folder)
    if path.is_file():
        return [path]

    excluded = set(EXCLUDED_DIR_NAMES) | set(extra_excludes or [])
    files = []
    for p in path.rglob("*"):
        if not p.is_file() or p.suffix not in CODE_EXTENSIONS:
            continue
        rel_parts = p.relative_to(path).parts
        if any(part in excluded for part in rel_parts):
            continue
        files.append(p)
    return sorted(files)


def _strip_code_fences(text):
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def analyze_file(client, filepath):
    code = filepath.read_text(encoding="utf-8", errors="ignore")
    prompt = f"Filename: {filepath.name}\n\nCode to analyze:\n```\n{code}\n```"

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.0,
            max_output_tokens=8192,
            response_mime_type="application/json",
        ),
    )

    raw = _strip_code_fences(response.text or "")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {
            "hallucination_percent": None,
            "issues": [{
                "line_hint": "N/A",
                "problem": "Model response could not be parsed as JSON",
                "confidence": "low",
            }],
            "corrected_code": code,
        }

    data.setdefault("hallucination_percent", None)
    data.setdefault("issues", [])
    data.setdefault("corrected_code", code)
    return data


def write_corrected_file(original_path, folder_root, output_root, corrected_code):
    folder_root = Path(folder_root)
    if folder_root.is_file():
        # single-file mode: just drop the corrected file directly in output_root
        out_path = Path(output_root) / original_path.name
    else:
        rel = original_path.relative_to(folder_root)
        out_path = Path(output_root) / rel

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(corrected_code, encoding="utf-8")
    return out_path


def get_recommendation(hallucination_percent):
    if hallucination_percent is None:
        return "recheck"
    if hallucination_percent <= 10:
        return "pass"
    if hallucination_percent <= 30:
        return "recheck"
    return "do_not_pass"


def scan(folder, output_root="corrected_output", extra_excludes=None):
    client = get_client()
    files = find_code_files(folder, extra_excludes=extra_excludes)

    if not files:
        print(f"No code files found in {folder}")
        return []

    results = []
    for f in files:
        print(f"Analyzing {f} ...")
        try:
            data = analyze_file(client, f)
        except Exception as e:
            print(f"  ERROR analyzing {f}: {e}")
            results.append({
                "file": str(f),
                "hallucination_percent": None,
                "num_issues": 0,
                "issues": [{"line_hint": "N/A", "problem": f"Analysis failed: {e}", "confidence": "low"}],
                "corrected_path": None,
                "recommendation": "recheck",
            })
            continue

        pct = data["hallucination_percent"]
        issues = data["issues"]
        corrected = data["corrected_code"]

        out_path = write_corrected_file(f, folder, output_root, corrected) if corrected else None

        recommendation = get_recommendation(pct)
        results.append({
            "file": str(f),
            "hallucination_percent": pct,
            "num_issues": len(issues),
            "issues": issues,
            "corrected_path": str(out_path) if out_path else None,
            "recommendation": recommendation,
        })

        pct_str = f"{pct}%" if pct is not None else "N/A"
        print(f"  -> hallucination: {pct_str} | issues: {len(issues)} | recommendation: {recommendation} | corrected saved to: {out_path}")

    return results


def print_summary(results):
    print("\n" + "=" * 60)
    print("HALLUCINATION CHECK SUMMARY")
    print("=" * 60)

    for r in results:
        pct = r["hallucination_percent"]
        pct_str = f"{pct}%" if pct is not None else "N/A"
        recommendation = r.get("recommendation", "recheck")
        print(f"- {r['file']}: {pct_str} hallucination, {r['num_issues']} issue(s), recommendation: {recommendation}")
        for issue in r["issues"]:
            conf = issue.get("confidence", "?")
            problem = issue.get("problem", "")
            hint = issue.get("line_hint", "")
            print(f"    [{conf}] {problem}  ({hint})")

    valid = [r["hallucination_percent"] for r in results if isinstance(r["hallucination_percent"], (int, float))]
    if valid:
        avg = sum(valid) / len(valid)
        print(f"\nAverage hallucination across {len(valid)} file(s): {avg:.1f}%")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Detect hallucinated code in a single file or a folder.")
    parser.add_argument("path", help="Path to a single code file (or a folder to scan multiple files)")
    parser.add_argument("--output", default="corrected_output", help="Folder to write corrected files to")
    parser.add_argument("--report", default="hallucination_report.json", help="Path to save the JSON report")
    parser.add_argument(
        "--exclude", nargs="*", default=[],
        help="Extra directory names to skip, e.g. --exclude migrations tests",
    )
    args = parser.parse_args()

    results = scan(args.path, args.output, extra_excludes=args.exclude)
    print_summary(results)

    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull report saved to {args.report}")


if __name__ == "__main__":
    main()