# Floodmap

A flood risk map for San Francisco. Live at https://isahouh.github.io/Floodmap/ (GitHub Pages serves `index.html` from `main`).

## Where things stand (Nov 21, 2026)

**Built and live: `index.html`**
- One self-contained page. Leaflet is inlined. No build step.
- Ground heights come from Mapzen terrarium tiles on Amazon (`s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`, height in meters = R*256 + G + B/256 - 32768, max zoom 15).
- Shades every pixel whose ground is at or below a water height. Tap the map to read ground height.
- Loads tide predictions for the nearest tide station (National Oceanic and Atmospheric Administration, high and low points joined by a cosine curve) and the hourly rain forecast (Open-Meteo). A time slider sets the water height from the tide at that hour.
- Rain is drawn on the chart only. It does not change the shading yet.
- Tested only with mocked data in headless Chrome. The owner has loaded the live page on his phone.

**Not built: the rain plus tide simulation.** This is the next job.

## The model to build

Water balance on the ground-height grid. Each cell holds depth `h`. Each edge between cells holds flow `q` per unit width.

```
q <- (q - g*h*dt*S) / (1 + g*dt*n^2*|q| / h^(7/3))      # S = water surface slope, n = roughness (~0.015 asphalt)
h <- h + dt*( r - d + (q_in - q_out)/dx )               # r = rain rate * runoff fraction
d  = min( d_max, k*sqrt(max(0, z + h - T(t))) )         # drain term, T(t) = tide height at time t
```

- Time step limit: `dt < 0.7*dx / sqrt(g*h_max)`.
- Shoreline cells are held at the tide level `T(t)`.
- Apply the drain term only at cells that contain a storm drain (`data/storm_drains.csv`).
- Unknowns to fit: drain capacity `d_max` (start with one value per drainage basin), outlet constant `k`. Fix the runoff fraction from land cover, because it trades off against `d_max`.
- The city says its sewers handle a 5-year storm, and the 5-year 3-hour storm makes about 1.14 inches of runoff. Use that as the starting `d_max`.
- No public dataset of sewer pipes (sizes, slopes) was found. That is why pipe capacity is fitted.

## Testing against past floods

- Run a past storm with measured rain and measured tide.
- Score per city block and storm: hits / (hits + misses + false alarms), model wet versus 311 report present.
- Fit on half the storms, score on the other half.
- Include heavy-rain days that had few reports.
- Tide check: compare storms with similar rain at high tide versus low tide. Reports near the shore should differ.
- Second check: run a 100-year storm and compare with `data/city_100yr_flood_zone.geojson` (the city's own model, rain only, 6 inches deep or more).

Largest days by 311 flooding reports: 2026-11-18 (778), 2022-12-31 (560), 2019-12-07 (393), 2023-01-10 (371), 2021-10-24 (370), 2024-11-22 (333). 84 days have 50 or more.

## Data (in `data/`, written by `data/fetch.py`)

`data/fetch.py` runs in GitHub Actions (`.github/workflows/fetch-data.yml`) on any push that changes it, and commits results. It skips files that already exist unless run with `--all`. Read `data/fetch_log.txt` for the last run. Run it locally the same way: `python data/fetch.py`.

| File | Contents |
|---|---|
| `311_flooding.csv` | 171,773 sewer-related 311 cases since July 2008. Flooding reports are `service_name` starting with "Sewer" and `service_subtype` equal to "flooding" in any letter case: 33,051 rows, 31,540 with a location. `lat`/`long` of 0 means no location. Times look like local time. |
| `311_categories.csv` | Counts by category, used to choose the filter above. |
| `tide_hourly_9414290.csv` | Measured hourly water level at the San Francisco gauge, 2008 to now, meters above mean lower low water, GMT. Includes storm surge. |
| `tide_datums_9414290.json` | Datum table. Tide zero is 0.006 m below the ground-height zero (NAVD88) at this gauge. |
| `rain_sf_downtown.csv` | Downtown San Francisco gauge, roughly hourly since May 2015. The rain column is a running total in millimeters. Difference it, and treat drops as gauge resets. |
| `rain_gauge_SFO.csv`, `_OAK`, `_HAF` | Airport gauges, hourly, only hours with rain, inches, UTC. |
| `rain_model_*.csv` | Open-Meteo weather-model reconstruction, hourly millimeters, GMT. Coarse. It smooths out short bursts. |
| `storm_drains.csv` | City storm drain locations (about 23,900). |
| `city_100yr_flood_zone.geojson` | City 100-year storm flood zone boundary. |
| `dem/14/{x}/{y}.png` | Terrarium ground-height tiles covering the city at zoom 14, about 7.5 m per pixel. `dem/index.json` has the tile range. |

Known gaps:
- The federal 15-minute rain gauge archive fetch failed (station list address was wrong). Short bursts matter for street flooding, so finer rain data is worth finding. The city utility runs neighborhood rain gauges, and that data has not been located.
- Rain before May 2015 inside the city is only available from the airports and the weather model.

## Plan from here

1. Build the simulation offline in Python, on the graphics card if there is one (the update is a stencil over a 2-D array, so PyTorch or CuPy fits). Assemble the zoom-14 tiles into one grid first.
2. Run 2026-11-18 and compare with the 778 reports.
3. Fit and hold-out test across the storms listed above.
4. Ship the fitted numbers with the page, and run a lighter version of the simulation in the browser from the rain forecast and tide prediction for the chosen time.

## Owner preferences

- Plain, short sentences. No acronyms: spell terms out. No jargon.
- Feet and inches first for display, with meters available.
- He reads on his phone. The page must work in mobile Safari.
- Commit to `main`. Pages redeploys on push.
