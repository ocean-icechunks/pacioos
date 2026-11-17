<!-- Mirror of the Claude Doc https://claude.ai/artifact/MmW3VYYgR6enaALtqToX31
     (doc rev 9, exported 2026-11-17). The doc is the live copy that goes to PacIOOS; edit
     there and refresh this file. -->

# PacIOOS models on Source Cooperative: how to upload, what's next, and working with an agent

Nov 17, 2026 · @Eli

The PacIOOS Hawaiʻi model NetCDFs (ROMS forecast, WRF, WW3 and the ROMS reanalysis v2.0, 3.8 TB) are on Source Cooperative, and the GitHub repo [ocean-icechunks/pacioos](https://github.com/ocean-icechunks/pacioos) is yours to take over. Its README lists what was copied. This note covers how to work on the repo with a coding agent, which tasks are waiting, and where the upload instructions are.

**Where it stands on 2026-11-17.** Three virtual Icechunk stores are published on Source Cooperative: the ROMS reanalysis v2.0, the ROMS forecast and WW3, each with a browser viewer. The ROMS forecast and WW3 stores each have a daily updater (`update_store.py` in the store's folder), both run on the production stores on 2026-11-16. WRF has no store yet. Nothing runs the upload or the updaters on a schedule yet: that is the hackweek project, [#4](https://github.com/ocean-icechunks/pacioos/issues/4).

**Background, if you're new to this:** [How a virtual Icechunk store gets made](https://claude.ai/artifact/BTCTko294KTQebZW6Y2K4o) explains what a virtual store is and why the files had to go to the cloud first. [Getting the PacIOOS model files onto Source Cooperative](https://claude.ai/artifact/4Nqhx91MozRLbfjYXmfpP7) is the transfer plan this copy followed: Route A for the first copy, Route B for PacIOOS uploading its own new files.

## Working with a coding agent

Start the agent (Claude Code, GitHub Copilot, Codex, Antigravity) in the root of the repo, and install the shared Icechunk skills first. The repo's `AGENTS.md` gives the agent the rules, and `agent/handoff.md` says where the work stands, so you don't have to explain the project.

### Set up once

1. **Clone the repo** and open your agent in its folder. Claude Code reads `CLAUDE.md`, which loads `AGENTS.md`; the other agents read `AGENTS.md` directly.
2. **Install the `virtual-icechunk` skill** from [ocean-icechunks/ocean-icechunks-skills](https://github.com/ocean-icechunks/ocean-icechunks-skills#install), following that repo's README (one clone, then a link per agent). A skill is a folder of instructions the agent loads on its own when your request matches it; you don't call it by name.

### First, have it explain the repo and the upload

Ask in plain words. Prompts that work well:

- "Read AGENTS.md and agent/handoff.md, then tell me what this repo does and what is open."
- "Walk me through upload/upload\_to\_source\_coop.sh. What does it do with each file, and what makes it safe to stop and rerun?"
- "Do a dry run of the upload for wrf\_hi and explain what it would upload." Run this on the server, where the files are.
- "Check the copies on Source Cooperative for ww3\_hawaii with a sample of 10 files."
- "Read issue #4 and the OISST pipeline in ocean-icechunks/noaa\_oisst, and propose how to run our daily upload on our side."

### Then, the stores and the daily update

Each store's folder under `stores/` starts with a `how_store_created.md` that explains how it was built and why. Ask the agent to walk you through one before changing anything.

1. "Read stores/roms\_hiig/how\_store\_created.md and explain how the forecast store is built and how update\_store.py keeps it current."
2. "Run stores/ww3\_hawaii/update\_store.py --dest production --dry-run and tell me what it would change." A dry run writes nothing.
3. "Read issue #4 and the OISST pipeline in ocean-icechunks/noaa\_oisst, and propose how to run the upload on our server and then the two updaters, every day."
4. "Using the virtual-icechunk skill and the ROMS and WW3 store code, plan the WRF store (#12). WRF needs two groups because the byte order changes on 2017-08-16."

Build on scratch first (`--dest scratch` is the default); only `--dest production` writes the public stores.

The rules the agent must follow, such as never overwriting the copies and keeping server details out of git, are in the repo's `AGENTS.md`, which it reads on its own.

## Tasks waiting in the issues

The most urgent is the daily upload ([#4](https://github.com/ocean-icechunks/pacioos/issues/4)): the forecast archive on the server is trimmed over time, so a day not copied in time is lost for good. Each issue lists what it needs from PacIOOS.

- [#4](https://github.com/ocean-icechunks/pacioos/issues/4): upload new forecast, WRF and WW3 runs automatically every day (hackweek project).
- [#2](https://github.com/ocean-icechunks/pacioos/issues/2): decide what happens when files change or reanalysis v3.0 arrives.
- [#3](https://github.com/ocean-icechunks/pacioos/issues/3): copy the ROMS hindcast (3.37 TB).
- [#12](https://github.com/ocean-icechunks/pacioos/issues/12): build the WRF store, reusing the shared updater (`stores/best_series_update.py`).
- [#14](https://github.com/ocean-icechunks/pacioos/issues/14): an all-runs view of the forecasts, for forecast skill, after WRF.

## Running the upload yourselves

Step-by-step instructions are in [`upload/README.md`](https://github.com/ocean-icechunks/pacioos/blob/main/upload/README.md). You need a Source Cooperative account with write access to `ocean-icechunks/pacioos`; ask Eli.
