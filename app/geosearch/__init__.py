"""geosearch v1.0.0 - addresses and places -> coordinates, from keyless services.

A MyCommons building block, copied into its users by MyCommons/sync.sh:
MyFITContainer (app/geosearch/, the place of a competition), MyGPXContainer
(app/geosearch/, starts and stops of route suggestions, the place filter).
Never edit a copy; change it in MyCommons, run its tests, bump the version,
sync again.

`geosearch.photon` (OpenStreetMap, made for search-as-you-type) knows streets,
house numbers and venues, but matches fuzzily ("Seebad Roth" -> "Röthenlage" in
Brandenburg): good for a list a person picks from. `geosearch.openmeteo` knows
only places, sorted by importance, and a comma narrows them down: the one to
use when a coordinate is written without anyone looking. Which one to ask when
is the app's decision. Both answer [] / None on a network error, which is not
cached. Needs `httpx`.
"""

__version__ = "1.0.0"
