# GPX Appender

A QGIS plugin (3.34+ / 4.x) that appends GPX data directly into existing
project layers via a dockable drag-and-drop panel.

## Features

- **Drag & drop** GPX files or entire folders onto the panel (or click to browse)
- **Multi-file / multi-folder** — drop 20 folders at once, all GPX files inside are found recursively
- **Destination layer picker** — choose any Point or Line vector layer in your project
- **Smart geometry import**
  - Point layer → imports waypoints or track-points as individual points
  - Line layer → imports tracks/routes as linestrings
  - Z and ZM layers fully supported (elevation preserved from GPX)
- **Field mapping** — for each destination field, choose the value source:
  - *From GPX* — pick any standard GPX attribute (ele, time, name, desc, sat, hdop, …)
  - *Layer pick* — stamp a specific value from another layer (e.g. Incident ID)
  - *Expression* — any QGIS expression, with full expression builder (e.g. `epoch(now())`)
  - *Parent folder* — uses the GPX file's parent folder name (great for batch imports where folder = person/team name)
  - *Ignore* — leave the field blank
- **Mappings saved per layer** — switch destination layers and each remembers its own mapping
- **Progress bar + Stop button** — for large files with tens of thousands of track points
- **fid-safe** — never overwrites your layer's primary key unless you explicitly map it

## Installation

1. Download the zip from the [releases page](https://github.com/tyhol/www.dontknowyet/releases)
2. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**
3. Select the downloaded zip and click **Install Plugin**

## Usage

1. Click the **GPX Appender** toolbar button to open the panel
2. Select your destination layer from the dropdown
3. Optionally switch to the **Field Mapping** tab to configure which GPX attributes go where
4. Drag GPX files or folders onto the drop zone (or click to browse)
5. Watch the progress bar — hit **Stop** if needed

## License

GPLv2 or later — see [LICENSE](LICENSE)
