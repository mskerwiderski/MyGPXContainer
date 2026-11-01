"""Sports a route suits: Garmin's own activity types (typeKey + typeId), so the
course sync needs no mapping. Every outdoor sub-sport of running, walking and
cycling (Michael 2026-10-27); hiking counts as walking. Indoor and virtual
types are left out - a route is always outside.

Taken once from Garmin (GET activity-service/activity/activityTypes,
2026-10-27); a new Garmin sport is a change here, not a lookup at run time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import N_


@dataclass(frozen=True)
class Sport:
    key: str        # Garmin typeKey
    type_id: int    # Garmin typeId (course activityTypePk)
    group: str      # run | walk | bike
    label: str      # English, translated where shown


GROUPS = {"run": N_("Run"), "walk": N_("Walk"), "bike": N_("Bike")}

SPORTS = [
    Sport("running", 1, "run", N_("Running")),
    Sport("trail_running", 6, "run", N_("Trail running")),
    Sport("street_running", 7, "run", N_("Street running")),
    Sport("track_running", 8, "run", N_("Track running")),
    Sport("ultra_run", 181, "run", N_("Ultra run")),
    Sport("obstacle_run", 154, "run", N_("Obstacle run")),
    Sport("walking", 9, "walk", N_("Walking")),
    Sport("hiking", 3, "walk", N_("Hiking")),
    Sport("casual_walking", 15, "walk", N_("Casual walking")),
    Sport("speed_walking", 16, "walk", N_("Speed walking")),
    Sport("cycling", 2, "bike", N_("Cycling")),
    Sport("road_biking", 10, "bike", N_("Road cycling")),
    Sport("gravel_cycling", 143, "bike", N_("Gravel")),
    Sport("mountain_biking", 5, "bike", N_("Mountain biking")),
    Sport("enduro_mtb", 256, "bike", N_("Enduro MTB")),
    Sport("downhill_biking", 20, "bike", N_("Downhill")),
    Sport("cyclocross", 19, "bike", N_("Cyclocross")),
    Sport("track_cycling", 21, "bike", N_("Track cycling")),
    Sport("recumbent_cycling", 22, "bike", N_("Recumbent cycling")),
    Sport("bmx", 131, "bike", N_("BMX")),
    Sport("hand_cycling", 197, "bike", N_("Hand cycling")),
    Sport("e_bike_fitness", 176, "bike", N_("E-bike")),
    Sport("e_bike_mountain", 175, "bike", N_("E-mountain bike")),
    Sport("e_enduro_mtb", 260, "bike", N_("E-enduro MTB")),
]

BY_KEY = {s.key: s for s in SPORTS}


def clean(keys: list[str]) -> list[str]:
    """Known keys only, each once, in the order of SPORTS (a form sends its
    boxes in page order anyway)."""
    wanted = set(keys)
    return [s.key for s in SPORTS if s.key in wanted]


# Profile from the climbing per km (Michael 2026-10-27: flat / hilly /
# mountainous, worked out by the computer, never by hand). Bounds picked on
# the routes then in MGC: the home loops are flat, Fuerteventura hilly,
# the Glocknerkönig (61 m/km) mountainous. On foot much more (Michael
# 2026-10-30): 265 m on a 15 km hike is not mountainous.
PROFILES = {"flat": N_("Flat"), "hilly": N_("Hilly"), "mountainous": N_("Mountainous")}
HILLY_M_PER_KM, MOUNTAINOUS_M_PER_KM = 7, 15
FOOT_HILLY_M_PER_KM, FOOT_MOUNTAINOUS_M_PER_KM = 20, 50


def km_label(km: float, sport: str) -> str:
    """Runs and walks with one decimal ("21.9k"), rides whole ("85k") - as on
    the routes renamed on 2026-10-27; a point, in every language."""
    return f"{km:.1f}" if on_foot([sport]) else f"{km:.0f}"


def on_foot(sport_keys) -> bool:
    """Run and Walk only - a route with any bike sport counts as by bike."""
    keys = [k for k in sport_keys if k in BY_KEY]
    return bool(keys) and all(BY_KEY[k].group != "bike" for k in keys)


def profile(distance_m: float, ascent_m: int | None, sport_keys=()) -> str | None:
    if ascent_m is None or distance_m <= 0:
        return None
    hilly, mountainous = ((FOOT_HILLY_M_PER_KM, FOOT_MOUNTAINOUS_M_PER_KM) if on_foot(sport_keys)
                          else (HILLY_M_PER_KM, MOUNTAINOUS_M_PER_KM))
    per_km = ascent_m / (distance_m / 1000)
    if per_km >= mountainous:
        return "mountainous"
    return "hilly" if per_km >= hilly else "flat"
