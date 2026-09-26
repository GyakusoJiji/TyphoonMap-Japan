# TyphoonMap

TyphoonMap is a local interactive map for replaying typhoon tracks near Japan over time. It follows EQMap's dark map, floating panels, and continuous playback controls.

- Includes JMA RSMC Tokyo best-track data from 2000 onward
- Filter by year and by tracks near Japan or across the Western North Pacific
- Replay by time, speed, and date range; drag to pan, zoom, and replay individual storms
- Use **Update data** to retrieve analysis and forecast tracks for currently active typhoons directly from JMA in the browser

## Launch

On Windows, double-click `start.bat`. The application opens at `http://127.0.0.1:8765/`. Close the server command window to stop it.

You can also open `index.html` directly to browse the bundled best tracks. Updates use JMA's public JSON endpoints directly from the browser and do not depend on the local server having outbound network access.

## Refresh bundled data

To replace the bundled best-track data with the latest version, run the following command with Python 3.10 or later:

```powershell
python tools/update_data.py
```

To refresh the base map as well, run `python tools/update_data.py --map`.

Sources: JMA RSMC Tokyo Best Track Data and JMA Typhoon Information. Forecast tracks for active storms are provisional and are not best-track records.
