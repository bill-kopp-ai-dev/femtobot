"""Centralized magic constants for agent tools."""

from typing import Dict, Tuple

# search
SEARCH_DEFAULT_HEAD_LIMIT = 250
SEARCH_DEFAULT_FILE_HEAD_LIMIT = 200
SEARCH_MAX_RESULT_CHARS = 128_000
SEARCH_MAX_FILE_BYTES = 2_000_000
SEARCH_TYPE_GLOB_MAP: Dict[str, Tuple[str, ...]] = {
    "py": ("*.py", "*.pyi"),
    "python": ("*.py", "*.pyi"),
    "js": ("*.js", "*.jsx", "*.mjs", "*.cjs"),
    "ts": ("*.ts", "*.tsx", "*.mts", "*.cts"),
    "tsx": ("*.tsx",),
    "jsx": ("*.jsx",),
    "json": ("*.json",),
    "md": ("*.md", "*.mdx"),
    "markdown": ("*.md", "*.mdx"),
    "go": ("*.go",),
    "rs": ("*.rs",),
    "rust": ("*.rs",),
    "java": ("*.java",),
    "sh": ("*.sh", "*.bash"),
    "yaml": ("*.yaml", "*.yml"),
    "yml": ("*.yaml", "*.yml"),
    "toml": ("*.toml",),
    "sql": ("*.sql",),
    "html": ("*.html", "*.htm"),
    "css": ("*.css", "*.scss", "*.sass"),
}

# shell
SHELL_MAX_TIMEOUT_S = 600
SHELL_MAX_OUTPUT_CHARS = 10_000

# web
WEB_MAX_REDIRECTS = 5
WEB_DEFAULT_TIMEOUT_S = 15.0
WEB_SHORT_TIMEOUT_S = 10.0
WEB_LONG_TIMEOUT_S = 20.0
WEB_EXTRA_LONG_TIMEOUT_S = 30.0
WEB_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
