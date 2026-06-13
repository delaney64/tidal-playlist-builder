#!/usr/bin/env python3
"""
tidal_playlist_builder
======================

Reads a CSV of Artist/Track rows and recreates it as a playlist in your TIDAL
account. Works with any CSV that has 'Artist' and 'Track' columns; a 'Search Query'
column is used if present, otherwise it falls back to "<Artist> <Track>".

Pipeline:
  1. Log into TIDAL via the OAuth device flow (opens a link.tidal.com URL once;
     caches the session to ~/.tidal_session.json so future runs skip the login).
  2. Search TIDAL for each row and pick the best matching track.
  3. Create a new playlist and add the matches (chunked, dedup'd).
  4. Write <csv>_misses.csv listing anything not confidently matched.

Tested against tidalapi 0.8.11.
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import tidalapi
except ImportError:
    sys.exit("tidalapi not installed. Run:  pip install tidalapi")

__version__ = "1.0.0"

SESSION_CACHE = Path.home() / ".tidal_session.json"


# ---------------------------------------------------------------------------
# Auth: log in once, then reuse the cached OAuth session on later runs.
# ---------------------------------------------------------------------------
def get_session(use_cache: bool = True) -> "tidalapi.Session":
    session = tidalapi.Session()

    if use_cache and SESSION_CACHE.exists():
        try:
            data = json.loads(SESSION_CACHE.read_text())
            expiry = (
                datetime.datetime.fromisoformat(data["expiry_time"])
                if data.get("expiry_time")
                else None
            )
            session.load_oauth_session(
                data["token_type"],
                data["access_token"],
                data.get("refresh_token"),
                expiry,
            )
            if session.check_login():
                print("Reusing cached TIDAL session.")
                return session
        except Exception:
            pass  # fall through to a fresh login

    # Fresh login: prints a link.tidal.com URL, blocks until you authorize.
    print("Opening TIDAL login. Visit the URL below and authorize this device:\n")
    session.login_oauth_simple()
    if not session.check_login():
        sys.exit("Login failed.")

    SESSION_CACHE.write_text(
        json.dumps(
            {
                "token_type": session.token_type,
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "expiry_time": session.expiry_time.isoformat()
                if session.expiry_time
                else None,
            }
        )
    )
    os.chmod(SESSION_CACHE, 0o600)  # token file: owner read/write only
    print(f"Session cached to {SESSION_CACHE}")
    return session


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------
def normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace -- for loose comparison."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


def artist_matches(csv_artist: str, track) -> bool:
    """True if the CSV artist overlaps the matched track's artist(s)."""
    want = set(normalize(csv_artist).split())
    names = [getattr(track.artist, "name", "")] + [
        a.name for a in getattr(track, "artists", []) or []
    ]
    for name in names:
        got = set(normalize(name).split())
        if want & got:  # any shared token (handles "feat." / punctuation drift)
            return True
    return False


def find_track(session, query: str, csv_artist: str):
    """
    Search TIDAL and return (track, confidence).
    confidence: 'high' if artist verified, 'low' if we took the top hit anyway.
    """
    try:
        results = session.search(query, models=[tidalapi.media.Track], limit=10)
    except Exception as e:
        print(f"   ! search error for '{query}': {e}")
        return None, None

    tracks = (
        results.get("tracks")
        if isinstance(results, dict)
        else getattr(results, "tracks", None)
    )
    if not tracks:
        return None, None

    for t in tracks:  # prefer the first artist-verified hit
        if artist_matches(csv_artist, t):
            return t, "high"
    return tracks[0], "low"  # fall back to top hit, flagged for review


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def read_rows(csv_path: Path):
    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            artist, track = r.get("Artist", "").strip(), r.get("Track", "").strip()
            if artist and track:
                query = (r.get("Search Query") or f"{artist} {track}").strip()
                rows.append((artist, track, query, r.get("Playlist", "")))
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="tidal-playlist-builder",
        description="Build a TIDAL playlist from a CSV of Artist/Track rows.",
    )
    ap.add_argument("csv", help="Path to the CSV (needs Artist + Track columns)")
    ap.add_argument("--name", help="Playlist name (default: CSV 'Playlist' column)")
    ap.add_argument("--delay", type=float, default=0.15, help="Seconds between searches")
    ap.add_argument("--dry-run", action="store_true", help="Search only; don't create")
    ap.add_argument("--no-cache", action="store_true", help="Force a fresh TIDAL login")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(f"File not found: {csv_path}")

    rows = read_rows(csv_path)
    if not rows:
        sys.exit("No usable rows (need 'Artist' and 'Track' columns).")

    playlist_name = (
        args.name
        or (rows[0][3].strip() if rows[0][3].strip() else None)
        or csv_path.stem
    )
    print(f'{len(rows)} tracks to look up -> playlist: "{playlist_name}"\n')

    session = get_session(use_cache=not args.no_cache)

    # --- search ------------------------------------------------------------
    found_ids, misses, low_conf = [], [], []
    seen = set()
    for i, (artist, track, query, _) in enumerate(rows, 1):
        t, conf = find_track(session, query, artist)
        label = f"{artist} - {track}"
        if t is None:
            print(f"[{i}/{len(rows)}] MISS  {label}")
            misses.append((artist, track, "not found"))
        else:
            tag = "ok " if conf == "high" else "?? "
            print(f"[{i}/{len(rows)}] {tag}  {label}  ->  {t.full_name} [{t.id}]")
            if t.id not in seen:
                seen.add(t.id)
                found_ids.append(str(t.id))
            if conf == "low":
                low_conf.append((artist, track, t.full_name))
        time.sleep(args.delay)

    # --- report ------------------------------------------------------------
    print(
        f"\nMatched {len(found_ids)} unique tracks, "
        f"{len(low_conf)} low-confidence, {len(misses)} not found."
    )

    report = csv_path.with_name(csv_path.stem + "_misses.csv")
    with report.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Artist", "Track", "Reason / Matched As"])
        for a, t, why in misses:
            w.writerow([a, t, why])
        for a, t, got in low_conf:
            w.writerow([a, t, f"LOW CONFIDENCE -> {got}"])
    print(f"Review list written to {report}")

    if args.dry_run:
        print("\nDry run -- no playlist created.")
        return
    if not found_ids:
        sys.exit("Nothing matched; not creating an empty playlist.")

    # --- create + populate -------------------------------------------------
    playlist = session.user.create_playlist(
        playlist_name, f"Imported from {csv_path.name}"
    )
    for start in range(0, len(found_ids), 100):  # add() caps at 100/call
        playlist.add(found_ids[start:start + 100])
    print(f"\nDone. Added {len(found_ids)} tracks.")
    print(f"Open it: https://tidal.com/browse/playlist/{playlist.id}")


if __name__ == "__main__":
    main()
