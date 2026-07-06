"""Local JSON-file caching layer for parsed SEC filing data.

Caches raw XML bytes from EDGAR to avoid redundant HTTP requests.
SEC filings are immutable once filed, so cached data never goes stale
for a given (CIK, accession_number) pair. We use a simple file-based
cache keyed by CIK and accession number.

Cache structure:
    ~/.fundautopsy/cache/
        xml/
            {cik}/{accession_no_dashes}.xml

TTL is configurable but defaults are generous since filings don't change:
    - N-CEN: 365 days (annual filing)
    - N-PORT: 90 days (quarterly, but we cache by accession so effectively infinite)
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default cache location
DEFAULT_CACHE_DIR: Path = Path.home() / ".fundautopsy" / "cache"


MAX_CACHE_SIZE_BYTES: int = 1_000_000_000  # 1 GB


class FilingCache:
    """File-based cache for raw EDGAR XML filings.

    Caches raw XML bytes keyed by (CIK, accession_number). Since filings
    are immutable once filed, cached data is valid indefinitely. A TTL
    is provided as a safety valve but defaults to 365 days.

    When total cache size exceeds MAX_CACHE_SIZE_BYTES, oldest entries
    (by modification time) are evicted.

    Args:
        cache_dir: Root directory for cache storage. Defaults to
            ~/.fundautopsy/cache/
        enabled: Set to False to disable caching (all lookups return None).
    """

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        enabled: bool = True,
    ) -> None:
        self.cache_dir = cache_dir
        self.enabled = enabled
        self._xml_dir = cache_dir / "xml"
        if enabled:
            self._xml_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, cik: int, accession_number: str, document: str) -> Path:
        """Build the filesystem path for a cached filing.

        Sanitizes inputs to prevent path traversal — only the filename
        component of `document` is used, and accession dashes are stripped.
        """
        safe_acc = accession_number.replace("-", "")
        # Extract only the filename, stripping any directory components or
        # traversal sequences (e.g., "../", "..\\", nested paths)
        safe_doc = Path(document).name.replace("/", "_").replace("\\", "_")
        return self._xml_dir / str(cik) / f"{safe_acc}_{safe_doc}"

    def get_xml(
        self,
        cik: int,
        accession_number: str,
        document: str,
        max_age_days: int = 365,
    ) -> Optional[bytes]:
        """Retrieve cached XML bytes if fresh enough.

        Args:
            cik: SEC CIK number.
            accession_number: EDGAR accession number.
            document: Primary document filename.
            max_age_days: Maximum cache age in days.

        Returns:
            Cached XML bytes, or None if not cached or stale.
        """
        if not self.enabled:
            return None

        path = self._cache_path(cik, accession_number, document)
        if not path.exists():
            return None

        # Check age
        age_seconds = time.time() - path.stat().st_mtime
        if age_seconds > max_age_days * 86_400:
            logger.debug("Cache expired for %s/%s (age: %.0f days)", cik, accession_number, age_seconds / 86_400)
            path.unlink(missing_ok=True)
            return None

        logger.debug("Cache hit for %s/%s/%s", cik, accession_number, document)
        return path.read_bytes()

    def put_xml(
        self,
        cik: int,
        accession_number: str,
        document: str,
        data: bytes,
    ) -> None:
        """Store XML bytes in the cache.

        Args:
            cik: SEC CIK number.
            accession_number: EDGAR accession number.
            document: Primary document filename.
            data: Raw XML bytes to cache.
        """
        if not self.enabled:
            return

        path = self._cache_path(cik, accession_number, document)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.debug("Cached %s/%s/%s (%d bytes)", cik, accession_number, document, len(data))

        # Evict oldest files if cache exceeds size limit
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        """Remove oldest cache files if total size exceeds the limit."""
        if not self.enabled:
            return
        try:
            files = list(self._xml_dir.rglob("*"))
            files = [f for f in files if f.is_file()]
            total_size = sum(f.stat().st_size for f in files)
            if total_size <= MAX_CACHE_SIZE_BYTES:
                return

            # Sort by modification time (oldest first) and evict until under limit
            files.sort(key=lambda f: f.stat().st_mtime)
            evicted = 0
            for f in files:
                if total_size <= MAX_CACHE_SIZE_BYTES * 0.8:  # Evict to 80% to avoid thrashing
                    break
                fsize = f.stat().st_size
                f.unlink(missing_ok=True)
                total_size -= fsize
                evicted += 1

            if evicted:
                logger.info("Cache eviction: removed %d files, %.1f MB freed", evicted, evicted / 1048576)
        except OSError as exc:
            logger.warning("Cache eviction failed: %s", exc)

    def clear(self) -> None:
        """Clear all cached data."""
        import shutil
        if self._xml_dir.exists():
            shutil.rmtree(self._xml_dir)
            self._xml_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Cache cleared")


# Module-level singleton — importable by retrieval modules
_cache: Optional[FilingCache] = None
_cache_lock = threading.Lock()


def get_cache() -> FilingCache:
    """Get or create the global filing cache singleton. Thread-safe."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:  # Double-checked locking
                _cache = FilingCache()
    return _cache
