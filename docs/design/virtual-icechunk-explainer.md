<!--
Snapshot of the Claude Doc now titled "How a virtual Icechunk store gets made",
https://claude.ai/artifact/BTCTko294KTQebZW6Y2K4o, exported 2026-11-10 at rev 695
(still rev 695 when checked 2026-11-13).
Written for PacIOOS after a Slack question about when "the NetCDF => VirtualiZarr
conversion happens". Eli edits the doc directly; the doc is the live version, this is a
copy for the repo. The doc's diagram (pointers in the store, bytes in the files) is a
widget and does not export; it is marked below.
-->

# Intro to virtual Icechunk stores and how they are made

Nov 10, 2026 · Eli Holmes

## Why it is worth doing: an example

The HYCOM global ocean reanalysis is 1.2 PB dataset in 63,341 NetCDF files of 3-hour time-steps for 22 years stored on AWS Open Data. A virtual Icechunk store created for the whole file set opens in about a second as one dataset. [This short notebook](https://colab.research.google.com/github/ocean-icechunks/hycom/blob/main/hycom-gofs-3pt1-reanalysis/bering-sea-snow-crab-demo.ipynb) uses it to map Bering Sea bottom temperature, then builds a 22-year record of the July cold pool on the snow crab grounds. The whole pipeline from reading the data to averaging across space and across all July times takes 2-3 minutes. No data files are downloaded.

This is what a user sees after opening it with xarray (it opened in 1.3 seconds). The user sees one dataset of 64,272 time steps. And can easier run analyses like in the short notebook above with simple lines of code.

```plain
<xarray.Dataset> Size: 1PB
Dimensions:            (time: 64272, depth: 40, lat: 3251, lon: 4500)
Coordinates:
  * time               (time) datetime64[ns] 514kB 1994-01-01T12:00:00 ... 2015-12-31...
    tau                (time) float64 514kB ...
    experiment         (time) int16 129kB ...
  * depth              (depth) float64 320B 0.0 2.0 4.0 6.0 ... 3e+03 4e+03 5e+03
  * lat                (lat) float64 26kB -80.0 -79.96 -79.92 ... 89.92 89.96 90.0
  * lon                (lon) float64 36kB -180.0 -179.9 -179.8 ... 179.8 179.8 179.9
Data variables:
    salinity           (time, depth, lat, lon) float64 301TB ...
    water_temp         (time, depth, lat, lon) float64 301TB ...
    water_temp_bottom  (time, lat, lon) float64 8TB ...
    surf_el            (time, lat, lon) float64 8TB ...
    water_u            (time, depth, lat, lon) float64 301TB ...
    water_v            (time, depth, lat, lon) float64 301TB ...
    salinity_bottom    (time, lat, lon) float64 8TB ...
    water_v_bottom     (time, lat, lon) float64 8TB ...
    water_u_bottom     (time, lat, lon) float64 8TB ...
Attributes: (12/15)
    institution:               Naval Oceanographic Office
    title:                     HYCOM GOFS 3.1 Global Ocean Reanalysis, GLBv0.08 expt_...
    ...                        ...
```

## What a virtual store is

Think of a library catalog. The books stay on the shelves, and the catalog card says which shelf and which page. A virtual Icechunk store is the catalog, and the NetCDF files are the shelves.

Inside each NetCDF file, the data is stored in pieces called chunks. In ROMS, for example, a chunk might be one variable at one time step: the full 3-D grid of temperature at 03:00 on one day. VirtualiZarr opens each file, reads only its header, and writes down one line per chunk:

- which variable and time step it is;
- which file it is in, by web address;
- where in that file it starts, and how many bytes long it is.

It never reads the data itself. That is why building the store is fast, and why it stays small: tens of megabytes of pointers for terabytes of files.

When someone opens the store and asks for temperature in January 2015, Icechunk looks up the matching chunks and fetches just those bytes from the NetCDF files. The reader sees one tidy dataset covering every year and never has to know there were thousands of files.

[diagram in the doc: a virtual store · pointers in the store, bytes in the files]

The store answers where the data is; the files supply the numbers.

The other way to make a store is to copy the numbers out of the NetCDFs into new Zarr files. That is a real conversion, it doubles the storage, and it is not the plan here.

## Why the files go to the cloud first

Every pointer holds a web address. If the store is built from files on your server, the addresses are paths like `/data/roms/2015/file.nc`, and those mean nothing to anyone outside your building. A reader's request would go nowhere.

The addresses have to be the files' final public ones, such as `https://data.source.coop/pacioos/roms/2015/file.nc`. There are two ways to get there:

- **Build after uploading (simplest).** Copy the files to Source Cooperative, then build the store from the copies. The addresses come out right with no extra step.
- **Build locally, then fix the addresses.** VirtualiZarr can rewrite every address from the local path to the cloud one before the store is written. This works, but the files still have to be uploaded to exactly those addresses, and a mismatch shows up only when someone tries to read.

Either way, the files must not change or move once the store points at them. The pointers are byte positions, so a replaced or edited file makes them point at the wrong bytes. If a file has to be replaced, the store is updated to match. Icechunk can record each file's last-modified time, so a stale pointer gives an error rather than wrong numbers.

**If the files later move to a NOAA cloud bucket.** If the files later go to other Amazon or Google cloud storage. That is fine, and it does not mean starting over. Copy the files there unchanged, with the same folder layout, and point the store at the new addresses. Only the start of each address changes, so the pointers are rewritten or rebuilt from the file headers. That takes hours, and no data is copied a second time to do it. Keep the Source Cooperative copies until the store has been switched and tested, so readers are never left with broken pointers.

## What a user sees

A user opens the store in Python with xarray and gets one dataset, not thousands of files. Common jobs take a line or two. The code is illustrative: the exact names and the two lines that connect to the store will be in the store's README.

```python
# open the whole dataset, opened in seconds; session.store is the icechunk url
ds = xr.open_zarr(session.store, consolidated=False)   

# a time series at one place, near the surface
ds.temp.sel(lat=21.3, lon=-157.9, method="nearest").isel(depth=0).sel(time="2015").plot()

# a spatial average over the whole grid, for each time step
ds.temp.isel(depth=0).mean(["lat", "lon"])
```

There is no downloading of files, no looping over them, and no stitching them together by hand.  How fast each kind of request is depends on how the raw files lay out the data inside, and we will know that only once we see one. A map is almost always quick. A long time series at one point may be quick or slow depending on that layout, so we will check before promising anything.

## The steps, in order

1. **Before hackathon. ****Copy the NetCDF files, unchanged.** This is the slow step: days, not hours, for the full set. How it gets done is in [Getting the PacIOOS model files onto Source Cooperative](https://claude.ai/artifact/4Nqhx91MozRLbfjYXmfpP7).
2. **Hackathon. ****Build the index, one store per model.** VirtualiZarr reads the header of each file and Icechunk writes the pointers, combined along time into one dataset. Models on different grids get separate stores. This step reads headers only, so it takes hours, not days. Fixing/adding metadata re the netCDFs happens at this step.
3. **Hackathon. Create dashboards, tutorials and applications** that leverage the icechunk.

## Where the missing metadata goes

Missing metadata goes into the store when it is built, never into the files. The store keeps its own copy of every name, unit and description. A reader sees the store's version, and the NetCDF files stay exactly as you produced them.

| Can be fixed in the store | Cannot be fixed without rewriting the files |
| --- | --- |
| Dataset title, summary, license, citation, contact | The data values themselves |
| Variable units, long names, CF standard names | How the data is compressed |
| Coordinate names and time encoding | How the data is split into chunks, which sets read speed |
| Coordinates the files lack, taken from a grid file |  |
| Dropping variables nobody needs |  |

Nothing here has to be perfect on the first pass. Each change to the store is saved as a new version, like a commit in git, so metadata can be corrected later without touching the files and without losing the history.

The most useful thing to bring to the sprint is a list: which attributes are missing or wrong, and what they should say.

## The metadata your THREDDS adds with NcML

**Does it matter that the raw files lack the metadata THREDDS adds?** No. The store is what people open, and the store gets the full metadata. Nothing needs to be sent for this: comparing what THREDDS serves with a raw file shows exactly what your NcML adds, and the same attributes, names and units go into the icechunk store. Most of what NcML does can be reproduced this way:

| What your NcML does | In the store |
| --- | --- |
| Adds or corrects global and variable attributes | Yes, the same attributes |
| Renames variables or dimensions | Yes |
| Joins many files into one long time series | Yes, this is what the store does anyway |
| Hides variables | Yes, they are left out |
| Computes new values from the data, such as scaling or unit conversion of the numbers | Usually not; check case by case |

**Is it OK to host the raw files on Source Cooperative?** Yes. They are what the store points to. Most people will open the store, not the files. Anyone who downloads a raw file directly gets it without the NcML additions. A short README beside the files says that and gives the icechunk store's address, so they know where the full metadata is.

**Can the metadata be added or changed later?** Yes. The icechunk store's metadata can be added to or corrected at any time, and each change is saved as a new version. This is routine: Eli already adds metadata to the store whenever the original NetCDFs are not CF-compliant. The raw files never need to be touched for this, and it is best if they are not, because the store's pointers depend on them staying exactly as uploaded.

## Who does what

For the sprint, Eli does the technical steps, and PacIOOS supplies the files and the knowledge of what they contain. Later, the steps move to PacIOOS and we can help show automation pipelines.

| Step | For the sprint | Later |
| --- | --- | --- |
| Copy files to Source Cooperative | Eli, or PacIOOS with a script from Eli | PacIOOS uploads new files as they are made |
| Build the store | Eli | An automatic job, still to be set up, that runs when new files land, as for NOAA's OISST store |
| Metadata fixes | PacIOOS says what is missing; Eli puts it in | PacIOOS says what to change |
| Test and publish | Eli and PacIOOS together | Only when something changes |

PacIOOS does not need to learn VirtualiZarr or Icechunk for any of this. The one thing that has to stay true is that files on Source Cooperative are not edited or replaced in place.

## To settle at the sprint

- [ ] Anything you know is missing or wrong even in what THREDDS serves today.
- [ ] Which datasets go first. The ROMS reanalysis is finished and does not change, so it is the easiest start.
- [ ] For the forecasts: every past run, or only the latest stitched-together series.
- [ ] Are files on your server ever replaced after they are first written? If so, how often, so the store can be kept in step.
- [ ] Folder and store names on Source Cooperative.
- [ ] How much long time series at a single point matter to your users, so we know what to check for once we see the raw files.
