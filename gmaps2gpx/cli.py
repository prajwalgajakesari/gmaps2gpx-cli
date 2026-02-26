"""
gmaps2gpx - Convert Google Maps direction URLs to GPX files.

Usage:
    gmaps2gpx <google_maps_url> [options]

Setup:
    pipx install .
    export GOOGLE_MAPS_API_KEY="your_key_here"
"""

import re
import sys
import os
import argparse
import requests
from urllib.parse import urlparse, unquote
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 1. URL Parsing
# ---------------------------------------------------------------------------

def resolve_short_url(url: str) -> str:
    """Resolve shortened Google Maps URLs (goo.gl, maps.app.goo.gl)."""
    if "goo.gl" in url or "maps.app" in url:
        resp = requests.head(url, allow_redirects=True, timeout=10)
        return resp.url
    return url


def parse_google_maps_url(url: str) -> dict:
    """
    Extract origin, destination, and waypoints from a Google Maps directions URL.

    Supports:
        - https://www.google.com/maps/dir/Place+A/Place+B/Place+C
        - https://www.google.com/maps/dir/lat,lng/lat,lng
        - https://maps.app.goo.gl/xxxxx (shortened)
        - Dragged via-points embedded in the data= parameter
    """
    url = resolve_short_url(url)
    parsed = urlparse(url)
    # Split on raw path BEFORE unquoting — %2F in place names stays intact
    path = parsed.path

    dir_match = re.search(r'/maps/dir/(.+?)(?:/@|$|\?)', path)
    if not dir_match:
        dir_match = re.search(r'/maps/dir/(.+)', path)

    if not dir_match:
        raise ValueError(
            "Could not parse directions from this URL.\n"
            "Make sure it's a Google Maps directions link (contains '/maps/dir/')."
        )

    segments = [s.strip() for s in dir_match.group(1).split('/') if s.strip()]

    clean_segments = []
    for seg in segments:
        if seg.startswith('@'):
            break
        seg = re.split(r'@', seg)[0].strip()
        if seg:
            clean_segments.append(unquote(seg))

    if len(clean_segments) < 2:
        raise ValueError("Need at least an origin and destination. Found: " + str(clean_segments))

    # Extract dragged via-points from the data= parameter.
    # Google Maps encodes them as: !3mN!1m2!1d<lng>!2d<lat>
    via_waypoints = []
    data_match = re.search(r'data=([^&]+)', url)
    if data_match:
        data_str = unquote(data_match.group(1))
        via_points = re.findall(r'!3m\d+!1m2!1d([\d.]+)!2d([\d.]+)', data_str)
        for lng, lat in via_points:
            via_waypoints.append(f"{lat},{lng}")

    path_waypoints = clean_segments[1:-1] if len(clean_segments) > 2 else []
    all_waypoints = path_waypoints + via_waypoints

    result = {
        "origin": clean_segments[0],
        "destination": clean_segments[-1],
        "waypoints": all_waypoints
    }

    print(f"  Origin:      {result['origin']}")
    print(f"  Destination: {result['destination']}")
    if result['waypoints']:
        print(f"  Waypoints:   {', '.join(result['waypoints'])}")

    return result


# ---------------------------------------------------------------------------
# 2. Google Directions API
# ---------------------------------------------------------------------------

def get_directions(origin: str, destination: str, waypoints: list, api_key: str,
                   mode: str = "driving", alternatives: bool = False) -> dict:
    """Call Google Directions API and return the response."""
    if mode == "motorcycle":
        return _get_directions_routes_api(origin, destination, waypoints, api_key, alternatives)

    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "key": api_key,
    }
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    if alternatives:
        params["alternatives"] = "true"

    resp = requests.get(
        "https://maps.googleapis.com/maps/api/directions/json",
        params=params,
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()

    if data["status"] != "OK":
        raise RuntimeError(f"Directions API error: {data['status']} — {data.get('error_message', '')}")

    return data


def _geocode(place: str, api_key: str) -> dict:
    """Geocode a place name or pass through lat,lng coordinates."""
    if re.match(r'^-?\d+\.?\d*,-?\d+\.?\d*$', place.strip()):
        lat, lng = place.strip().split(',')
        return {"lat": float(lat), "lng": float(lng)}

    resp = requests.get(
        "https://maps.googleapis.com/maps/api/geocode/json",
        params={"address": place, "key": api_key},
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    if data["status"] != "OK" or not data["results"]:
        raise RuntimeError(f"Geocode failed for '{place}': {data['status']}")
    return data["results"][0]["geometry"]["location"]


def _get_directions_routes_api(origin: str, destination: str, waypoints: list,
                                api_key: str, alternatives: bool) -> dict:
    """
    Use Google Routes API (v2) for TWO_WHEELER mode.
    Returns data in the same format as the legacy Directions API.
    """
    print("  (using Routes API for motorcycle/two-wheeler mode)")

    origin_loc = _geocode(origin, api_key)
    dest_loc = _geocode(destination, api_key)

    body = {
        "origin": {"location": {"latLng": {"latitude": origin_loc["lat"], "longitude": origin_loc["lng"]}}},
        "destination": {"location": {"latLng": {"latitude": dest_loc["lat"], "longitude": dest_loc["lng"]}}},
        "travelMode": "TWO_WHEELER",
        "computeAlternativeRoutes": alternatives,
    }

    if waypoints:
        intermediates = []
        for wp in waypoints:
            loc = _geocode(wp, api_key)
            intermediates.append({"location": {"latLng": {"latitude": loc["lat"], "longitude": loc["lng"]}}})
        body["intermediates"] = intermediates

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.legs.steps.polyline,routes.legs.distanceMeters,routes.legs.duration,routes.legs.startLocation,routes.legs.endLocation,routes.description"
    }

    resp = requests.post(
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        json=body,
        headers=headers,
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("routes"):
        raise RuntimeError("Routes API returned no routes")

    # Convert Routes API response to legacy Directions API format
    converted = {"routes": []}
    for route in data["routes"]:
        legs = []
        for leg in route["legs"]:
            steps = []
            for step in leg.get("steps", []):
                poly = step.get("polyline", {}).get("encodedPolyline", "")
                steps.append({"polyline": {"points": poly}})

            dur_str = leg.get("duration", "0s")
            dur_secs = int(dur_str.rstrip("s")) if isinstance(dur_str, str) else 0

            start = leg.get("startLocation", {}).get("latLng", {})
            end = leg.get("endLocation", {}).get("latLng", {})

            legs.append({
                "distance": {"value": leg.get("distanceMeters", 0), "text": f"{leg.get('distanceMeters', 0)/1000:.1f} km"},
                "duration": {"value": dur_secs, "text": f"{dur_secs//60} mins"},
                "start_location": {"lat": start.get("latitude", 0), "lng": start.get("longitude", 0)},
                "end_location": {"lat": end.get("latitude", 0), "lng": end.get("longitude", 0)},
                "steps": steps,
            })
        converted["routes"].append({
            "legs": legs,
            "summary": route.get("description", ""),
        })

    return converted


# ---------------------------------------------------------------------------
# 3. Polyline Decoding
# ---------------------------------------------------------------------------

def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline into (lat, lng) tuples."""
    points = []
    index = 0
    lat = 0
    lng = 0

    while index < len(encoded):
        for attr in ('lat', 'lng'):
            shift = 0
            result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if attr == 'lat':
                lat += delta
            else:
                lng += delta

        points.append((lat / 1e5, lng / 1e5))

    return points


# ---------------------------------------------------------------------------
# 4. GPX Generation
# ---------------------------------------------------------------------------

def escape_xml(text: str) -> str:
    """Escape special XML characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def build_gpx(points: list[tuple[float, float]], route_name: str = "Google Maps Route",
              legs: list = None) -> str:
    """Build a GPX 1.1 XML string from (lat, lng) points."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="gmaps2gpx"',
        '     xmlns="http://www.topografix.com/GPX/1/1"',
        '     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '     xsi:schemaLocation="http://www.topografix.com/GPX/1/1',
        '     http://www.topografix.com/GPX/1/1/gpx.xsd">',
        '  <metadata>',
        f'    <name>{escape_xml(route_name)}</name>',
        f'    <time>{now}</time>',
        '  </metadata>',
    ]

    if legs:
        start = legs[0]["start_location"]
        start_name = legs[0].get("start_address", "Start")
        lines.append(f'  <wpt lat="{start["lat"]}" lon="{start["lng"]}">')
        lines.append(f'    <name>{escape_xml(start_name)}</name>')
        lines.append('  </wpt>')

        for i, leg in enumerate(legs):
            end = leg["end_location"]
            end_name = leg.get("end_address", f"Stop {i+1}")
            lines.append(f'  <wpt lat="{end["lat"]}" lon="{end["lng"]}">')
            lines.append(f'    <name>{escape_xml(end_name)}</name>')
            lines.append('  </wpt>')

    lines.append('  <trk>')
    lines.append(f'    <name>{escape_xml(route_name)}</name>')
    lines.append('    <trkseg>')

    for lat, lng in points:
        lines.append(f'      <trkpt lat="{lat:.6f}" lon="{lng:.6f}"></trkpt>')

    lines.append('    </trkseg>')
    lines.append('  </trk>')
    lines.append('</gpx>')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. Main Pipeline
# ---------------------------------------------------------------------------

def convert_url_to_gpx(url: str, api_key: str, output_path: str = None,
                        mode: str = "driving", shortest: bool = False) -> str:
    """Full pipeline: Google Maps URL -> GPX file."""
    print(f"\n{'='*60}")
    print(f"Converting: {url}")
    print(f"{'='*60}")

    print("\n[1/4] Parsing Google Maps URL...")
    route = parse_google_maps_url(url)

    print("\n[2/4] Fetching directions from Google API...")
    data = get_directions(
        origin=route["origin"],
        destination=route["destination"],
        waypoints=route["waypoints"],
        api_key=api_key,
        mode=mode,
        alternatives=shortest
    )

    routes = data["routes"]
    if shortest and len(routes) > 1:
        print(f"\n  Found {len(routes)} alternative routes:")
        for i, r in enumerate(routes):
            d = sum(leg["distance"]["value"] for leg in r["legs"])
            t = sum(leg["duration"]["value"] for leg in r["legs"])
            summary = r.get("summary", "N/A")
            print(f"    {i+1}. {summary}: {d/1000:.1f} km, {t//3600}h {(t%3600)//60}m")
        chosen_idx = min(range(len(routes)),
                         key=lambda i: sum(leg["distance"]["value"] for leg in routes[i]["legs"]))
        chosen = routes[chosen_idx]
        print(f"  -> Picking route {chosen_idx+1} (shortest)")
    else:
        chosen = routes[0]

    print("\n[3/4] Decoding route polylines...")
    all_points = []
    legs = []
    total_distance = 0
    total_duration = 0

    for leg in chosen["legs"]:
        legs.append(leg)
        total_distance += leg["distance"]["value"]
        total_duration += leg["duration"]["value"]
        for step in leg["steps"]:
            encoded = step["polyline"]["points"]
            points = decode_polyline(encoded)
            all_points.extend(points)

    print(f"  Total points:   {len(all_points)}")
    print(f"  Total distance: {total_distance / 1000:.1f} km ({total_distance / 1609.34:.1f} mi)")
    print(f"  Est. duration:  {total_duration // 3600}h {(total_duration % 3600) // 60}m")

    print("\n[4/4] Generating GPX file...")
    route_name = f"{route['origin']} to {route['destination']}"
    gpx_content = build_gpx(all_points, route_name=route_name, legs=legs)

    if not output_path:
        safe_name = re.sub(r'[^\w\-]', '_', f"{route['origin']}_to_{route['destination']}")
        safe_name = re.sub(r'_+', '_', safe_name)[:80]
        output_path = f"{safe_name}.gpx"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(gpx_content)

    print(f"\n  Saved: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert Google Maps direction URLs to GPX files.",
        epilog=(
            "Examples:\n"
            "  gmaps2gpx 'https://maps.app.goo.gl/abc123'\n"
            "  gmaps2gpx 'https://www.google.com/maps/dir/Mumbai/Goa' -o ride.gpx\n"
            "  gmaps2gpx URL1 URL2 URL3  # batch convert\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "urls",
        nargs="+",
        help="one or more Google Maps direction URLs"
    )
    parser.add_argument(
        "-k", "--api-key",
        default=os.environ.get("GOOGLE_MAPS_API_KEY"),
        help="Google Maps API key (or set GOOGLE_MAPS_API_KEY env var)"
    )
    parser.add_argument(
        "-o", "--output",
        help="output GPX filename (auto-generated if omitted, single URL only)"
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["driving", "walking", "bicycling", "transit", "motorcycle"],
        default="driving",
        help="travel mode (default: driving). 'motorcycle' uses Google Routes API TWO_WHEELER mode"
    )
    parser.add_argument(
        "-s", "--shortest",
        action="store_true",
        help="fetch alternative routes and pick the shortest by distance"
    )

    args = parser.parse_args()

    if not args.api_key:
        print("Error: No API key provided.")
        print("  Set via env:  export GOOGLE_MAPS_API_KEY='your_key'")
        print("  Or pass flag: gmaps2gpx --api-key YOUR_KEY <url>")
        sys.exit(1)

    output_files = []
    for url in args.urls:
        out = args.output if (args.output and len(args.urls) == 1) else None
        try:
            path = convert_url_to_gpx(url, args.api_key, output_path=out,
                                       mode=args.mode, shortest=args.shortest)
            output_files.append(path)
        except Exception as e:
            print(f"\n  Failed: {e}")

    if output_files:
        print(f"\n{'='*60}")
        print(f"Done! Generated {len(output_files)} GPX file(s):")
        for f in output_files:
            print(f"  - {f}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
