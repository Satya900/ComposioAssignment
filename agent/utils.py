"""
Utility functions for the Composio App Research Agent.

Includes:
- JSON file I/O (load/save with pretty printing)
- Text truncation (token-aware)
- URL extraction and ranking
- Logging setup with Rich
- Progress tracking helpers
"""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Force utf-8 encoding for stdout and stderr on Windows
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

console = Console()


# ─── LOGGING ─────────────────────────────────────────────────────────────────


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None) -> logging.Logger:
    """Set up logging with Rich handler for pretty console output."""
    logger = logging.getLogger("composio-research")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    logger.handlers.clear()

    # Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    rich_handler.setLevel(logging.INFO)
    logger.addHandler(rich_handler)

    # File handler (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
        )
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """Get or create the pipeline logger."""
    logger = logging.getLogger("composio-research")
    if not logger.handlers:
        return setup_logging()
    return logger


# ─── JSON I/O ────────────────────────────────────────────────────────────────


def save_json(data: Any, path: str | Path, indent: int = 2) -> None:
    """Save data to a JSON file with pretty printing and atomic write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first, then rename (atomic)
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            if hasattr(data, "model_dump"):
                # Pydantic model
                json.dump(data.model_dump(mode="json"), f, indent=indent, default=str, ensure_ascii=False)
            elif isinstance(data, list) and data and hasattr(data[0], "model_dump"):
                # List of Pydantic models
                json.dump(
                    [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in data],
                    f, indent=indent, default=str, ensure_ascii=False,
                )
            else:
                json.dump(data, f, indent=indent, default=str, ensure_ascii=False)
        tmp_path.replace(path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    get_logger().debug(f"Saved JSON: {path}")


def load_json(path: str | Path) -> Any:
    """Load data from a JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── TEXT PROCESSING ─────────────────────────────────────────────────────────


def truncate_text(text: str, max_chars: int = 4000) -> str:
    """Truncate text to a maximum number of characters, preserving whole words."""
    if len(text) <= max_chars:
        return text

    # Find the last space before the limit
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.8:
        truncated = truncated[:last_space]

    return truncated + "\n\n[... truncated ...]"


def clean_text(text: str) -> str:
    """Clean scraped text: remove excessive whitespace, normalize line breaks."""
    if not text:
        return ""

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove excessive spaces
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Strip leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


def _as_dict(value) -> Optional[Dict]:
    """Normalize a parsed JSON value to a dict, unwrapping a single-item
    array — some models wrap the classification object in `[...]` even when
    asked for a bare object. Anything else can't be a valid classification."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return None


def extract_json_from_text(text: str) -> Optional[Dict]:
    """
    Extract JSON from LLM response text.
    Handles cases where the LLM wraps JSON in markdown code fences.
    """
    if not text:
        return None

    # Try direct parse first
    try:
        parsed = _as_dict(json.loads(text))
        if parsed is not None:
            return parsed
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if json_match:
        try:
            parsed = _as_dict(json.loads(json_match.group(1)))
            if parsed is not None:
                return parsed
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in the text
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            parsed = _as_dict(json.loads(brace_match.group(0)))
            if parsed is not None:
                return parsed
        except json.JSONDecodeError:
            pass

    # Try finding JSON array in the text
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        try:
            parsed = _as_dict(json.loads(bracket_match.group(0)))
            if parsed is not None:
                return parsed
        except json.JSONDecodeError:
            pass

    return None


# ─── URL HELPERS ─────────────────────────────────────────────────────────────


def generate_docs_urls(website: str) -> List[str]:
    """
    Generate candidate documentation URLs for a given website.
    Tries common patterns where developer docs are typically found.
    """
    # Clean the website
    website = website.strip().rstrip("/")
    if website.startswith("http"):
        # Already a URL, extract domain
        from urllib.parse import urlparse
        parsed = urlparse(website)
        base_domain = parsed.netloc or parsed.path
    else:
        base_domain = website

    # Remove any path components for base domain
    base = base_domain.split("/")[0]

    # Prefer developer/documentation paths.  Starting with a marketing
    # homepage causes the scraper to fill its page quota before it reaches
    # the evidence needed for auth and API classification.
    candidates = [
        f"https://developers.{base}",
        f"https://developer.{base}",
        f"https://docs.{base}",
        f"https://{base}/docs",
        f"https://{base}/developers",
        f"https://{base}/api",
        f"https://{base}/developer",
        f"https://api.{base}",
        f"https://{base}/docs/api",
        f"https://{website}",
    ]

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)

    return unique


def extract_docs_urls(search_results: Any, website: str) -> List[str]:
    """
    Extract and rank documentation URLs from search results.
    Prioritizes URLs that contain docs-related keywords.
    """
    urls = []
    docs_keywords = ["docs", "developer", "api", "reference", "guide", "documentation"]

    if isinstance(search_results, dict):
        # Handle various search result formats
        for key in ["results", "data", "items", "organic"]:
            if key in search_results:
                for item in search_results[key]:
                    url = item.get("url") or item.get("link") or item.get("href", "")
                    if url:
                        urls.append(url)

    elif isinstance(search_results, list):
        for item in search_results:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict):
                url = item.get("url") or item.get("link") or item.get("href", "")
                if url:
                    urls.append(url)

    # Score and rank URLs
    def score_url(url: str) -> int:
        url_lower = url.lower()
        score = 0
        for kw in docs_keywords:
            if kw in url_lower:
                score += 2
        # Boost URLs from the same domain
        if website.lower().split("/")[0] in url_lower:
            score += 3
        return score

    urls.sort(key=score_url, reverse=True)
    return urls[:5]  # Top 5


# ─── PROGRESS BAR ───────────────────────────────────────────────────────────


def create_progress_bar(description: str = "Processing") -> Progress:
    """Create a Rich progress bar for pipeline tracking."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


# ─── TIMESTAMP HELPERS ──────────────────────────────────────────────────────


def now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.utcnow().isoformat() + "Z"


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"
