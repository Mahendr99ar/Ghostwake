# 3. Alert thresholds

**Status:** accepted, revisit on real data

| Setting | Value | Why |
| --- | --- | --- |
| AIS gap | 6 h | Class B transponders and coverage holes produce gaps of an hour or two routinely. Six hours is well past that. |
| Spoofing | 40 kn implied speed, and a jump over 5 km | Few working vessels exceed 25 kn. The 5 km floor stops GPS jitter on close fixes from tripping it. |
| Meeting at sea | 0.5 km, both under 3 kn, 2 h, outside 3 km of a port | Ships pass close all the time. Staying side by side, nearly stopped, for two hours away from port is the pattern worth checking. |
| IMBL warning | 5 km | At 5 kn that is about 30 minutes of warning, enough to turn around. |
| Radar match gate | 1.5 km plus 0.1 km per minute since the nearest fix, capped at 5 km | Sentinel-1 geolocation error plus how far a ship moves between fixes. |
| Dark candidate | length 15 m or more, confidence 0.5 or more | Below that, small returns are mostly sea clutter and wave crests. |

All of these live in `config.py` and can be set with `GW_` environment variables, and every alert records the values used in its lineage.
