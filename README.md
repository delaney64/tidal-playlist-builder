# tidal-playlist-builder

Turn a CSV of artists and tracks into a real playlist in your TIDAL account.

Point it at a CSV, authorize once via TIDAL's OAuth device flow, and it searches the
catalog, builds the playlist, and hands you back a short list of anything it couldn't
confidently match — so nothing gets silently mis-added.

Built originally to import a "top 3 songs per band" festival lineup, but it works with
any CSV that has `Artist` and `Track` columns.

## Features

- **One-time login.** OAuth device flow; the session caches to `~/.tidal_session.json` (chmod `600`) so later runs skip the login.
- **Confidence-aware matching.** For each row it pulls the top search results and prefers the first whose artist actually overlaps your CSV artist, instead of blindly taking the top hit. Token-based comparison shrugs off `feat.` credits and punctuation drift.
- **A review file, not a black box.** Misses and low-confidence guesses are written to `<csv>_misses.csv` for you to eyeball and add by hand.
- **Safe to re-run.** Dedups within a run, chunks adds to TIDAL's 100-per-call limit, and won't create an empty playlist.
- **Dry-run mode** to preview match quality before anything is created.

## Setup

You need an active TIDAL subscription (the API requires a logged-in account) and
Python 3.9+.

Use a project virtualenv so dependencies don't land in your system Python:

```bash
cd /path/to/csv-tidal
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .                   # installs tidalapi + the `tidal-playlist-builder` command
```

`pip install -e .` gives you both the dependency and the console command. If you
just want to run the script directly, `pip install -r requirements.txt` is enough.

**Interpreter gotcha:** the most common "tidalapi not installed" error is installing
into a different Python than the one running the script. Install into the *exact*
interpreter with `</path/to/python> -m pip install tidalapi` rather than a bare `pip`.
In **PyCharm**, point the project interpreter at the venv: **Settings → Project →
Python Interpreter → Add Interpreter → Existing → select `.venv/bin/python`**. Then the
Run button uses the venv.

When running from PyCharm's Run button, pass the CSV via **Run → Edit Configurations →
Parameters** (e.g. `playlist.csv --dry-run`) and set **Working directory** to the
project root so the relative path resolves.

## Usage

Drop your own CSV in the project root (e.g. `playlist.csv`). Personal CSVs are
gitignored, so your music data stays out of the repo.

```bash
# Simplest: playlist name is taken from the CSV's "Playlist" column
tidal-playlist-builder playlist.csv

# Preview matches without creating anything
tidal-playlist-builder playlist.csv --dry-run

# Override the playlist name; force a fresh login
tidal-playlist-builder playlist.csv --name "Summer 2026" --no-cache
```

Or without installing the console command:

```bash
python3 tidal_playlist_builder.py playlist.csv
```

### Options

| Flag | Description |
| --- | --- |
| `--name NAME` | Playlist name (defaults to the CSV's `Playlist` column, then the filename) |
| `--dry-run` | Search only; report matches but don't create the playlist |
| `--no-cache` | Ignore the cached session and log in fresh |
| `--delay SECONDS` | Pause between searches (default `0.15`); raise it if you hit rate limits |
| `--version` | Print version and exit |

## CSV format

Only `Artist` and `Track` are required. `Search Query` and `Playlist` are used if present.

```csv
Playlist,Position,Artist,Track,Search Query
My Playlist,1,Thrice,Black Honey,Thrice Black Honey
My Playlist,2,Underoath,Writing on the Walls,Underoath Writing on the Walls
```

A working example lives in [`examples/sample_playlist.csv`](examples/sample_playlist.csv).

## What the output looks like

```
315 tracks to look up -> playlist: "Warped Tour DC 2026 - Top 3 Main Lineup"

Reusing cached TIDAL session.
[1/315] ok    3OH!3 - Richman  ->  3OH!3 - Richman [12345678]
[25/315] ??   BIG ASS TRUCK I.E. - BIG ASS BEER  ->  <best guess> [...]
...
Matched 298 unique tracks, 11 low-confidence, 6 not found.
Review list written to mylist_misses.csv

Done. Added 298 tracks.
Open it: https://tidal.com/browse/playlist/<id>
```

`ok` = artist verified. `??` = top hit taken but not verified (logged for review).
`MISS` = nothing found.

## Notes & caveats

- Matching depends on TIDAL's catalog metadata — tracks not in the catalog can't be added, and very new or obscure artists are the usual misses.
- The first run exercises the live OAuth + search round-trip. If the very first search errors, it's almost always a stale session: delete `~/.tidal_session.json` (or pass `--no-cache`) and re-run.
- The token cache is a credential. It's written owner-only and is gitignored — don't commit it.

## License

MIT — see [LICENSE](LICENSE).
