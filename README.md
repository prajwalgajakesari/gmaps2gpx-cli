# gmaps2gpx

Convert Google Maps direction URLs to GPX files with a single command.

## Features

- **Shortened URLs** - Paste `maps.app.goo.gl` links directly
- **Dragged routes** - Preserves via-points when you drag a route on Google Maps
- **Motorcycle mode** - Two-wheeler routing via Google Routes API (great for India/SE Asia)
- **Alternative routes** - `--shortest` picks the shortest route by distance
- **Batch convert** - Pass multiple URLs at once
- **All travel modes** - driving, walking, bicycling, transit, motorcycle

## Install

```bash
# From PyPI
pip install gmaps2gpx

# Or with pipx (recommended - isolated install)
pipx install gmaps2gpx

# From source
git clone https://github.com/prajwalgajakesari/gmaps2gpx-cli.git
cd gmaps2gpx
pip install .
```

## Setup

You need a Google Maps API key with **Directions API** enabled. For motorcycle mode, also enable the **Routes API**.

```bash
# Set it once (add to your .bashrc/.zshrc)
export GOOGLE_MAPS_API_KEY="your_key_here"
```

Or pass it each time with `-k YOUR_KEY`.

### Getting an API key

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a project (or select existing)
3. Enable **Directions API** (and **Routes API** for motorcycle mode)
4. Create an API key under Credentials
5. (Optional) Restrict the key to Directions API + Routes API

## Usage

```bash
# Basic - paste any Google Maps directions link
gmaps2gpx 'https://maps.app.goo.gl/Mz9Q47fcBMHLa2HB7'

# Save to specific file
gmaps2gpx 'https://maps.app.goo.gl/abc123' -o ride.gpx

# Motorcycle / two-wheeler mode (uses Google Routes API)
gmaps2gpx 'https://maps.app.goo.gl/abc123' -m motorcycle -o ride.gpx

# Pick the shortest route from alternatives
gmaps2gpx 'https://maps.app.goo.gl/abc123' --shortest

# Full Google Maps URL works too
gmaps2gpx 'https://www.google.com/maps/dir/Mumbai/Goa' -o mumbai_goa.gpx

# Walking directions
gmaps2gpx 'https://maps.app.goo.gl/abc123' -m walking

# Batch convert multiple routes
gmaps2gpx URL1 URL2 URL3

# Pass API key directly
gmaps2gpx 'https://maps.app.goo.gl/abc123' -k YOUR_API_KEY
```

## Options

```
positional arguments:
  urls                    one or more Google Maps direction URLs

options:
  -k, --api-key KEY       Google Maps API key (or set GOOGLE_MAPS_API_KEY env var)
  -o, --output FILE       output GPX filename (auto-generated if omitted)
  -m, --mode MODE         travel mode: driving, walking, bicycling, transit, motorcycle
  -s, --shortest          fetch alternatives and pick the shortest by distance
  -h, --help              show help
```

## How it works

1. Resolves shortened Google Maps URLs
2. Parses origin, destination, waypoints, and dragged via-points from the URL
3. Calls Google Directions API (or Routes API for motorcycle mode)
4. Decodes polylines into GPS coordinates
5. Generates a GPX 1.1 file with track points and waypoint markers

## Publishing to PyPI

One-time setup:

```bash
# Install build tools
pip install build twine

# Create a PyPI account at https://pypi.org/account/register/
# Generate an API token at https://pypi.org/manage/account/
```

To publish:

```bash
# Build the package
python -m build

# Upload to PyPI
twine upload dist/*

# You'll be prompted for credentials:
#   Username: __token__
#   Password: pypi-YOUR_API_TOKEN
```

After publishing, anyone can install with:

```bash
pip install gmaps2gpx
```

## License

MIT
