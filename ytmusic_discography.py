#!/usr/bin/env python3
"""
YouTube Music Discography Downloader
Downloads an artist's full discography from a YouTube Music artist page URL.

Requirements:
    pip install yt-dlp ytmusicapi requests

Usage:
    python ytmusic_discography.py <artist_url> [options]
    python ytmusic_discography.py "https://music.youtube.com/channel/UCxxxxxx"
    python ytmusic_discography.py "https://music.youtube.com/channel/UCxxxxxx" --format mp3 --output ./music
"""

import argparse
import json
import os
import re
import sys
import subprocess
from pathlib import Path

# ── Optional dependency check ────────────────────────────────────────────────

def check_dependencies():
    missing = []
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        missing.append("yt-dlp")
    try:
        from ytmusicapi import YTMusic  # noqa: F401
    except ImportError:
        missing.append("ytmusicapi")
    if missing:
        print(f"[!] Missing dependencies: {', '.join(missing)}")
        print(f"    Install with: pip install {' '.join(missing)}")
        sys.exit(1)

check_dependencies()

import yt_dlp
from ytmusicapi import YTMusic


# ── Helpers ───────────────────────────────────────────────────────────────────

def resolve_handle_to_channel_id(url: str) -> str:
    """Use yt-dlp to resolve a @handle or any channel URL to a UC... channel ID."""
    print(f"[*] Resolving handle URL: {url}")
    # Normalise to youtube.com so yt-dlp can fetch the page
    fetch_url = url.replace("music.youtube.com", "www.youtube.com")
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(fetch_url, download=False)
            channel_id = info.get("channel_id") or info.get("uploader_id", "")
            if channel_id and channel_id.startswith("UC"):
                return channel_id
            # Sometimes it's nested under entries
            for entry in info.get("entries", []):
                cid = entry.get("channel_id") or entry.get("uploader_id", "")
                if cid and cid.startswith("UC"):
                    return cid
    except Exception as e:
        raise ValueError(f"yt-dlp could not resolve the URL: {e}")
    raise ValueError(f"Could not find a channel ID in yt-dlp response for: {url}")


def extract_channel_id(url: str) -> str:
    """Pull the channel/browse ID out of a YouTube Music URL."""
    # Fast path: ID already in URL
    patterns = [
        r"music\.youtube\.com/channel/(UC[\w-]+)",
        r"music\.youtube\.com/browse/(UC[\w-]+)",
        r"youtube\.com/channel/(UC[\w-]+)",
        r"(UC[\w-]{22})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)

    # Slow path: @handle or other vanity URL — let yt-dlp resolve it
    if "@" in url or "/c/" in url or "/user/" in url:
        return resolve_handle_to_channel_id(url)

    raise ValueError(
        f"Could not extract a channel ID from: {url}\n"
        "Supported formats:\n"
        "  https://music.youtube.com/channel/UCxxxxxx\n"
        "  https://music.youtube.com/@artist_handle"
    )


def fetch_discography(channel_id: str) -> tuple[str, list[dict]]:
    """Return (artist_name, list_of_albums) using ytmusicapi."""
    yt = YTMusic()
    print(f"[*] Fetching artist info for channel: {channel_id}")
    try:
        artist = yt.get_artist(channel_id)
    except Exception as e:
        raise RuntimeError(f"Could not fetch artist data: {e}")

    name = artist.get("name", "Unknown Artist")
    albums_section = artist.get("albums", {})
    results = albums_section.get("results", [])

    # Also grab singles if present
    singles_section = artist.get("singles", {})
    singles = singles_section.get("results", [])

    print(f"[*] Artist : {name}")
    print(f"[*] Albums : {len(results)}")
    print(f"[*] Singles: {len(singles)}")

    return name, results + singles


def get_album_tracks(album_browse_id: str) -> list[str]:
    """Return a list of video IDs for every track in an album."""
    yt = YTMusic()
    try:
        album = yt.get_album(album_browse_id)
    except Exception as e:
        print(f"    [!] Could not fetch album {album_browse_id}: {e}")
        return []
    tracks = album.get("tracks", [])
    ids = []
    for t in tracks:
        vid = t.get("videoId")
        if vid:
            ids.append(vid)
    return ids


def build_ydl_opts(output_dir: Path, audio_format: str, quality: str) -> dict:
    """Build yt-dlp options dictionary."""
    fmt_map = {
        "mp3":  ("bestaudio/best", "mp3",  "192"),
        "m4a":  ("bestaudio[ext=m4a]/bestaudio/best", "m4a", "0"),
        "opus": ("bestaudio[ext=webm]/bestaudio/best", "opus", "0"),
        "flac": ("bestaudio/best", "flac", "0"),
        "wav":  ("bestaudio/best", "wav",  "0"),
    }
    yt_format, postproc_fmt, default_quality = fmt_map.get(
        audio_format, fmt_map["mp3"]
    )
    bitrate = quality if quality else default_quality

    opts = {
        "format": yt_format,
        "outtmpl": str(output_dir / "%(artist)s" / "%(album)s" / "%(track_number)02d - %(title)s.%(ext)s"),
        "writethumbnail": True,
        "embedthumbnail": True,
        "addmetadata": True,
        "ignoreerrors": True,
        "quiet": False,
        "no_warnings": False,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": postproc_fmt,
                "preferredquality": bitrate,
            },
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ],
    }
    return opts


def download_tracks(video_ids: list[str], ydl_opts: dict, dry_run: bool = False):
    """Download a list of YouTube video IDs."""
    urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
    if dry_run:
        for u in urls:
            print(f"    [dry-run] Would download: {u}")
        return
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(urls)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download a full artist discography from YouTube Music.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "url",
        help="YouTube Music artist page URL (e.g. https://music.youtube.com/channel/UCxxxxxx)",
    )
    parser.add_argument(
        "--output", "-o",
        default=str(Path.home() / "Downloads"),
        help="Output directory (default: ~/Downloads)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["mp3", "m4a", "opus", "flac", "wav"],
        default="mp3",
        dest="audio_format",
        help="Audio format (default: mp3)",
    )
    parser.add_argument(
        "--quality", "-q",
        default="",
        help="Audio bitrate/quality, e.g. 320 for mp3 (default: 192 for mp3, best for others)",
    )
    parser.add_argument(
        "--albums-only",
        action="store_true",
        help="Skip singles, download studio albums only",
    )
    parser.add_argument(
        "--singles-only",
        action="store_true",
        help="Download only singles/EPs, skip albums",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be downloaded without actually downloading",
    )
    parser.add_argument(
        "--list-albums",
        action="store_true",
        help="Print the album list and exit without downloading",
    )

    args = parser.parse_args()

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Extract channel ID
    try:
        channel_id = extract_channel_id(args.url)
    except ValueError as e:
        print(f"[!] {e}")
        sys.exit(1)

    # 2. Fetch discography
    try:
        artist_name, releases = fetch_discography(channel_id)
    except RuntimeError as e:
        print(f"[!] {e}")
        sys.exit(1)

    if not releases:
        print("[!] No releases found for this artist. The page may be private or region-locked.")
        sys.exit(1)

    # 3. Optionally filter
    if args.albums_only:
        releases = [r for r in releases if r.get("type", "").lower() in ("album", "")]
        print(f"[*] After filtering: {len(releases)} albums")
    elif args.singles_only:
        releases = [r for r in releases if r.get("type", "").lower() in ("single", "ep")]
        print(f"[*] After filtering: {len(releases)} singles/EPs")

    if args.list_albums:
        print("\nDiscography:")
        for i, r in enumerate(releases, 1):
            rtype = r.get("type", "Album")
            year  = r.get("year", "????")
            title = r.get("title", "Unknown")
            print(f"  {i:>3}. [{year}] {title} ({rtype})")
        sys.exit(0)

    # 4. Build yt-dlp options
    ydl_opts = build_ydl_opts(output_dir, args.audio_format, args.quality)

    # 5. Iterate releases → collect track IDs → download
    total_tracks = 0
    for release in releases:
        title      = release.get("title", "Unknown")
        browse_id  = release.get("browseId", "")
        year       = release.get("year", "")
        rtype      = release.get("type", "Album")

        print(f"\n[→] {rtype}: {title} ({year})")

        if not browse_id:
            print("    [!] No browseId — skipping")
            continue

        track_ids = get_album_tracks(browse_id)
        if not track_ids:
            print("    [!] No tracks found — skipping")
            continue

        print(f"    Tracks: {len(track_ids)}")
        download_tracks(track_ids, ydl_opts, dry_run=args.dry_run)
        total_tracks += len(track_ids)

    print(f"\n[✓] Done! {total_tracks} track(s) processed → {output_dir}")


if __name__ == "__main__":
    main()
