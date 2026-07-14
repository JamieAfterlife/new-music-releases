#!/usr/bin/env python3
"""MusicBrainz-powered new-release feed generator (standard library only)."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from youtube_video_tracker import is_excluded_video_record, render_video_page

VERSION = "0.1.0"
MB_ROOT = "https://musicbrainz.org/ws/2"
LASTFM_ROOT = "https://ws.audioscrobbler.com/2.0/"
VARIOUS_ARTISTS_MBID = "89ad4ac3-39f7-470e-963a-56509c546377"
LASTFM_ARTIST_ALIASES = {
    "Eskimo Callboy": ("Electric Callboy", "cf075492-d880-4afc-b87b-d6b03e33dacc"),
    "HANABIE.": ("HANABIE.", "ce2703e5-34f4-4389-883f-00f8ca2662c2"),
    "Devil You Know": ("Light the Torch", "e35d3678-25e6-48e3-a40d-3059b9831bf3"),
    "WARGASM (UK)": ("WARGASM", "7a3fc4e1-bec5-49f4-888a-0c32fee5071f"),
    "Xzibit, B Real & Demrick (Serial Killers)": (
        "Xzibit",
        "9e839dc3-55f3-4492-ad0e-a1a2e84275e2",
    ),
}
LASTFM_IGNORED_ARTISTS = {
    "Punk Goes Pop 5",  # compilation title incorrectly represented as an artist
    "Dan Kraus",  # no unambiguous MusicBrainz artist entity
    "Rola Young",  # no unambiguous MusicBrainz artist entity
}
DATE_RE = re.compile(r"^\d{4}(?:-\d{2})?(?:-\d{2})?$")


@dataclass
class Settings:
    root: Path
    feed_title: str = "New music"
    timezone: str = "UTC"
    site_url: str = ""
    lookback_days: int = 45
    future_days: int = 90
    max_feed_items: int = 250
    exclude_various_artists: bool = True
    include_appearances: bool = True
    min_lastfm_scrobbles: int = 50
    lastfm_username: str = ""
    github_issue_notifications: bool = False
    watchlist: Path = Path("artists.json")
    blacklist_file: Path = Path("blacklist.json")
    state_file: Path = Path("data/state.json")
    output_dir: Path = Path("public")
    contact: str = "personal-music-tracker"

    @classmethod
    def load(cls, path: Path) -> "Settings":
        raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        tracker = raw.get("tracker", {})
        mb = raw.get("musicbrainz", {})
        root = path.parent.resolve()
        obj = cls(root=root)
        site_path = root / "site.json"
        site = json.loads(site_path.read_text(encoding="utf-8")) if site_path.exists() else {}
        for key in (
            "feed_title",
            "timezone",
            "lastfm_username",
            "min_lastfm_scrobbles",
            "github_issue_notifications",
        ):
            if key in site:
                setattr(obj, key, site[key])
        for key in (
            "feed_title", "timezone", "site_url", "lookback_days", "future_days", "max_feed_items",
            "exclude_various_artists", "include_appearances", "min_lastfm_scrobbles",
        ):
            if key in tracker:
                setattr(obj, key, tracker[key])
        obj.watchlist = root / tracker.get("watchlist", "artists.json")
        obj.blacklist_file = root / tracker.get("blacklist_file", "blacklist.json")
        obj.state_file = root / tracker.get("state_file", "data/state.json")
        obj.output_dir = root / tracker.get("output_dir", "public")
        obj.contact = os.environ.get("MUSICBRAINZ_CONTACT", mb.get("contact", "personal-music-tracker"))
        obj.feed_title = os.environ.get("FEED_TITLE", obj.feed_title)
        obj.timezone = os.environ.get("TRACKER_TIMEZONE", obj.timezone)
        obj.site_url = os.environ.get("SITE_URL", obj.site_url).rstrip("/")
        return obj


class MusicBrainz:
    def __init__(self, contact: str, delay: float = 1.05):
        self.user_agent = f"NewAlbumReleases/{VERSION} ({contact})"
        self.delay = delay
        self.last_request = 0.0

    def get(self, entity: str, params: dict[str, Any], retries: int = 4) -> dict[str, Any]:
        query = urllib.parse.urlencode({**params, "fmt": "json"})
        url = f"{MB_ROOT}/{entity}?{query}"
        for attempt in range(retries):
            wait = self.delay - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            request = urllib.request.Request(
                url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    self.last_request = time.monotonic()
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                self.last_request = time.monotonic()
                if exc.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                    raise
                time.sleep(max(2 ** attempt, int(exc.headers.get("Retry-After", "1"))))
            except urllib.error.URLError:
                self.last_request = time.monotonic()
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("MusicBrainz request failed")

    def search_artists(self, name: str, limit: int = 5) -> list[dict[str, Any]]:
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        data = self.get("artist", {"query": f'artist:"{escaped}"', "limit": limit})
        return data.get("artists", [])

    def release_groups(self, mbid: str, start: str, end: str) -> list[dict[str, Any]]:
        query = f"arid:{mbid} AND firstreleasedate:[{start} TO {end}]"
        return self._search_all("release-group", query, "release-groups")

    def appearance_groups(self, mbid: str, start: str, end: str) -> list[dict[str, Any]]:
        # Recording artist credits include featured/track appearances. Extract their
        # recent release groups and deduplicate them against primary releases later.
        query = f"arid:{mbid} AND firstreleasedate:[{start} TO {end}]"
        recordings = self._search_all("recording", query, "recordings")
        groups: dict[str, dict[str, Any]] = {}
        for recording in recordings:
            for release in recording.get("releases", []):
                group = release.get("release-group") or {}
                rgid = group.get("id")
                if not rgid:
                    continue
                item = dict(group)
                item.setdefault("title", release.get("title", recording.get("title", "Unknown")))
                item.setdefault("first-release-date", release.get("date", recording.get("first-release-date", "")))
                item.setdefault("artist-credit", release.get("artist-credit", []))
                # A recording search also returns ordinary releases by the
                # watched artist. Only mark it as an appearance when the
                # release-level credit identifies other artists. If the API
                # omits that credit, the primary-discography search below can
                # still override this conservative True value.
                release_artist_ids = {
                    (credit.get("artist", credit) or {}).get("id")
                    for credit in item.get("artist-credit", [])
                    if isinstance(credit, dict)
                }
                release_artist_ids.discard(None)
                is_appearance = not release_artist_ids or mbid not in release_artist_ids
                existing = groups.get(rgid)
                matched_recordings = set((existing or {}).get("_appearance_recording_ids", []))
                recording_id = recording.get("id") or recording.get("title")
                if recording_id:
                    matched_recordings.add(str(recording_id))
                if existing:
                    item = {**existing, **item}
                    # If any release-level route credits the watched artist,
                    # the primary-discography result will win during deduping.
                    is_appearance = bool(existing.get("appearance")) and is_appearance
                item["appearance"] = is_appearance
                item["_appearance_recording_ids"] = sorted(matched_recordings)
                item["appearance_track_count"] = len(matched_recordings)
                groups[rgid] = item
        return list(groups.values())

    def release_group_links(self, mbid: str) -> list[dict[str, Any]]:
        # Streaming relationships are commonly attached to a specific regional
        # release rather than the release group, so browse all editions in one call.
        data = self.get("release", {"release-group": mbid, "inc": "url-rels", "limit": 100})
        return [relation for release in data.get("releases", []) for relation in release.get("relations", [])]

    def release_group_metadata(self, mbid: str, release_date: str = "") -> dict[str, Any]:
        """Return links and the most representative official edition's tracklist."""
        data = self.get(
            "release",
            {"release-group": mbid, "inc": "url-rels+recordings", "limit": 100},
        )
        editions = data.get("releases", [])
        relations = [relation for edition in editions for relation in edition.get("relations", [])]

        def edition_key(edition: dict[str, Any]) -> tuple[Any, ...]:
            media = edition.get("media", [])
            tracks = [track for medium in media for track in medium.get("tracks", [])]
            digital = any(str(medium.get("format", "")).casefold() == "digital media" for medium in media)
            return (
                edition.get("status") != "Official",
                not tracks,
                edition.get("date", "") != release_date,
                not digital,
                edition.get("country") != "XW",
                -len(tracks),
                edition.get("id", ""),
            )

        chosen = min(editions, key=edition_key) if editions else None
        tracklist: list[dict[str, Any]] = []
        if chosen:
            for medium_index, medium in enumerate(chosen.get("media", []), start=1):
                disc = int(medium.get("position") or medium_index)
                for track_index, track in enumerate(medium.get("tracks", []), start=1):
                    recording = track.get("recording") or {}
                    title = track.get("title") or recording.get("title") or "Untitled"
                    tracklist.append({
                        "disc": disc,
                        "disc_title": medium.get("title") or "",
                        "position": str(track.get("number") or track.get("position") or track_index),
                        "title": title,
                        "length_ms": track.get("length") or recording.get("length"),
                    })
        return {
            "relations": relations,
            "edition_id": chosen.get("id") if chosen else None,
            "tracklist": tracklist,
        }

    def _search_all(self, entity: str, query: str, key: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = self.get(entity, {"query": query, "limit": 100, "offset": offset})
            page = data.get(key, [])
            results.extend(page)
            offset += len(page)
            total = int(data.get("count", len(results)))
            if not page or offset >= total:
                return results


def fetch_lastfm_artists(user: str, api_key: str) -> list[dict[str, Any]]:
    artists: list[dict[str, Any]] = []
    page = 1
    while True:
        params = urllib.parse.urlencode({
            "method": "library.getartists",
            "api_key": api_key,
            "user": user,
            "limit": 1000,
            "page": page,
            "format": "json",
        })
        request = urllib.request.Request(
            f"{LASTFM_ROOT}?{params}",
            headers={"User-Agent": f"NewAlbumReleases/{VERSION} (personal music tracker)"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        if "error" in data:
            raise RuntimeError(f"Last.fm error {data['error']}: {data.get('message', 'Unknown error')}")
        container = data.get("artists", {})
        artists.extend(container.get("artist", []))
        attrs = container.get("@attr", {})
        total_pages = int(attrs.get("totalPages", page))
        if page >= total_pages:
            return artists
        page += 1


def fetch_lastfm_top_artists(
    user: str,
    api_key: str,
    period: str = "12month",
) -> list[dict[str, Any]]:
    """Return a user's top artists for a supported Last.fm chart period."""
    artists: list[dict[str, Any]] = []
    page = 1
    while True:
        params = urllib.parse.urlencode({
            "method": "user.gettopartists",
            "api_key": api_key,
            "user": user,
            "period": period,
            "limit": 1000,
            "page": page,
            "format": "json",
        })
        request = urllib.request.Request(
            f"{LASTFM_ROOT}?{params}",
            headers={"User-Agent": f"NewAlbumReleases/{VERSION} (personal music tracker)"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        if "error" in data:
            raise RuntimeError(f"Last.fm error {data['error']}: {data.get('message', 'Unknown error')}")
        container = data.get("topartists", {})
        artists.extend(container.get("artist", []))
        attrs = container.get("@attr", {})
        total_pages = int(attrs.get("totalPages", page))
        if page >= total_pages:
            return artists
        page += 1


def build_recent_lastfm_candidates(
    settings: Settings,
    mb: MusicBrainz,
    user: str,
    api_key: str,
    min_plays: int = 5,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve recent Last.fm favourites for the website's first-run review."""
    source = fetch_lastfm_top_artists(user, api_key, "12month")
    eligible = [x for x in source if int(x.get("playcount", 0)) >= min_plays]
    resolved: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []

    aliases = lastfm_artist_aliases(settings)
    ignored_sources = lastfm_ignored_sources(settings)
    for item in eligible:
        name = item.get("name", "").strip()
        if not name or name in LASTFM_IGNORED_ARTISTS or name.casefold() in ignored_sources:
            continue
        mbid = item.get("mbid", "").strip()
        if name.casefold() in aliases:
            name, mbid = aliases[name.casefold()]
        try:
            chosen = {"id": mbid, "name": name} if mbid else best_artist(name, mb.search_artists(name))
            if not chosen:
                raise ValueError(f"No MusicBrainz artist found for {name!r}")
            key = chosen["id"]
            existing = resolved.setdefault(
                key,
                {
                    "name": chosen.get("name", name),
                    "mbid": key,
                    "lastfm_scrobbles_12month": 0,
                    "lastfm_user": user,
                },
            )
            existing["lastfm_scrobbles_12month"] += int(item.get("playcount", 0))
        except (ValueError, urllib.error.URLError, urllib.error.HTTPError):
            unresolved.append(name)

    candidates = sorted(
        resolved.values(),
        key=lambda x: (-int(x["lastfm_scrobbles_12month"]), x["name"].casefold()),
    )
    save_json(
        settings.root / "data" / "lastfm_recent_artists.json",
        {"period": "12month", "minimum_scrobbles": min_plays, "artists": candidates},
    )
    return candidates, unresolved


def import_lastfm(
    settings: Settings,
    mb: MusicBrainz,
    user: str,
    api_key: str,
    min_plays: int,
) -> tuple[int, list[str], int]:
    source = fetch_lastfm_artists(user, api_key)
    eligible = [x for x in source if int(x.get("playcount", 0)) >= min_plays]
    processed = 0
    unresolved: list[str] = []
    imported_counts: dict[str, int] = {}
    data = load_json(settings.watchlist, {"artists": []})
    artists = data.setdefault("artists", [])
    blacklist = load_json(settings.blacklist_file, {})

    aliases = lastfm_artist_aliases(settings)
    ignored_sources = lastfm_ignored_sources(settings)
    for item in eligible:
        name = item.get("name", "").strip()
        if name in LASTFM_IGNORED_ARTISTS or name.casefold() in ignored_sources:
            continue
        mbid = item.get("mbid", "").strip()
        if name.casefold() in aliases:
            name, mbid = aliases[name.casefold()]
        try:
            entry = next((x for x in artists if mbid and x.get("mbid") == mbid), None)
            if entry is None:
                entry = next(
                    (x for x in artists if x.get("name", "").casefold() == name.casefold()),
                    None,
                )
            if entry is None:
                if mbid:
                    chosen = {"id": mbid, "name": name}
                else:
                    chosen = best_artist(name, mb.search_artists(name))
                    if not chosen:
                        raise ValueError(f"No MusicBrainz artist found for {name!r}")
                if artist_blacklist_reason(chosen.get("name", name), chosen["id"], blacklist):
                    continue
                entry = {"name": chosen.get("name", name), "mbid": chosen["id"]}
                artists.append(entry)
            resolved_mbid = entry["mbid"]
            imported_counts[resolved_mbid] = (
                imported_counts.get(resolved_mbid, 0) + int(item.get("playcount", 0))
            )
            # Aliases can occur as separate Last.fm rows while representing one
            # MusicBrainz artist, so combine their play counts for this import.
            entry["lastfm_scrobbles"] = imported_counts[resolved_mbid]
            entry["lastfm_user"] = user
            processed += 1
            print(f"Added {name} ({item.get('playcount', 0)} scrobbles)")
        except (ValueError, urllib.error.URLError, urllib.error.HTTPError):
            unresolved.append(name)
    artists.sort(key=lambda x: x["name"].casefold())
    save_json(settings.watchlist, data)
    return processed, unresolved, len(source)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def lastfm_artist_aliases(settings: Settings) -> dict[str, tuple[str, str]]:
    """Combine built-in corrections with aliases chosen on the management page."""
    aliases = {source.casefold(): target for source, target in LASTFM_ARTIST_ALIASES.items()}
    custom = load_json(settings.root / "aliases.json", {"artist_aliases": []})
    for record in custom.get("artist_aliases", []):
        source = str(record.get("source_name", "")).strip()
        name = str(record.get("name", "")).strip()
        mbid = str(record.get("mbid", "")).strip()
        if source and name and mbid:
            aliases[source.casefold()] = (name, mbid)
    return aliases


def lastfm_ignored_sources(settings: Settings) -> set[str]:
    """Return Last.fm credit strings the listener chose not to treat as artists."""
    custom = load_json(settings.root / "aliases.json", {"ignored_sources": []})
    return {
        str(source).strip().casefold()
        for source in custom.get("ignored_sources", [])
        if str(source).strip()
    }


def save_lastfm_unresolved(settings: Settings, names: Iterable[str]) -> None:
    unique = sorted({name.strip() for name in names if name.strip()}, key=str.casefold)
    save_json(
        settings.root / "data" / "lastfm_unresolved.json",
        {"artists": [{"source_name": name} for name in unique]},
    )


def artist_credit(item: dict[str, Any]) -> tuple[str, list[str]]:
    names: list[str] = []
    ids: list[str] = []
    for credit in item.get("artist-credit", []):
        if isinstance(credit, str):
            continue
        artist = credit.get("artist", credit)
        if artist.get("name"):
            names.append(credit.get("name") or artist["name"])
        if artist.get("id"):
            ids.append(artist["id"])
    return " & ".join(names) or "Unknown artist", ids


def normalize_release(group: dict[str, Any], watched: dict[str, Any]) -> dict[str, Any] | None:
    release_date = group.get("first-release-date", "")
    if not release_date or not DATE_RE.match(release_date):
        return None
    artist, artist_ids = artist_credit(group)
    primary_raw = group.get("primary-type") or group.get("primary_type") or "Other"
    primary = "EP" if str(primary_raw).casefold() == "ep" else str(primary_raw).title()
    secondary = [str(x).title() for x in group.get("secondary-types", group.get("secondary_types", []))]
    return {
        "id": group["id"],
        "title": group.get("title") or "Untitled",
        "artist": artist if artist != "Unknown artist" else watched["name"],
        "artist_ids": artist_ids,
        "watched_artist": watched["name"],
        "watched_artist_id": watched.get("mbid"),
        "date": release_date,
        "type": primary,
        "secondary_types": secondary,
        "live": "Live" in secondary,
        "appearance": bool(group.get("appearance")),
        "appearance_track_count": group.get("appearance_track_count"),
        "musicbrainz": f"https://musicbrainz.org/release-group/{group['id']}",
        "links": {},
    }


def display_release_type(release: dict[str, Any]) -> str:
    """Describe a one-track guest appearance as the single contribution it is."""
    try:
        matched_tracks = int(release.get("appearance_track_count") or 0)
    except (TypeError, ValueError):
        matched_tracks = 0
    if release.get("appearance") and matched_tracks == 1:
        return "Single"
    return str(release.get("type") or "Release")


def is_various_artists(release: dict[str, Any]) -> bool:
    return (
        VARIOUS_ARTISTS_MBID in release.get("artist_ids", [])
        or release.get("artist", "").casefold() == "various artists"
    )


def is_compilation_demo_appearance(release: dict[str, Any]) -> bool:
    """Identify low-signal artist appearances on compilation demo dumps."""
    secondary = {
        str(value).strip().casefold()
        for value in release.get("secondary_types", [])
        if str(value).strip()
    }
    return bool(release.get("appearance")) and {"compilation", "demo"} <= secondary


def appearance_match_text(release: dict[str, Any]) -> str:
    """Explain which tracked artist caused an appearance to match."""
    watched = str(release.get("watched_artist") or "").strip()
    credited = str(release.get("artist") or "").strip()
    if release.get("appearance") and watched and watched.casefold() != credited.casefold():
        return f"Matched via {watched}"
    return ""


def blacklist_reason(release: dict[str, Any], blacklist: dict[str, Any]) -> str | None:
    release_id = str(release.get("id", "")).casefold()
    blocked_release_ids = {str(x).strip().casefold() for x in blacklist.get("release_ids", [])}
    if release_id in blocked_release_ids:
        return "release ID"

    blocked_mbids = {str(x).strip().casefold() for x in blacklist.get("artist_mbids", [])}
    release_mbids = {
        str(x).casefold()
        for x in [*release.get("artist_ids", []), release.get("watched_artist_id")]
        if x
    }
    if blocked_mbids & release_mbids:
        return "artist MusicBrainz ID"

    blocked_artists = {str(x).strip().casefold() for x in blacklist.get("artists", []) if str(x).strip()}
    credited_artists = {
        release.get("artist", "").strip().casefold(),
        release.get("watched_artist", "").strip().casefold(),
    }
    credited_artists.update(
        part.strip().casefold() for part in re.split(r"\s+&\s+", release.get("artist", ""))
    )
    if blocked_artists & credited_artists:
        return "artist name"

    title = release.get("title", "").casefold()
    for phrase in blacklist.get("title_contains", []):
        phrase = str(phrase).strip().casefold()
        if phrase and phrase in title:
            return f'title contains "{phrase}"'
    return None


def artist_blacklist_reason(name: str, mbid: str, blacklist: dict[str, Any]) -> str | None:
    """Return why an artist is blocked independently of any release."""
    blocked_names = {
        str(value).strip().casefold()
        for value in blacklist.get("artists", [])
        if str(value).strip()
    }
    if name.strip().casefold() in blocked_names:
        return "artist name"
    blocked_mbids = {
        str(value).strip().casefold()
        for value in blacklist.get("artist_mbids", [])
        if str(value).strip()
    }
    if mbid.strip().casefold() in blocked_mbids:
        return "artist MusicBrainz ID"
    return None


def visible_releases(
    settings: Settings,
    releases: Iterable[dict[str, Any]],
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or dt.datetime.now(dt.timezone.utc)
    start = (now.date() - dt.timedelta(days=settings.lookback_days)).isoformat()
    end = (now.date() + dt.timedelta(days=settings.future_days)).isoformat()
    blacklist = load_json(settings.blacklist_file, {})
    visible: list[dict[str, Any]] = []
    today = now.date().isoformat()
    for release in releases:
        normalized_date = comparable_date(release.get("date", ""))
        if (
            not (start <= normalized_date <= end)
            or is_compilation_demo_appearance(release)
            or blacklist_reason(release, blacklist)
        ):
            continue
        item = dict(release)
        item["upcoming"] = normalized_date > today
        visible.append(item)
    return visible


def fallback_links(release: dict[str, Any]) -> dict[str, str]:
    query = urllib.parse.quote_plus(f"{release['artist']} {release['title']}")
    return {
        "spotify_search": f"https://open.spotify.com/search/{query}",
        "youtube_search": f"https://www.youtube.com/results?search_query={query}",
        "youtube_music_search": f"https://music.youtube.com/search?q={query}",
    }


def notification_markdown(releases: Iterable[dict[str, Any]]) -> str:
    """Format a concise GitHub notification containing playable release links."""
    rows = ["## New music releases", ""]
    for release in releases:
        links = {**fallback_links(release), **release.get("links", {})}
        labels = [display_release_type(release)]
        if release.get("live"):
            labels.append("Live")
        if release.get("appearance"):
            labels.append("Feature")
        match_text = appearance_match_text(release)
        rows.extend([
            f"### {release.get('artist', 'Unknown artist')} — {release.get('title', 'Untitled')}",
            f"{' · '.join(dict.fromkeys(labels))} · {release.get('date', '')}",
            *([f"**{match_text}**"] if match_text else []),
            " · ".join([
                f"[Spotify]({links.get('spotify') or links['spotify_search']})",
                f"[YouTube Music]({links.get('youtube_music') or links['youtube_music_search']})",
                f"[YouTube]({links.get('youtube') or links['youtube_search']})",
            ]),
            "",
        ])
    return "\n".join(rows).rstrip() + "\n"


def add_exact_links(release: dict[str, Any], relations: Iterable[dict[str, Any]]) -> None:
    for relation in relations:
        url = (relation.get("url") or {}).get("resource", "")
        lower = url.casefold()
        if "open.spotify.com/" in lower:
            release["links"].setdefault("spotify", url)
        elif "music.youtube.com/" in lower:
            release["links"].setdefault("youtube_music", url)
        elif "youtube.com/" in lower or "youtu.be/" in lower:
            release["links"].setdefault("youtube", url)


def cover_art_url(release: dict[str, Any], size: int = 250) -> str:
    return f"https://coverartarchive.org/release-group/{release['id']}/front-{size}"


def enrich_release(release: dict[str, Any], mb: MusicBrainz, checked_at: dt.datetime) -> None:
    metadata = mb.release_group_metadata(release["id"], release.get("date", ""))
    add_exact_links(release, metadata.get("relations", []))
    release["edition_id"] = metadata.get("edition_id")
    release["tracklist"] = metadata.get("tracklist", [])
    release["metadata_checked_at"] = checked_at.isoformat()


def format_duration(milliseconds: Any) -> str:
    try:
        seconds = max(0, round(int(milliseconds) / 1000))
    except (TypeError, ValueError):
        return ""
    return f"{seconds // 60}:{seconds % 60:02d}"


def make_rss(settings: Settings, releases: list[dict[str, Any]], generated: dt.datetime) -> str:
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    ET.register_namespace("media", "http://search.yahoo.com/mrss/")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = settings.feed_title
    ET.SubElement(channel, "link").text = settings.site_url or "https://musicbrainz.org"
    ET.SubElement(channel, "description").text = "New releases from watched artists"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(generated)
    if settings.site_url:
        ET.SubElement(
            channel, "{http://www.w3.org/2005/Atom}link",
            {"href": settings.site_url.rstrip("/") + "/feed.xml", "rel": "self", "type": "application/rss+xml"},
        )
    item_dates: dict[int, dt.datetime] = {}
    for release in releases[: settings.max_feed_items]:
        item = ET.SubElement(channel, "item")
        label = display_release_type(release) + (" · Live" if release["live"] else "") + (" · Upcoming" if release.get("upcoming") else "")
        ET.SubElement(item, "title").text = f"{release['artist']} — {release['title']} ({label})"
        ET.SubElement(item, "link").text = release["links"].get("spotify", release["musicbrainz"])
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = f"musicbrainz:release-group:{release['id']}"
        ET.SubElement(
            item,
            "{http://search.yahoo.com/mrss/}thumbnail",
            {"url": cover_art_url(release), "width": "250", "height": "250"},
        )
        pub = (
            dt.datetime.fromisoformat(release["first_seen"])
            if release.get("upcoming") and release.get("first_seen")
            else parse_date(release["date"])
        )
        ET.SubElement(item, "pubDate").text = format_datetime(pub)
        item_dates[id(item)] = pub
        desc = release_description(release)
        ET.SubElement(item, "description").text = desc
    decisions = load_json(settings.root / "video_decisions.json", {"rejected": []})
    rejected = set(decisions.get("rejected", []))
    video_state = load_json(settings.root / "data" / "videos.json", {"videos": {}})
    for video_id, video in video_state.get("videos", {}).items():
        if (
            video_id in rejected
            or str(video.get("channel", "")).casefold().endswith(" - topic")
            or is_excluded_video_record(video)
        ):
            continue
        item = ET.SubElement(channel, "item")
        artist = ", ".join(video.get("matched_artists", [])) or video.get("channel", "Unknown channel")
        title = video.get("title", "Untitled video")
        url = video.get("url") or f"https://www.youtube.com/watch?v={video_id}"
        ET.SubElement(item, "title").text = f"{artist} â€” {title} (Music Video)"
        ET.SubElement(item, "link").text = url
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = f"youtube:video:{video_id}"
        if video.get("thumbnail"):
            ET.SubElement(item, "{http://search.yahoo.com/mrss/}thumbnail", {"url": video["thumbnail"]})
        try:
            pub = dt.datetime.fromisoformat(str(video.get("published_at", "")).replace("Z", "+00:00"))
        except ValueError:
            pub = generated
        ET.SubElement(item, "pubDate").text = format_datetime(pub)
        item_dates[id(item)] = pub
        ET.SubElement(item, "description").text = (
            f'<p><strong>Music Video</strong> Â· {html.escape(video.get("channel", ""))}</p>'
            f'<p><a href="{html.escape(url, quote=True)}">Watch on YouTube</a></p>'
        )
    items = list(channel.findall("item"))
    for item in items:
        channel.remove(item)
    for item in sorted(items, key=lambda node: item_dates.get(id(node), generated), reverse=True):
        channel.append(item)
    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n"


def digest_category(release: dict[str, Any]) -> str:
    """Group appearances separately while keeping release types predictable."""
    if release.get("appearance"):
        return "Feature"
    release_type = display_release_type(release)
    return release_type if release_type in {"Album", "EP", "Single"} else "Other"


def digest_section(title: str, releases: Iterable[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for release in releases:
        grouped.setdefault(digest_category(release), []).append(release)
    if not grouped:
        return f"<h2>{html.escape(title)}</h2><p>None.</p>"

    rows = [f"<h2>{html.escape(title)}</h2>"]
    for category in ("Album", "EP", "Single", "Feature", "Other"):
        items = grouped.get(category, [])
        if not items:
            continue
        label = {"EP": "EPs", "Other": "Other releases"}.get(category, category + "s")
        rows.append(f"<h3>{html.escape(label)}</h3><ul>")
        for release in sorted(
            items,
            key=lambda item: (item.get("artist", "").casefold(), item.get("title", "").casefold()),
        ):
            links = {**fallback_links(release), **release.get("links", {})}
            spotify = links.get("spotify") or links["spotify_search"]
            youtube_music = links.get("youtube_music") or links["youtube_music_search"]
            youtube = links.get("youtube") or links["youtube_search"]
            details = []
            if release.get("live"):
                details.append("Live")
            match_text = appearance_match_text(release)
            if match_text:
                details.append(match_text)
            suffix = (
                f" <small>({' · '.join(html.escape(value) for value in details)})</small>"
                if details else ""
            )
            rows.append(
                f'<li><strong>{html.escape(release.get("artist", "Unknown artist"))}</strong> — '
                f'<a href="{html.escape(spotify, quote=True)}">{html.escape(release.get("title", "Untitled"))}</a>'
                f'{suffix}<br><small><a href="{html.escape(youtube_music, quote=True)}">YouTube Music</a> · '
                f'<a href="{html.escape(youtube, quote=True)}">YouTube</a></small></li>'
            )
        rows.append("</ul>")
    return "".join(rows)


def make_digest_rss(settings: Settings, releases: list[dict[str, Any]], generated: dt.datetime) -> str:
    """Create one grouped digest item per local day, published from 6am onward."""
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"{settings.feed_title} — daily digest"
    ET.SubElement(channel, "link").text = settings.site_url or "https://musicbrainz.org"
    ET.SubElement(channel, "description").text = (
        "A 6am digest of today's expected music and yesterday's releases"
    )
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(generated)
    if settings.site_url:
        ET.SubElement(
            channel,
            "{http://www.w3.org/2005/Atom}link",
            {
                "href": settings.site_url.rstrip("/") + "/digest.xml",
                "rel": "self",
                "type": "application/rss+xml",
            },
        )

    local_generated = display_time(generated, settings.timezone)
    digest_day = local_generated.date()
    if local_generated.hour < 6:
        digest_day -= dt.timedelta(days=1)
    exact_dates: dict[str, list[dict[str, Any]]] = {}
    for release in releases:
        release_date = str(release.get("date", ""))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
            exact_dates.setdefault(release_date, []).append(release)

    for offset in range(min(settings.lookback_days, 30)):
        day = digest_day - dt.timedelta(days=offset)
        expected = exact_dates.get(day.isoformat(), [])
        yesterday = exact_dates.get((day - dt.timedelta(days=1)).isoformat(), [])
        if not expected and not yesterday:
            continue
        item = ET.SubElement(channel, "item")
        friendly = day.strftime("%A, %d %B %Y").replace(" 0", " ")
        ET.SubElement(item, "title").text = f"Daily new music — {friendly}"
        ET.SubElement(item, "link").text = settings.site_url or "https://musicbrainz.org"
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = (
            f"new-music-digest:{day.isoformat()}"
        )
        zone = local_generated.tzinfo or dt.timezone.utc
        published = dt.datetime.combine(day, dt.time(6), tzinfo=zone)
        ET.SubElement(item, "pubDate").text = format_datetime(published)
        ET.SubElement(item, "description").text = (
            digest_section("Expected today", expected)
            + digest_section("Made available yesterday", yesterday)
        )
    ET.indent(rss, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n"


def digest_due(settings: Settings, now: dt.datetime | None = None) -> bool:
    """Return true during the user's local 6am hour."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return display_time(now, settings.timezone).hour == 6


def parse_date(value: str) -> dt.datetime:
    parts = [int(x) for x in value.split("-")]
    while len(parts) < 3:
        parts.append(1)
    return dt.datetime(parts[0], parts[1], parts[2], 12, tzinfo=dt.timezone.utc)


def display_time(value: dt.datetime, timezone_name: str) -> dt.datetime:
    """Convert a timestamp using an explicit timezone, falling back safely to UTC."""
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = dt.timezone.utc
    return value.astimezone(zone)


def comparable_date(value: str) -> str:
    """Convert MusicBrainz year/month/day precision into an ISO day for bounds checks."""
    parts = value.split("-")
    return "-".join((parts + ["01", "01"])[:3])


def release_description(release: dict[str, Any]) -> str:
    links = {**fallback_links(release), **release["links"]}
    match_text = appearance_match_text(release)
    rows = [
        f'<p><img src="{html.escape(cover_art_url(release), quote=True)}" width="250" height="250" '
        f'alt="Cover art for {html.escape(release["title"], quote=True)}"></p>',
        f"<p><strong>{html.escape(display_release_type(release))}</strong> · {html.escape(release['date'])}"
        + (" · Live" if release["live"] else "")
        + (" · Appearance" if release["appearance"] else "")
        + (" · Upcoming" if release.get("upcoming") else "") + "</p>",
        *([f"<p><strong>{html.escape(match_text)}</strong></p>"] if match_text else []),
        "<p>" + " · ".join(
            f'<a href="{html.escape(url, quote=True)}">{label}</a>' for label, url in (
                ("Spotify", links.get("spotify") or links["spotify_search"]),
                ("YouTube", links.get("youtube") or links["youtube_search"]),
                ("YouTube Music", links.get("youtube_music") or links["youtube_music_search"]),
                ("MusicBrainz", release["musicbrainz"]),
            )
        ) + "</p>",
    ]
    tracklist = release.get("tracklist", [])
    if tracklist:
        discs: dict[int, list[dict[str, Any]]] = {}
        for track in tracklist:
            discs.setdefault(int(track.get("disc") or 1), []).append(track)
        rows.append(f"<p><strong>Tracklist ({len(tracklist)} tracks)</strong></p>")
        for disc, tracks in discs.items():
            disc_title = next((track.get("disc_title") for track in tracks if track.get("disc_title")), "")
            if len(discs) > 1 or disc_title:
                heading = f"Disc {disc}" + (f" — {disc_title}" if disc_title else "")
                rows.append(f"<p><strong>{html.escape(heading)}</strong></p>")
            items = []
            for track in tracks:
                duration = format_duration(track.get("length_ms"))
                suffix = f" <small>({duration})</small>" if duration else ""
                items.append(
                    f'<li>{html.escape(track.get("title") or "Untitled")}{suffix}</li>'
                )
            rows.append("<ol>" + "".join(items) + "</ol>")
    return "".join(rows)


def make_html(settings: Settings, releases: list[dict[str, Any]], generated: dt.datetime) -> str:
    selected = releases[: settings.max_feed_items]
    ratings = load_json(settings.root / "ratings.json", {"ratings": {}}).get("ratings", {})

    def rating_controls(item_id: str) -> str:
        current = int(ratings.get(item_id, {}).get("rating", 0) or 0)
        stars = "".join(
            f'<a class="rating__star{" rating__star--selected" if number <= current else ""}" '
            f'href="history.html?rate={urllib.parse.quote(item_id, safe="")}&amp;stars={number}&amp;return=releases" '
            f'aria-label="Rate {number} out of 5" title="Rate {number} out of 5">★</a>'
            for number in range(1, 6)
        )
        sentiment = "Liked" if current >= 4 else "Disliked" if current else "Rate"
        return f'<div class="rating" data-rating="{current}" data-server-rating="{current}" data-rating-id="{html.escape(item_id, quote=True)}"><span>{sentiment}</span>{stars}</div>'

    by_date: dict[str, list[dict[str, Any]]] = {}
    for release in selected:
        by_date.setdefault(release["date"], []).append(release)
    video_decisions = load_json(settings.root / "video_decisions.json", {"rejected": []})
    rejected_videos = set(video_decisions.get("rejected", []))
    video_state = load_json(settings.root / "data" / "videos.json", {"videos": {}})
    videos = [
        video for video_id, video in video_state.get("videos", {}).items()
        if video_id not in rejected_videos
        and not str(video.get("channel", "")).casefold().endswith(" - topic")
        and not is_excluded_video_record(video)
    ]
    videos.sort(key=lambda video: video.get("published_at", ""), reverse=True)
    videos_by_date: dict[str, list[dict[str, Any]]] = {}
    for video in videos:
        published_date = str(video.get("published_at", ""))[:10]
        if DATE_RE.fullmatch(published_date):
            videos_by_date.setdefault(published_date, []).append(video)

    groups: list[str] = []
    dates = sorted({*by_date, *videos_by_date}, key=comparable_date, reverse=True)
    for release_date in dates:
        dated_releases = by_date.get(release_date, [])
        friendly = parse_date(release_date).strftime("%B %d").replace(" 0", " ")
        cards: list[str] = []
        for release in dated_releases:
            links = {**fallback_links(release), **release["links"]}
            spotify = links.get("spotify") or links["spotify_search"]
            youtube = links.get("youtube") or links["youtube_search"]
            youtube_music = links.get("youtube_music") or links["youtube_music_search"]
            shown_type = display_release_type(release)
            flags = [shown_type]
            if release["live"]:
                flags.append("Live")
            if release["appearance"]:
                flags.append("Feature")
            if release.get("upcoming"):
                flags.append("Upcoming")
            match_text = appearance_match_text(release)
            badges = "".join(
                f'<span class="badge badge--{html.escape(flag.casefold())}">{html.escape(flag)}</span>'
                for flag in flags
            )
            search_text = f'{release["artist"]} {release["title"]} {match_text} {" ".join(flags)}'.casefold()
            initials = "".join(word[0] for word in release["artist"].split()[:2] if word) or "♪"
            cover = f'https://coverartarchive.org/release-group/{release["id"]}/front-250'
            type_class = "feature" if release["appearance"] else shown_type.casefold()
            sort_rank = 3 if release["appearance"] else {
                "album": 0,
                "ep": 1,
                "single": 2,
            }.get(shown_type.casefold(), 4)
            cards.append(
                f'<article class="release release--{html.escape(type_class)}" data-type="{html.escape(shown_type.casefold())}" '
                f'data-live="{str(release["live"]).lower()}" data-feature="{str(release["appearance"]).lower()}" '
                f'data-upcoming="{str(bool(release.get("upcoming"))).lower()}" '
                f'data-rank="{sort_rank}" data-artist="{html.escape(release["artist"].casefold(), quote=True)}" '
                f'data-title="{html.escape(release["title"].casefold(), quote=True)}" '
                f'data-search="{html.escape(search_text, quote=True)}"><div class="cover">'
                f'<span class="cover__fallback">{html.escape(initials[:2].upper())}</span>'
                f'<img loading="lazy" src="{html.escape(cover, quote=True)}" alt="" referrerpolicy="no-referrer"></div>'
                '<div class="release__content"><div class="badges">' + badges + '</div>'
                f'<a class="release__title" href="{html.escape(spotify, quote=True)}" target="_blank" rel="noopener">{html.escape(release["title"])}</a>'
                f'<div class="release__artist">{html.escape(release["artist"])}</div>'
                + (f'<div class="release__match">{html.escape(match_text)}</div>' if match_text else '')
                + '<div class="services">'
                f'<a class="service service--spotify" href="{html.escape(spotify, quote=True)}" target="_blank" rel="noopener">Spotify</a>'
                f'<a class="service" href="{html.escape(youtube_music, quote=True)}" target="_blank" rel="noopener">YouTube Music</a>'
                f'<a class="service" href="{html.escape(youtube, quote=True)}" target="_blank" rel="noopener">YouTube</a>'
                f'<a class="service service--muted" href="{html.escape(release["musicbrainz"], quote=True)}" target="_blank" rel="noopener">MusicBrainz</a>'
                f'<a class="service service--mute" href="manage.html?hide_release={urllib.parse.quote(release["id"], safe="")}">Hide</a>'
                f'</div>{"" if release.get("upcoming") else rating_controls("release:" + release["id"])}</div></article>'
            )
        for video in videos_by_date.get(release_date, []):
            artist = ", ".join(video.get("matched_artists", [])) or video.get("channel", "Unknown channel")
            title = video.get("title", "Untitled video")
            url = video.get("url") or f'https://www.youtube.com/watch?v={video.get("id", "")}'
            thumbnail = video.get("thumbnail", "")
            search_text = f"{artist} {title} {video.get('channel', '')} music video".casefold()
            initials = "".join(word[0] for word in artist.split()[:2] if word) or "♪"
            cards.append(
                f'<article class="release release--video" data-type="video" data-live="false" data-feature="false" '
                f'data-upcoming="false" data-rank="4" data-artist="{html.escape(artist.casefold(), quote=True)}" '
                f'data-title="{html.escape(title.casefold(), quote=True)}" data-search="{html.escape(search_text, quote=True)}"><div class="cover">'
                f'<span class="cover__fallback">{html.escape(initials[:2].upper())}</span>'
                f'<img loading="lazy" src="{html.escape(thumbnail, quote=True)}" alt="" referrerpolicy="no-referrer"></div>'
                '<div class="release__content"><div class="badges"><span class="badge badge--video">Music Video</span></div>'
                f'<a class="release__title" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">{html.escape(title)}</a>'
                f'<div class="release__artist">{html.escape(artist)}</div><div class="release__match">{html.escape(video.get("channel", ""))}</div>'
                '<div class="services">'
                f'<a class="service" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">YouTube</a>'
                f'<a class="service service--mute" href="manage.html?hide_video={urllib.parse.quote(video.get("id", ""), safe="")}">Hide</a>'
                f'</div>{rating_controls("video:" + video.get("id", ""))}</div></article>'
            )
        groups.append(
            f'<section class="release-day" data-date="{html.escape(comparable_date(release_date), quote=True)}">'
            f'<div class="release-day__date"><span>{html.escape(friendly)}</span>'
            f'<small>{len(cards)} item{"s" if len(cards) != 1 else ""}</small></div>'
            f'<div class="release-grid">{"".join(cards)}</div></section>'
        )

    template_path = settings.root / "web_template.html"
    if not template_path.exists():
        template_path = Path(__file__).with_name("web_template.html")
    template = template_path.read_text(encoding="utf-8")
    return (
        template.replace("__TITLE__", html.escape(settings.feed_title))
        .replace(
            "__UPDATED__",
            html.escape(display_time(generated, settings.timezone).strftime("%d %B %Y, %H:%M %Z")),
        )
        .replace("__COUNT__", str(len(selected) + len(videos)))
        .replace("__REPOSITORY_JSON__", json.dumps(os.environ.get("GITHUB_REPOSITORY", "")).replace("</", "<\\/"))
        .replace("__GROUPS__", "".join(groups))
    )


def make_history_html(settings: Settings, releases: list[dict[str, Any]], generated: dt.datetime) -> str:
    """Build the cross-device listening history and rating editor."""
    ratings = load_json(settings.root / "ratings.json", {"ratings": {}})
    blacklist = load_json(settings.blacklist_file, {})
    today = display_time(generated, settings.timezone).date().isoformat()
    catalog: dict[str, dict[str, Any]] = {}
    for release in releases:
        if (
            comparable_date(release.get("date", "")) > today
            or is_compilation_demo_appearance(release)
            or blacklist_reason(release, blacklist)
        ):
            continue
        links = {**fallback_links(release), **release.get("links", {})}
        item_id = f'release:{release["id"]}'
        item_type = "Feature" if release.get("appearance") else display_release_type(release)
        catalog[item_id] = {
            "id": item_id,
            "title": release.get("title", "Untitled release"),
            "artist": release.get("artist", "Unknown artist"),
            "type": item_type,
            "release_date": release.get("date", ""),
            "url": links.get("spotify") or links.get("spotify_search") or release.get("musicbrainz", ""),
            "image": cover_art_url(release),
        }
    decisions = load_json(settings.root / "video_decisions.json", {"rejected": []})
    rejected = set(decisions.get("rejected", []))
    video_state = load_json(settings.root / "data" / "videos.json", {"videos": {}})
    for video_id, video in video_state.get("videos", {}).items():
        if (
            video_id in rejected
            or str(video.get("channel", "")).casefold().endswith(" - topic")
            or is_excluded_video_record(video)
        ):
            continue
        item_id = f"video:{video_id}"
        catalog[item_id] = {
            "id": item_id,
            "title": video.get("title", "Untitled video"),
            "artist": ", ".join(video.get("matched_artists", [])) or video.get("channel", "Unknown channel"),
            "type": "Music Video",
            "release_date": str(video.get("published_at", ""))[:10],
            "url": video.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            "image": video.get("thumbnail", ""),
        }
    template_path = settings.root / "history_template.html"
    if not template_path.exists():
        template_path = Path(__file__).with_name("history_template.html")
    script_json = lambda value: json.dumps(value, ensure_ascii=False).replace("</", "<\\/")
    return (
        template_path.read_text(encoding="utf-8")
        .replace("__TITLE__", html.escape(settings.feed_title))
        .replace("__UPDATED__", html.escape(display_time(generated, settings.timezone).strftime("%d %B %Y, %H:%M %Z")))
        .replace("__DEVICE_AUTH_JS__", device_auth_source(settings))
        .replace("__REPOSITORY_JSON__", script_json(os.environ.get("GITHUB_REPOSITORY", "")))
        .replace("__RATINGS_JSON__", script_json(ratings))
        .replace("__CATALOG_JSON__", script_json(catalog))
    )


def device_auth_source(settings: Settings) -> str:
    """Embed the login helper so navigation never depends on a second web request."""
    source = settings.root / "device_auth.js"
    if not source.exists():
        source = Path(__file__).with_name("device_auth.js")
    content = source.read_text(encoding="utf-8")
    if "</script" in content.casefold():
        raise ValueError("device_auth.js must not contain a closing script tag")
    return content


def copy_device_auth(settings: Settings) -> None:
    """Copy the shared trusted-device helper beside the generated pages."""
    source = settings.root / "device_auth.js"
    if not source.exists():
        source = Path(__file__).with_name("device_auth.js")
    shutil.copyfile(source, settings.output_dir / "device-auth.js")


def make_manage_html(settings: Settings) -> str:
    """Build the static owner editor for the tracked and blocked artist lists."""
    template_path = settings.root / "manage_template.html"
    if not template_path.exists():
        template_path = Path(__file__).with_name("manage_template.html")
    watchlist = load_json(settings.watchlist, {"artists": []})
    blacklist = load_json(
        settings.blacklist_file,
        {"artists": [], "artist_mbids": [], "release_ids": [], "title_contains": []},
    )
    site = load_json(
        settings.root / "site.json",
        {"feed_title": settings.feed_title, "timezone": settings.timezone},
    )
    recent = load_json(
        settings.root / "data" / "lastfm_recent_artists.json",
        {"period": "12month", "minimum_scrobbles": 5, "artists": []},
    )
    aliases = load_json(settings.root / "aliases.json", {"artist_aliases": []})
    unresolved = load_json(settings.root / "data" / "lastfm_unresolved.json", {"artists": []})
    video_sources = load_json(settings.root / "video_sources.json", {"channels": []})
    video_review = load_json(settings.root / "data" / "video_review.json", {"videos": []})
    video_review["videos"] = [
        video for video in video_review.get("videos", [])
        if not is_excluded_video_record(video)
    ]
    video_channel_review = load_json(settings.root / "data" / "video_channel_review.json", {"channels": []})
    video_decisions = load_json(settings.root / "video_decisions.json", {"approved": [], "rejected": []})
    published_videos = [
        video
        for video in load_json(settings.root / "data" / "videos.json", {"videos": {}}).get("videos", {}).values()
        if not str(video.get("channel", "")).casefold().endswith(" - topic")
        and not is_excluded_video_record(video)
    ]
    state = load_json(settings.state_file, {"releases": {}})
    releases = [
        {
            "id": release_id,
            "title": release.get("title") or "Unknown release",
            "artist": release.get("artist") or "Unknown artist",
            "date": release.get("date") or "",
        }
        for release_id, release in state.get("releases", {}).items()
    ]
    releases.sort(key=lambda release: (release["date"], release["artist"], release["title"]), reverse=True)

    def script_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")

    return (
        template_path.read_text(encoding="utf-8")
        .replace("__TITLE__", html.escape(settings.feed_title))
        .replace("__DEVICE_AUTH_JS__", device_auth_source(settings))
        .replace("__REPOSITORY_JSON__", script_json(os.environ.get("GITHUB_REPOSITORY", "")))
        .replace("__WATCHLIST_JSON__", script_json(watchlist))
        .replace("__BLACKLIST_JSON__", script_json(blacklist))
        .replace("__SITE_JSON__", script_json(site))
        .replace("__RECENT_LASTFM_JSON__", script_json(recent))
        .replace("__RELEASES_JSON__", script_json(releases))
        .replace("__ALIASES_JSON__", script_json(aliases))
        .replace("__UNRESOLVED_JSON__", script_json(unresolved))
        .replace("__VIDEO_SOURCES_JSON__", script_json(video_sources))
        .replace("__VIDEO_REVIEW_JSON__", script_json(video_review))
        .replace("__VIDEO_CHANNEL_REVIEW_JSON__", script_json(video_channel_review))
        .replace("__VIDEO_DECISIONS_JSON__", script_json(video_decisions))
        .replace("__PUBLISHED_VIDEOS_JSON__", script_json(published_videos))
    )


def run_check(
    settings: Settings,
    mb: MusicBrainz,
    now: dt.datetime | None = None,
    artist_mbids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Scan every active artist, or only the supplied MusicBrainz IDs."""
    now = now or dt.datetime.now(dt.timezone.utc)
    start = (now.date() - dt.timedelta(days=settings.lookback_days)).isoformat()
    end = (now.date() + dt.timedelta(days=settings.future_days)).isoformat()
    watchlist = load_json(settings.watchlist, {"artists": []}).get("artists", [])
    if artist_mbids is not None:
        watchlist = [artist for artist in watchlist if artist.get("mbid") in artist_mbids]
    state = load_json(settings.state_file, {"releases": {}})
    known: dict[str, dict[str, Any]] = state.setdefault("releases", {})
    discovered: dict[str, dict[str, Any]] = {}
    for watched in watchlist:
        if (
            watched.get("lastfm_scrobbles") is not None
            and int(watched["lastfm_scrobbles"]) < settings.min_lastfm_scrobbles
            and not watched.get("spotify_id")
            and not watched.get("manual_tracking")
        ):
            continue
        mbid = watched.get("mbid")
        if not mbid:
            print(f"Skipping unresolved artist: {watched.get('name', 'Unknown')}", file=sys.stderr)
            continue
        groups = mb.release_groups(mbid, start, end)
        if settings.include_appearances:
            groups.extend(mb.appearance_groups(mbid, start, end))
        for group in groups:
            release = normalize_release(group, watched)
            if release and not (start <= comparable_date(release["date"]) <= end):
                release = None
            if (
                not release
                or (settings.exclude_various_artists and is_various_artists(release))
                or is_compilation_demo_appearance(release)
            ):
                continue
            previous = discovered.get(release["id"])
            if previous:
                # Recording searches overlap primary discographies. A release is
                # an appearance only when every route that found it says so.
                release["appearance"] = bool(previous.get("appearance")) and release["appearance"]
            discovered[release["id"]] = {**(previous or {}), **release}
    new_releases: list[dict[str, Any]] = []
    today = now.date().isoformat()
    for rgid, release in discovered.items():
        is_released = comparable_date(release["date"]) <= today
        if rgid not in known:
            release["first_seen"] = now.isoformat()
            release["notified_released"] = is_released
            try:
                enrich_release(release, mb, now)
            except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                print(f"Metadata lookup failed for {release['title']}: {exc}", file=sys.stderr)
            known[rgid] = release
            if is_released:
                new_releases.append(release)
        else:
            first_seen = known[rgid].get("first_seen")
            links = known[rgid].get("links", {})
            # Existing state predating upcoming-release support has already
            # been reported, so default it to notified to avoid duplicates.
            notified_released = bool(known[rgid].get("notified_released", True))
            known[rgid].update(release)
            known[rgid]["first_seen"] = first_seen
            known[rgid]["links"] = links
            known[rgid]["notified_released"] = notified_released if is_released else False
            if is_released and not notified_released:
                known[rgid]["notified_released"] = True
                try:
                    enrich_release(known[rgid], mb, now)
                except (urllib.error.URLError, urllib.error.HTTPError) as exc:
                    print(f"Metadata refresh failed for {release['title']}: {exc}", file=sys.stderr)
                new_releases.append(known[rgid])
    releases = sorted(known.values(), key=lambda x: (x.get("date", ""), x.get("first_seen", "")), reverse=True)
    visible = visible_releases(settings, releases, now)
    visible_new = visible_releases(settings, new_releases, now)
    state["last_checked"] = now.isoformat()
    save_json(settings.state_file, state)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    released_visible = [release for release in visible if not release.get("upcoming")]
    (settings.output_dir / "feed.xml").write_text(make_rss(settings, released_visible, now), encoding="utf-8")
    (settings.output_dir / "digest.xml").write_text(make_digest_rss(settings, visible, now), encoding="utf-8")
    (settings.output_dir / "index.html").write_text(make_html(settings, visible, now), encoding="utf-8")
    (settings.output_dir / "history.html").write_text(make_history_html(settings, releases, now), encoding="utf-8")
    (settings.output_dir / "manage.html").write_text(make_manage_html(settings), encoding="utf-8")
    copy_device_auth(settings)
    render_video_page(settings.root, settings.output_dir, settings.feed_title, settings.timezone)
    visible_new.sort(key=lambda x: (x.get("date", ""), x.get("artist", "")), reverse=True)
    return visible_new, len(visible_releases(settings, discovered.values(), now))


def rebuild_outputs(settings: Settings, now: dt.datetime | None = None) -> int:
    """Rebuild HTML/RSS from saved state without querying MusicBrainz."""
    now = now or dt.datetime.now(dt.timezone.utc)
    state = load_json(settings.state_file, {"releases": {}})
    releases = sorted(
        state.get("releases", {}).values(),
        key=lambda x: (x.get("date", ""), x.get("first_seen", "")),
        reverse=True,
    )
    today = now.date().isoformat()
    notification_state_changed = False
    for release in releases:
        if comparable_date(release.get("date", "")) > today and release.get("notified_released") is not False:
            release["notified_released"] = False
            notification_state_changed = True
    if notification_state_changed:
        save_json(settings.state_file, state)
    visible = visible_releases(settings, releases, now)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    released_visible = [release for release in visible if not release.get("upcoming")]
    (settings.output_dir / "feed.xml").write_text(make_rss(settings, released_visible, now), encoding="utf-8")
    (settings.output_dir / "digest.xml").write_text(make_digest_rss(settings, visible, now), encoding="utf-8")
    (settings.output_dir / "index.html").write_text(make_html(settings, visible, now), encoding="utf-8")
    (settings.output_dir / "history.html").write_text(make_history_html(settings, releases, now), encoding="utf-8")
    (settings.output_dir / "manage.html").write_text(make_manage_html(settings), encoding="utf-8")
    copy_device_auth(settings)
    render_video_page(settings.root, settings.output_dir, settings.feed_title, settings.timezone)
    return len(visible)


def enrich_saved_releases(
    settings: Settings,
    mb: MusicBrainz,
    refresh: bool = False,
    now: dt.datetime | None = None,
) -> tuple[int, int]:
    """Backfill tracklists and links for released items already in state."""
    now = now or dt.datetime.now(dt.timezone.utc)
    state = load_json(settings.state_file, {"releases": {}})
    known: dict[str, dict[str, Any]] = state.setdefault("releases", {})
    visible = visible_releases(settings, known.values(), now)
    target_ids = [
        release["id"]
        for release in visible
        if not release.get("upcoming") and (refresh or not release.get("metadata_checked_at"))
    ]
    updated = 0
    failed = 0
    for index, rgid in enumerate(target_ids, start=1):
        release = known[rgid]
        try:
            enrich_release(release, mb, now)
            updated += 1
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            failed += 1
            print(f"Metadata lookup failed for {release.get('title', rgid)}: {exc}", file=sys.stderr)
        if index % 10 == 0 or index == len(target_ids):
            save_json(settings.state_file, state)
            print(f"Enriched {index}/{len(target_ids)} saved releases")
    rebuild_outputs(settings, now)
    return updated, failed


def best_artist(name: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    exact = [x for x in candidates if x.get("name", "").casefold() == name.casefold()]
    return max(exact or candidates, key=lambda x: int(x.get("score", 0)))


def add_artist(
    settings: Settings,
    mb: MusicBrainz,
    name: str,
    mbid: str | None = None,
    spotify_id: str | None = None,
) -> dict[str, Any]:
    if mbid:
        chosen = {"id": mbid, "name": name, "score": 100}
    else:
        chosen = best_artist(name, mb.search_artists(name))
        if not chosen:
            raise ValueError(f"No MusicBrainz artist found for {name!r}")
    blocked = artist_blacklist_reason(
        chosen.get("name", name), chosen["id"], load_json(settings.blacklist_file, {})
    )
    if blocked:
        raise ValueError(f"Artist is blocked by {blocked}; unblock them before adding")
    data = load_json(settings.watchlist, {"artists": []})
    artists = data.setdefault("artists", [])
    entry = {"name": chosen.get("name", name), "mbid": chosen["id"]}
    if spotify_id:
        entry["spotify_id"] = spotify_id
    if not any(x.get("mbid") == entry["mbid"] for x in artists):
        artists.append(entry)
        artists.sort(key=lambda x: x["name"].casefold())
        save_json(settings.watchlist, data)
    elif spotify_id:
        for existing in artists:
            if existing.get("mbid") == entry["mbid"] and not existing.get("spotify_id"):
                existing["spotify_id"] = spotify_id
                save_json(settings.watchlist, data)
                break
    return entry


def import_csv(
    settings: Settings,
    mb: MusicBrainz,
    path: Path,
    min_plays: int = 0,
) -> tuple[int, list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        artist_columns = [c for c in reader.fieldnames if "artist" in c.casefold() and "id" not in c.casefold()]
        if not artist_columns:
            raise ValueError("Could not find a column containing 'artist'")
        artist_column = next((c for c in artist_columns if c.casefold() == "artists"), artist_columns[0])
        id_column = next((c for c in reader.fieldnames if c.casefold() == "artist ids"), None)
        plays_column = next(
            (c for c in reader.fieldnames if any(word in c.casefold() for word in ("scrobble", "playcount", "plays"))),
            None,
        )
        identities: dict[str, str | None] = {}
        for row in reader:
            if plays_column and min_plays:
                digits = re.sub(r"\D", "", row.get(plays_column, ""))
                if not digits or int(digits) < min_plays:
                    continue
            raw = row.get(artist_column, "").strip()
            spotify_ids = [x.strip() for x in row.get(id_column, "").split(",") if x.strip()] if id_column else []
            # Spotify Release List joins multiple artist names with commas. A comma
            # can also be part of one artist's name (for example nothing,nowhere.),
            # so only split when the parallel Spotify ID list proves it is a credit list.
            candidate_names = [x.strip() for x in raw.split(",")]
            if len(spotify_ids) > 1 and len(candidate_names) == len(spotify_ids):
                pairs = zip(candidate_names, spotify_ids)
            else:
                pairs = [(raw, spotify_ids[0] if len(spotify_ids) == 1 else None)]
            for name, spotify_id in pairs:
                if name and name.casefold() != "various artists":
                    identities.setdefault(name, spotify_id)
    added = 0
    unresolved: list[str] = []
    for name in sorted(identities, key=str.casefold):
        try:
            add_artist(settings, mb, name, spotify_id=identities[name])
            added += 1
            print(f"Added {name}")
        except (ValueError, urllib.error.URLError, urllib.error.HTTPError):
            unresolved.append(name)
    return added, unresolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search-artist", help="Find an artist's MusicBrainz ID")
    search.add_argument("name")
    add = sub.add_parser("add", help="Add an artist to the watchlist")
    add.add_argument("name")
    add.add_argument("--mbid")
    add.add_argument("--spotify-id", help="Optional Spotify artist ID to retain for cross-service matching")
    imp = sub.add_parser("import-csv", help="Import unique artists from a Spotify Release List CSV")
    imp.add_argument("path", type=Path)
    imp.add_argument("--min-plays", type=int, default=0, help="Skip rows below this play/scrobble count")
    lastfm = sub.add_parser("import-lastfm", help="Import a Last.fm user's artist library")
    lastfm.add_argument("user")
    lastfm.add_argument("--min-plays", type=int, default=20)
    lastfm.add_argument("--dry-run", action="store_true", help="Show threshold counts without changing the watchlist")
    sub.add_parser("sync-lastfm", help="Import the optional Last.fm account configured in site.json")
    check = sub.add_parser("check", help="Check releases and rebuild RSS/HTML")
    check.add_argument("--quiet-if-none", action="store_true", help="Print nothing when no releases are new")
    check.add_argument("--notification-file", type=Path, help="Write GitHub-ready Markdown when new releases are found")
    check.add_argument(
        "--artist-mbids",
        help="Comma-separated MusicBrainz artist IDs to scan instead of the full watchlist",
    )
    changed = sub.add_parser("changed-artists", help="List watchlist IDs added since an earlier artists.json")
    changed.add_argument("previous", type=Path)
    sub.add_parser("state-count", help="Print the number of releases in saved state")
    sub.add_parser("digest-due", help="Print true during the configured timezone's 6am hour")
    sub.add_parser("rebuild", help="Rebuild RSS/HTML from saved releases without an API scan")
    enrich = sub.add_parser("enrich", help="Backfill RSS tracklists and artwork metadata")
    enrich.add_argument("--refresh", action="store_true", help="Refresh metadata even when already checked")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    settings = Settings.load(args.config.resolve())
    mb = MusicBrainz(settings.contact)
    if args.command == "search-artist":
        for item in mb.search_artists(args.name):
            place = item.get("disambiguation") or item.get("country") or ""
            print(f"{item['id']}\t{item['name']}\t{place}\tscore={item.get('score', 0)}")
    elif args.command == "add":
        entry = add_artist(settings, mb, args.name, args.mbid, args.spotify_id)
        print(f"Watching {entry['name']} ({entry['mbid']})")
    elif args.command == "import-csv":
        added, unresolved = import_csv(settings, mb, args.path, args.min_plays)
        print(f"Imported {added} artists; unresolved: {len(unresolved)}")
        if unresolved:
            print("Unresolved: " + ", ".join(unresolved), file=sys.stderr)
    elif args.command == "import-lastfm":
        api_key = os.environ.get("LASTFM_API_KEY")
        if not api_key:
            raise SystemExit("Set LASTFM_API_KEY in the environment for this command.")
        if args.dry_run:
            source = fetch_lastfm_artists(args.user, api_key)
            counts = {threshold: sum(int(x.get("playcount", 0)) >= threshold for x in source) for threshold in (1, 5, 10, 20, 50, 100)}
            print(f"Last.fm library: {len(source)} artists")
            for threshold, count in counts.items():
                print(f"At least {threshold} scrobbles: {count}")
        else:
            added, unresolved, total = import_lastfm(settings, mb, args.user, api_key, args.min_plays)
            save_lastfm_unresolved(settings, unresolved)
            print(f"Imported/updated {added} of {total} Last.fm artists; unresolved: {len(unresolved)}")
            if unresolved:
                print("Unresolved: " + ", ".join(unresolved), file=sys.stderr)
    elif args.command == "sync-lastfm":
        api_key = os.environ.get("LASTFM_API_KEY", "").strip()
        if not settings.lastfm_username:
            print("Last.fm sync skipped: no username configured.")
        elif not api_key:
            print("Last.fm sync skipped: LASTFM_API_KEY is not configured.")
        else:
            processed, unresolved, total = import_lastfm(
                settings,
                mb,
                settings.lastfm_username,
                api_key,
                settings.min_lastfm_scrobbles,
            )
            recent, recent_unresolved = build_recent_lastfm_candidates(
                settings,
                mb,
                settings.lastfm_username,
                api_key,
                5,
            )
            save_lastfm_unresolved(settings, [*unresolved, *recent_unresolved])
            print(f"Synced {processed} of {total} Last.fm artists; unresolved: {len(unresolved)}")
            print(
                f"Prepared {len(recent)} recent favourites for review; "
                f"unresolved: {len(recent_unresolved)}"
            )
    elif args.command == "changed-artists":
        previous = load_json(args.previous, {"artists": []})
        current = load_json(settings.watchlist, {"artists": []})
        old_ids = {artist.get("mbid") for artist in previous.get("artists", []) if artist.get("mbid")}
        new_ids = sorted(
            artist["mbid"]
            for artist in current.get("artists", [])
            if artist.get("mbid") and artist["mbid"] not in old_ids
        )
        print(",".join(new_ids))
    elif args.command == "state-count":
        state = load_json(settings.state_file, {"releases": {}})
        print(len(state.get("releases", {})))
    elif args.command == "digest-due":
        print("true" if digest_due(settings) else "false")
    elif args.command == "check":
        selected_mbids = None
        if args.artist_mbids is not None:
            selected_mbids = {value.strip() for value in args.artist_mbids.split(",") if value.strip()}
        new_releases, current = run_check(settings, mb, artist_mbids=selected_mbids)
        if args.notification_file and args.notification_file.exists():
            args.notification_file.unlink()
        if new_releases:
            print(f"Found {len(new_releases)} new release(s):")
            for release in new_releases:
                labels = [display_release_type(release), *release["secondary_types"]]
                links = {**fallback_links(release), **release["links"]}
                print(f"- {release['artist']} — {release['title']} ({' · '.join(dict.fromkeys(labels))}) — {release['date']}")
                print(f"  Spotify: {links.get('spotify') or links['spotify_search']}")
                print(f"  YouTube Music: {links.get('youtube_music') or links['youtube_music_search']}")
            if args.notification_file and settings.github_issue_notifications:
                args.notification_file.write_text(
                    notification_markdown(new_releases),
                    encoding="utf-8",
                )
        elif not args.quiet_if_none:
            print(f"No new releases. {current} recent release(s) matched. Feed: {settings.output_dir / 'feed.xml'}")
    elif args.command == "rebuild":
        count = rebuild_outputs(settings)
        print(f"Rebuilt feed and webpage with {count} visible release(s).")
    elif args.command == "enrich":
        updated, failed = enrich_saved_releases(settings, mb, args.refresh)
        print(f"Enriched {updated} release(s); failures: {failed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
