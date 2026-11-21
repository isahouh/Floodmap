"""Download the records needed to test a flood model for San Francisco.

Runs inside GitHub Actions. Every dataset is fetched on its own, and a failure in one
is written to data/fetch_log.txt without stopping the others.
"""
import csv, io, json, math, os, sys, time, traceback, urllib.parse, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = []
UA = {"User-Agent": "floodmap-data-fetch (github.com/isahouh/Floodmap)"}


def get(url, tries=4, timeout=120):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa
            last = e
            time.sleep(3 * (i + 1))
    raise last


def log(msg):
    print(msg, flush=True)
    LOG.append(msg)


def step(name, fn):
    try:
        fn()
        log("OK   " + name)
    except Exception as e:  # noqa
        log("FAIL " + name + ": " + repr(e))
        traceback.print_exc()


# ---------------------------------------------------------------- 311 flooding cases
SODA = "https://data.sfgov.org/resource/vw6y-z8j6"
WHERE = ("lower(service_subtype) like '%flood%' OR lower(service_details) like '%flood%' "
         "OR lower(service_name) like '%flood%' OR lower(service_name) like '%sewer%'")
FIELDS = "service_request_id,requested_datetime,service_name,service_subtype,service_details,address,lat,long,source"


def fetch_311():
    # category counts first, so the right filter can be chosen later
    q = urllib.parse.urlencode({"$select": "service_name,service_subtype,count(*) as n", "$where": WHERE,
                                "$group": "service_name,service_subtype", "$order": "n DESC", "$limit": 5000})
    open(os.path.join(HERE, "311_categories.csv"), "wb").write(get(SODA + ".csv?" + q))

    rows, header, offset, page = [], None, 0, 50000
    select = FIELDS
    while True:
        params = {"$where": WHERE, "$order": "service_request_id", "$limit": page, "$offset": offset}
        if select:
            params["$select"] = select
        try:
            raw = get(SODA + ".csv?" + urllib.parse.urlencode(params))
        except Exception:
            if select and offset == 0:      # a field name was wrong: fall back to every column
                select = None
                continue
            raise
        part = list(csv.reader(io.StringIO(raw.decode("utf-8", "replace"))))
        if not part:
            break
        if header is None:
            header = part[0]
        rows.extend(part[1:])
        log("  311 rows so far: %d" % len(rows))
        if len(part) - 1 < page:
            break
        offset += page
    with open(os.path.join(HERE, "311_flooding.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# ---------------------------------------------------------------- measured water level, San Francisco gauge
def fetch_tide():
    out = [["time_gmt", "water_level_m_mllw"]]
    this_year = datetime.date.today().year
    for y in range(2008, this_year + 1):
        end = "%d1231" % y if y < this_year else datetime.date.today().strftime("%Y%m%d")
        url = ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=hourly_height&application=floodmap"
               "&begin_date=%d0101&end_date=%s&datum=MLLW&station=9414290&time_zone=gmt&units=metric&format=json" % (y, end))
        try:
            j = json.loads(get(url))
            for d in j.get("data", []):
                out.append([d["t"], d["v"]])
            log("  tide %d: %d rows" % (y, len(j.get("data", []))))
        except Exception as e:  # noqa
            log("  tide %d failed: %r" % (y, e))
    with open(os.path.join(HERE, "tide_hourly_9414290.csv"), "w", newline="") as f:
        csv.writer(f).writerows(out)
    d = get("https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/9414290/datums.json?units=metric")
    open(os.path.join(HERE, "tide_datums_9414290.json"), "wb").write(d)


# ---------------------------------------------------------------- hourly rain
def fetch_rain_model():
    # weather-model reconstruction of hourly rain, three points across the city
    pts = {"downtown": (37.79, -122.40), "mission": (37.76, -122.415), "sunset": (37.75, -122.49)}
    end = (datetime.date.today() - datetime.timedelta(days=6)).isoformat()
    for name, (la, lo) in pts.items():
        url = ("https://archive-api.open-meteo.com/v1/archive?latitude=%s&longitude=%s&start_date=2008-07-01&end_date=%s"
               "&hourly=precipitation&timezone=GMT&format=csv" % (la, lo, end))
        open(os.path.join(HERE, "rain_model_%s.csv" % name), "wb").write(get(url, timeout=300))
    # last two weeks from the forecast service, which covers the days the archive does not have yet
    url = ("https://api.open-meteo.com/v1/forecast?latitude=37.79&longitude=-122.40&hourly=precipitation"
           "&past_days=14&forecast_days=1&timezone=GMT&format=csv")
    open(os.path.join(HERE, "rain_model_downtown_recent.csv"), "wb").write(get(url))


def fetch_rain_gauges():
    # hourly rain measured at airport weather stations
    t = datetime.date.today()
    for st in ["SFO", "OAK", "HAF"]:
        url = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=%s&data=p01i&year1=2008&month1=7&day1=1"
               "&year2=%d&month2=%d&day2=%d&tz=Etc%%2FUTC&format=onlycomma&latlon=no&missing=M&trace=0.0001&report_type=3"
               % (st, t.year, t.month, t.day))
        try:
            raw = get(url, timeout=600)
            # keep only hours with rain to keep the file small
            lines = raw.decode("utf-8", "replace").splitlines()
            keep = [lines[0]] + [ln for ln in lines[1:] if ln.split(",")[-1] not in ("M", "0.00", "0", "")]
            open(os.path.join(HERE, "rain_gauge_%s.csv" % st), "w").write("\n".join(keep) + "\n")
            log("  gauge %s: %d rainy hours of %d reports" % (st, len(keep) - 1, len(lines) - 1))
        except Exception as e:  # noqa
            log("  gauge %s failed: %r" % (st, e))


# ---------------------------------------------------------------- ground heights
def fetch_dem():
    z = 14
    n = 2 ** z

    def tx(lon):
        return int((lon + 180.0) / 360.0 * n)

    def ty(lat):
        r = math.radians(lat)
        return int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)

    x0, x1 = tx(-122.525), tx(-122.35)
    y0, y1 = ty(37.84), ty(37.70)
    count = 0
    for x in range(x0, x1 + 1):
        os.makedirs(os.path.join(HERE, "dem", str(z), str(x)), exist_ok=True)
        for y in range(y0, y1 + 1):
            b = get("https://s3.amazonaws.com/elevation-tiles-prod/terrarium/%d/%d/%d.png" % (z, x, y))
            open(os.path.join(HERE, "dem", str(z), str(x), "%d.png" % y), "wb").write(b)
            count += 1
    json.dump({"z": z, "x0": x0, "x1": x1, "y0": y0, "y1": y1, "tiles": count},
              open(os.path.join(HERE, "dem", "index.json"), "w"))
    log("  ground height tiles: %d" % count)


# ---------------------------------------------------------------- city flood zone from the utility's own model
def fetch_flood_zone():
    b = get("https://data.sfgov.org/api/geospatial/jzu3-4yxp?method=export&format=GeoJSON", timeout=300)
    open(os.path.join(HERE, "city_100yr_flood_zone.geojson"), "wb").write(b)


# ---------------------------------------------------------------- rain measured inside San Francisco
def fetch_rain_sf_downtown():
    # the downtown San Francisco gauge, as relayed by the regional ocean observing data server
    base = "https://erddap.cencoos.org/erddap/tabledap/gov_noaa_nws_hads_san_francisco_"
    open(os.path.join(HERE, "rain_sf_downtown_info.csv"), "wb").write(
        get("https://erddap.cencoos.org/erddap/info/gov_noaa_nws_hads_san_francisco_/index.csv"))
    open(os.path.join(HERE, "rain_sf_downtown.csv"), "wb").write(get(base + ".csv", timeout=900))


def fetch_rain_15min():
    # federal archive of 15-minute rain gauges: keep any gauge inside or next to the city
    root = "https://www.ncei.noaa.gov/pub/data/hpd/auto/v2/beta/"
    inv = None
    for name in ["hpd-stations-inventory.csv", "15min/hpd-stations-inventory.csv", "hpd-stations.txt"]:
        try:
            inv = get(root + name).decode("utf-8", "replace")
            log("  station list: " + name)
            break
        except Exception as e:  # noqa
            log("  station list %s failed: %r" % (name, e))
    if inv is None:
        raise RuntimeError("no station list")
    open(os.path.join(HERE, "rain_15min_station_list.csv"), "w").write(
        "\n".join(ln for i, ln in enumerate(inv.splitlines()) if i == 0 or ",CA," in ln or " CA " in ln) + "\n")
    found = 0
    for row in csv.reader(io.StringIO(inv)):
        try:
            sid, la, lo = row[0], float(row[1]), float(row[2])
        except Exception:
            continue
        if 37.60 <= la <= 37.95 and -122.60 <= lo <= -122.15:
            for path in ["15min/all/%s.15m.csv" % sid, "all/%s.15m.csv" % sid]:
                try:
                    raw = get(root + path, timeout=300, tries=2)
                    open(os.path.join(HERE, "rain_15min_%s.csv" % sid), "wb").write(raw)
                    log("  15-minute gauge %s (%s): %d bytes" % (sid, row[5] if len(row) > 5 else "", len(raw)))
                    found += 1
                    break
                except Exception as e:  # noqa
                    log("  15-minute gauge %s at %s failed: %r" % (sid, path, e))
    log("  15-minute gauges saved: %d" % found)


# ---------------------------------------------------------------- storm drains
def fetch_drains():
    q = urllib.parse.urlencode({"$limit": 100000})
    open(os.path.join(HERE, "storm_drains.csv"), "wb").write(
        get("https://data.sfgov.org/resource/jtgq-b7c5.csv?" + q, timeout=300))


def have(*names):
    return all(os.path.exists(os.path.join(HERE, n)) for n in names)


if __name__ == "__main__":
    full = "--all" in sys.argv
    if full or not have("311_flooding.csv"):
        step("311 flooding cases", fetch_311)
    if full or not have("tide_hourly_9414290.csv"):
        step("tide gauge", fetch_tide)
    if full or not have("rain_model_downtown.csv"):
        step("rain, weather model", fetch_rain_model)
    if full or not have("rain_gauge_SFO.csv"):
        step("rain, airport gauges", fetch_rain_gauges)
    if full or not have("dem/index.json"):
        step("ground heights", fetch_dem)
    if full or not have("city_100yr_flood_zone.geojson"):
        step("city 100-year flood zone", fetch_flood_zone)
    step("rain, San Francisco downtown gauge", fetch_rain_sf_downtown)
    step("rain, 15-minute gauges", fetch_rain_15min)
    step("storm drains", fetch_drains)
    open(os.path.join(HERE, "fetch_log.txt"), "w").write(
        datetime.datetime.utcnow().isoformat() + "Z\n" + "\n".join(LOG) + "\n")
