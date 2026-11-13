<!-- Mirror of the Claude Doc https://claude.ai/artifact/4Nqhx91MozRLbfjYXmfpP7
     as Eli edited it (doc rev 2344, checked 2026-11-13). The doc is the live copy that goes to
     PacIOOS; edit there and refresh this file. Background and measurements:
     source-probe.md. -->

# Getting the PacIOOS model files onto Source Cooperative

Nov 10, 2026 · @Eli

## Summary

The five Hawaiʻi model archives total about 5 TB, and copying them straight from the PacIOOS server to Source Coop takes one to two days. That will allow time to get everything transferred by the start of the hackathon.

| Dataset | What it is | Years | Estimated size |
| --- | --- | --- | --- |
| ROMS reanalysis | Ocean currents, temperature, salinity (finished product) | 2009–2020 | 1.2 TB |
| ROMS hindcast | Same variables, data-assimilating, 3-day runs | 2015–now | 1.1 TB or more |
| ROMS forecast | Same variables, one 7-day run per day | 2025–now | 1.2 TB |
| ROMS sea surface height | 2-D companion files for the three above | as above | 0.1 TB |
| WRF wind and weather | One ~7-day run per day | 2010–now | 0.9 TB |
| WW3 waves | One 7.5-day run per day | 2011–now | 0.5 TB |
| **Total** |  |  | **about 5 TB** |

| Copy speed | Time for 5 TB |
| --- | --- |
| 100 MB/s (a typical UH server on a 1 Gbps link) | about 14 hours |
| 50 MB/s (busy or shared link) | about 28 hours |
| 1 MB/s (through the public THREDDS/ERDDAP pages, as measured) - So not what we want! | about 2 months |

The sizes are worked out from the data's dimensions, without compression. If the files on disk are compressed, the real total is smaller.

## What we are doing

We copy the original NetCDF files, unchanged, to Source Cooperative. Source Coop is supporting this effort to host ocean model data as it fits with their mission to provide cloud-optimized earth data. Also 5 TB is not that big. Once the NetCDFs are in Source Coop, building the icechunk is straightforward.  Plan:

- **The raw NetCDFs are not reformatted.** I don't think we need to do any re-processing or rechunking. The chunking is better for maps than for time series, but the files are fine for this stage.
- **File access.** Users read from the NetCDFs on Source Cooperative, not from the PacIOOS server, so the server is not stressed.

## How to get the NetCDFs onto Source Coop

A few options. Given that the hackathon is in 7 days, it might make sense for me (Eli) to get access to the server (read-only login so I can copy the files out) and I put files on Source Coop. If you prefer, I can help you get set up on Source Coop but we should have a 1 hour meeting for me to help you get all set up with the authentication step.

| Route | Who runs the copy | What PacIOOS provides | Notes |
| --- | --- | --- | --- |
| A. Eli copies | Eli, logged in to the PacIOOS server | A read-only login for a week | Eli uploads first copy to Source Coop and then walks PacIOOS staff through the steps at the hackathon. |
| B. PacIOOS uploads on its own | PacIOOS staff | A Source Cooperative account | This requires getting the Source Coop account and then getting authentication set up. Not hard, but a little finicky and might be easier to do together online. |

Route A puts the least work on PacIOOS: one account, then Eli does the rest. Route B avoids a login for Eli but needs a bit more setup.

Proposed schedule (drawn as a timeline in the doc):

| Step | Dates (2026) |
| --- | --- |
| PacIOOS sets up the login | Nov 10 to Nov 12 |
| Look at files, test one | Nov 12 |
| Full copy (1 to 2 days) | Nov 13 to Nov 14 |
| Check copies, build index | Nov 15 to Nov 16 |
| Hackathon starts | Nov 17 |

The copy itself needs one to two days, so the files and the Icechunk index are in place by Nov 16, the day before the hackathon.

## Route A: what PacIOOS needs to do

PacIOOS sets up one login; Eli handles everything after that.

- [ ] **Create a login for Eli** on the server. It needs read-only access to the model data folders and nothing else. Eli sends a public SSH key, so no password is shared.
- [ ] **Tell Eli the folder paths** for the ROMS, WW3 and WRF files.
- [ ] **Check that the machine can reach the internet over HTTPS** (port 443) to `data.source.coop`. Some servers block outgoing connections.
- [ ] **Agree a speed cap and quiet hours** (if desired).
- [ ] **Set an end date** for the login, for example two weeks after the copy finishes.
- [ ] If UH IT requires it, **sponsor a guest account**. Eli is at the University of Washington and NOAA, so she has no UH account. Note, my son is a graduate student in the marine science department at UH and is working on ocean model data, if that makes things easier.

What Eli does from that login:

1. Looks at the files: their sizes, and how they are stored inside. This settles the size estimates above.
2. Copies one file to Source Cooperative to test the route.
3. Runs the full copy with `rclone`, a widely used copy tool. It is a single program file in her own folder, so nothing is installed on the server. It resumes after a dropped connection and checks every file arrived intact.
4. Uses temporary Source Cooperative keys that expire after about a day. She creates them on her own computer, so no long-lived password sits on the PacIOOS machine.

## Route B, the end goal: PacIOOS uploads its own new files

Once the archive is in place, the only ongoing job is copying each day's new model runs, about 3 GB a day in total. That takes a minute or two and can be the last step of the existing daily forecast job.

1. A PacIOOS staff member signs up at [Source Cooperative](https://source.coop) and Eli adds them to the [Ocean Icechunks](https://source.coop/ocean-icechunks) org with upload rights. Or PacIOOS applies for beta tester status and creates their own PacIOOS org within Source Coop.
2. They install Source Cooperative's command-line login tool, which hands out temporary upload keys. Eli has scripts and examples.
3. Run the `rclone` scripts as Route A, which will upload files.

The one awkward step is the Source Coop login tool's sign-in: it opens a web page, which a server with no browser cannot show. After the hackathon, we can help you work with Source Coop to get an ARN setup for auto-updating. NERACOOS/GMRI uses the same setup to auto-update the [NOAA OISST icechunk](https://source.coop/ocean-icechunks/noaa-oisst) on Source Coop, which they build and maintain.

## Questions for PacIOOS

- [ ] Which machine holds the files, and what are the folder paths?
- [ ] How big is each folder on disk? A `du -sh` per folder replaces the estimates above.
- [ ] How fast is that machine's network connection, and may it connect out to `data.source.coop`?
- [ ] What speed cap and quiet hours should the copy keep to?
- [ ] Route A or Route B?

## Connection to Earthmover

We have a Community Organization on Earthmover for Ocean Icechunks and have a pipeline for auto adding/linking the icechunks on our Ocean Icechunk Source Coop org to the Earthmover org --- if you want to go that route. We can help with setting up a PacIOOS community org on Earthmover or use the existing Ocean Icechunk org.
