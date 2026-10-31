"""English and German.

English is the source language and doubles as the key: every text is written
in English where it is used, marked `_("…")` (templates) or `N_("…")` (Python), and
looked up in `DE` for German. A text missing from `DE` shows in English
rather than as a key - `tests/test_i18n.py` makes sure none is missing.
Values go in as `{name}` fields: `_("{n} routes", n=3)`.

Which language a request gets (`pick`): the one set in MyAuth for the
signed-in user, like every other app; without login (local development)
the browser's, then English. Route names and descriptions are user content
and are never translated.
"""

from __future__ import annotations

LANGS = ("en", "de")
DEFAULT = "en"

DE: dict[str, str] = {
    # shell
    "Routes": "Routen",
    "More": "Mehr",
    "Account": "Konto",
    "Log out": "Abmelden",
    "Main navigation": "Hauptnavigation",
    # routes: list, upload
    "Add route": "Route hinzufügen",
    "Add more": "Weitere hinzufügen",
    "Added": "Hinzugefügt",
    "Already there": "Schon vorhanden",
    "Ascent": "Anstieg",
    "Cancel": "Abbrechen",
    "Descent": "Abstieg",
    "Description": "Beschreibung",
    "Distance": "Distanz",
    "File": "Datei",
    "GPX files": "GPX-Dateien",
    "Name": "Name",
    "No routes yet": "Noch keine Routen",
    "Not added": "Nicht hinzugefügt",
    "One route per file, up to {n} files and 10 MB each. Name and description come from "
    "the file; you can change them afterwards.":
        "Eine Route je Datei, bis zu {n} Dateien mit je höchstens 10 MB. Name und "
        "Beschreibung kommen aus der Datei; du kannst sie danach ändern.",
    "Only the first {n} files were read.": "Nur die ersten {n} Dateien wurden gelesen.",
    "Optional - applies to every file": "Optional – gilt für jede Datei",
    "Result": "Ergebnis",
    "Suitable for": "Geeignet für",
    "To the routes": "Zu den Routen",
    "Upload": "Hochladen",
    "Paste a share link from Komoot or Garmin Connect, or upload GPX files, to add the "
    "first route.":
        "Füge einen Share-Link von Komoot oder Garmin Connect ein oder lade GPX-Dateien "
        "hoch, um die erste Route anzulegen.",
    "Upload GPX files": "GPX-Dateien hochladen",
    # share links (sources/)
    "A Komoot tour (the link from its “Share” button), a Garmin Connect course - yours or "
    "a public one - or any link to a GPX file.":
        "Eine Komoot-Tour (der Link aus ihrem „Teilen“-Knopf), eine Garmin-Connect-Strecke "
        "– deine oder eine öffentliche – oder ein beliebiger Link auf eine GPX-Datei.",
    "Add": "Hinzufügen",
    "From a share link": "Aus einem Share-Link",
    "Link": "Link",
    "Open it": "Öffnen",
    "Optional": "Optional",
    "Source": "Quelle",
    "Tick nothing to take the sport from Komoot or Garmin.":
        "Ohne Häkchen kommt die Sportart von Komoot bzw. Garmin.",
    "This route is already here: “{name}”.": "Diese Route gibt es schon: „{name}“.",
    "Please paste a link starting with https://":
        "Bitte einen Link einfügen, der mit https:// beginnt.",
    "{source} answered with an error ({status}).":
        "{source} hat mit einem Fehler geantwortet ({status}).",
    "{source} is not reachable right now.": "{source} ist gerade nicht erreichbar.",
    "Komoot does not know this tour.": "Komoot kennt diese Tour nicht.",
    "Komoot does not share this tour. Use the share link from Komoot's “Share” button - it "
    "carries an access token.":
        "Komoot gibt diese Tour nicht frei. Nimm den Link aus Komoots „Teilen“-Knopf – "
        "er enthält einen Zugangsschlüssel.",
    "The tour has no track.": "Die Tour hat keinen Track.",
    "This Komoot link does not point to a tour.": "Dieser Komoot-Link zeigt auf keine Tour.",
    "This Garmin Connect link does not point to a course.":
        "Dieser Garmin-Connect-Link zeigt auf keine Strecke.",
    "Garmin does not share this course with you. Only your own and public courses can be "
    "added.":
        "Garmin gibt dir diese Strecke nicht frei. Hinzufügen lassen sich nur deine eigenen "
        "und öffentliche Strecken.",
    "This link does not lead to a public website.":
        "Dieser Link führt auf keine öffentliche Website.",
    "Too many redirects.": "Zu viele Weiterleitungen.",
    # Garmin: send, My Garmin (garmin_sync.py, garmin_send.html, garmin.html, route.html)
    "All devices": "Alle Geräte",
    "Also on these devices": "Zusätzlich auf diese Geräte",
    "Also sent to {devices} - each gets them on its next sync with Garmin Connect.":
        "Außerdem an {devices} gesendet – jedes Gerät holt sie bei seinem nächsten Abgleich "
        "mit Garmin Connect.",
    "As {sport}": "Als {sport}",
    "Becomes a private course in your Garmin Connect account - and on your devices, if you "
    "like.":
        "Wird eine private Strecke in deinem Garmin-Connect-Konto – und auf Wunsch auf deinen "
        "Geräten.",
    "Changed": "Geändert",
    "Changed in Garmin Connect, so it was left there - delete it there.":
        "In Garmin Connect geändert, darum dort gelassen – lösche sie dort.",
    "Changed since it was sent to Garmin": "Geändert, seit sie an Garmin gesendet wurde",
    "Deleted route": "Gelöschte Route",
    "Devices": "Geräte",
    "Each route becomes a private course in your Garmin Connect account, as the sport you "
    "pick here. A route already there is replaced if it has changed since.":
        "Jede Route wird eine private Strecke in deinem Garmin-Connect-Konto, mit der "
        "Sportart, die du hier wählst. Ist eine Route schon dort und hat sich seitdem "
        "geändert, wird sie ersetzt.",
    "Garmin Connect": "Garmin Connect",
    "Checking Garmin Connect…": "Garmin Connect wird abgefragt …",
    "Garmin Connect at work…": "Garmin Connect arbeitet …",
    "Garmin Connect is not reachable right now - this is what it had last.":
        "Garmin Connect ist gerade nicht erreichbar – das ist der letzte bekannte Stand.",
    "Garmin works with your own account, so MyGPXContainer needs to know who you are.":
        "Garmin arbeitet mit deinem eigenen Konto, darum muss MyGPXContainer wissen, wer "
        "du bist.",
    "In Garmin Connect": "In Garmin Connect",
    "My Garmin": "Mein Garmin",
    "No device that can take courses. Devices show up here once your Garmin Connect account "
    "has one.":
        "Kein Gerät, das Strecken aufnehmen kann. Geräte erscheinen hier, sobald dein "
        "Garmin-Connect-Konto eines hat.",
    "Nothing in Garmin Connect yet": "Noch nichts in Garmin Connect",
    "Open": "Öffnen",
    "Open a route, or select several in the list, and choose “Send to Garmin…”.":
        "Öffne eine Route oder wähle in der Liste mehrere aus und tippe auf „An Garmin "
        "senden …“.",
    "Open in Garmin Connect": "In Garmin Connect öffnen",
    "Remove all": "Alle entfernen",
    "Remove all {n} courses from Garmin Connect?": "Alle {n} Strecken aus Garmin Connect entfernen?",
    "Remove from Garmin Connect": "Aus Garmin Connect entfernen",
    "Remove selected": "Ausgewählte entfernen",
    "Remove {n} courses from Garmin Connect?": "{n} Strecken aus Garmin Connect entfernen?",
    "Route": "Route",
    "Route deleted": "Route gelöscht",
    "Routes sent to a device stay there: later changes don't follow them, and only you can "
    "remove them, on the device itself.":
        "Auf ein Gerät gesendete Routen bleiben dort: Spätere Änderungen kommen nicht nach, "
        "und entfernen kannst nur du sie, am Gerät selbst.",
    "Send": "Senden",
    "Send again": "Erneut senden",
    "Send to Garmin": "An Garmin senden",
    "Send to Garmin…": "An Garmin senden …",
    "Sending to Garmin Connect…": "Wird an Garmin Connect gesendet …",
    "Sign in needed": "Anmeldung nötig",
    "Sign in to send routes to your Garmin account.":
        "Melde dich an, um Routen an dein Garmin-Konto zu senden.",
    "Something went wrong with Garmin Connect.": "Mit Garmin Connect ist etwas schiefgegangen.",
    "Sport in Garmin": "Sportart in Garmin",
    "Unknown device": "Unbekanntes Gerät",
    "Unknown sport": "Unbekannte Sportart",
    "What MyGPXContainer put into your Garmin Connect account, and the devices it went to. "
    "Your other courses there stay untouched.":
        "Was MyGPXContainer in dein Garmin-Connect-Konto gelegt hat und auf welche Geräte es "
        "ging. Deine anderen Strecken dort bleiben unberührt.",
    "in Garmin Connect": "in Garmin Connect",
    "since it was sent": "seit dem Senden",
    "since {date}": "seit {date}",
    "still in Garmin Connect": "noch in Garmin Connect",
    "{device} (old version)": "{device} (alte Version)",
    "{n} removed from Garmin Connect.": "{n} aus Garmin Connect entfernt.",
    "{n} routes in Garmin Connect.": "{n} Routen in Garmin Connect.",
    # own accounts (modes local, single: auth/local.py, login.html, setup.html, invite.html,
    # account.html, admin_users.html)
    "A user name has letters, digits, dot, dash or underscore (at most 40).":
        "Ein Benutzername besteht aus Buchstaben, Ziffern, Punkt, Bindestrich oder "
        "Unterstrich (höchstens 40).",
    "Active": "Aktiv",
    "Admin": "Admin",
    "As the app": "Wie die App",
    "As the browser": "Wie der Browser",
    "Ask whoever invited you for a new one.": "Bitte die Person, die dich eingeladen hat, um einen neuen.",
    "Change password": "Passwort ändern",
    "Create account": "Konto anlegen",
    "Create invitation link": "Einladungslink erstellen",
    "Current password": "Aktuelles Passwort",
    "Disable": "Sperren",
    "Disabled": "Gesperrt",
    "Enable": "Entsperren",
    "Invitation link": "Einladungslink",
    "Invite someone": "Jemanden einladen",
    "Invited": "Eingeladen",
    "Language": "Sprache",
    "Make admin": "Zum Admin machen",
    "MyGPXContainer has no account yet. This first one is the admin.":
        "MyGPXContainer hat noch kein Konto. Dieses erste ist der Admin.",
    "New link": "Neuer Link",
    "New password": "Neues Passwort",
    "No admin": "Kein Admin",
    "Not on your own account.": "Nicht beim eigenen Konto.",
    "Only admins manage the people.": "Nur Admins verwalten die Personen.",
    "Page not found": "Seite nicht gefunden",
    "Password": "Passwort",
    "Password again": "Passwort wiederholen",
    "Password changed. Other browsers have to sign in again.":
        "Passwort geändert. Andere Browser müssen sich neu anmelden.",
    "People": "Personen",
    "Saved.": "Gespeichert.",
    "Send this link to {name}. It works once, for 7 days:":
        "Schick diesen Link an {name}. Er gilt einmal, 7 Tage lang:",
    "Set a password for “{name}”, then you are in.":
        "Leg ein Passwort für „{name}“ fest, dann bist du drin.",
    "Set password": "Passwort festlegen",
    "Setup code": "Einrichtungscode",
    "The setup code is wrong. It is in the app's log.":
        "Der Einrichtungscode stimmt nicht. Er steht im Log der App.",
    "Whoever runs this instance finds it in the app's log (docker compose logs).":
        "Wer diese Instanz betreibt, findet ihn im Log der App (docker compose logs).",
    "Sign in": "Anmelden",
    "Status": "Status",
    "The current password is wrong.": "Das aktuelle Passwort stimmt nicht.",
    "The password needs at least 10 characters.": "Das Passwort braucht mindestens 10 Zeichen.",
    "The two passwords differ.": "Die beiden Passwörter sind verschieden.",
    "This link is not valid (any more).": "Dieser Link gilt nicht (mehr).",
    "This user name is taken.": "Diesen Benutzernamen gibt es schon.",
    "Time zone": "Zeitzone",
    "Too many failed attempts. Please wait a few minutes.":
        "Zu viele Fehlversuche. Bitte ein paar Minuten warten.",
    "Unknown language or time zone.": "Unbekannte Sprache oder Zeitzone.",
    "User name": "Benutzername",
    "User name or password is wrong.": "Benutzername oder Passwort stimmt nicht.",
    "Welcome": "Willkommen",
    "Who uses MyGPXContainer here. Everyone sees only their own routes; routes can be shared "
    "as copies.":
        "Wer MyGPXContainer hier nutzt. Jede Person sieht nur ihre eigenen Routen; Routen "
        "lassen sich als Kopie teilen.",
    "Your name": "Dein Name",
    "you": "du",
    # Garmin for own accounts (auth/garmin_link.py, account.html)
    "Code": "Code",
    "Confirm": "Bestätigen",
    "Connect Garmin": "Garmin verbinden",
    "Connected": "Verbunden",
    "Connected.": "Verbunden.",
    "Disconnect": "Trennen",
    "Disconnect Garmin? Courses already in Garmin Connect stay there.":
        "Garmin trennen? Strecken, die schon in Garmin Connect sind, bleiben dort.",
    "Garmin e-mail": "Garmin-E-Mail",
    "Garmin password": "Garmin-Passwort",
    "Garmin refused to renew the access. Connect it again under Account.":
        "Garmin hat den Zugang nicht verlängert. Verbinde es unter Konto neu.",
    "Garmin sent you a code (e-mail or app). Enter it here:":
        "Garmin hat dir einen Code geschickt (E-Mail oder App). Gib ihn hier ein:",
    "The Garmin connection can't be read any more (new secret key?). Connect it again under "
    "Account.":
        "Die Garmin-Verbindung lässt sich nicht mehr lesen (neuer Schlüssel?). Verbinde sie "
        "unter Konto neu.",
    "To send routes to Garmin Connect and your devices, sign in to Garmin once. Your password "
    "goes to Garmin only and is stored nowhere; MyGPXContainer keeps the access Garmin hands "
    "out, encrypted.":
        "Um Routen an Garmin Connect und deine Geräte zu senden, meldest du dich einmal bei "
        "Garmin an. Dein Passwort geht nur an Garmin und wird nirgends gespeichert; "
        "MyGPXContainer behält den Zugang, den Garmin ausgibt, verschlüsselt.",
    "Your Garmin account is not connected. Connect it under Account.":
        "Dein Garmin-Konto ist nicht verbunden. Verbinde es unter Konto.",
    # Garmin via MyAuth (auth.garmin_token)
    "Garmin is not set up for MyGPXContainer yet.":
        "Garmin ist für MyGPXContainer noch nicht eingerichtet.",
    "Garmin refused the sign-in. Please try again later.":
        "Garmin hat die Anmeldung abgelehnt. Bitte später noch einmal versuchen.",
    "MyAuth is not reachable right now.": "MyAuth ist gerade nicht erreichbar.",
    "Your Garmin account is not connected. Connect it under Connections in MyAuth.":
        "Dein Garmin-Konto ist nicht verbunden. Verbinde es in MyAuth unter Verbindungen.",
    "Upload result": "Ergebnis des Uploads",
    # list: filters, map (search.py, routes.html)
    "All of {group}": "Alles aus {group}",
    "All sports": "Alle Sportarten",
    "Any": "Beliebig",
    "Anyone": "Alle",
    "Apply": "Anwenden",
    "Ascent (m)": "Anstieg (m)",
    "Away": "Entfernt",
    "Distance (km)": "Distanz (km)",
    "Filter": "Filter",
    "Flattest first": "Flachste zuerst",
    "List": "Liste",
    "Near": "In der Nähe von",
    "Near my location": "In meiner Nähe",
    "Nearest first": "Nächste zuerst",
    "Newest first": "Neueste zuerst",
    "No route matches": "Keine Route passt",
    "Only in Garmin Connect": "Nur in Garmin Connect",
    "Place “{place}” not found": "Ort „{place}“ nicht gefunden",
    "Place, e.g. Starnberg": "Ort, z. B. Starnberg",
    "Radius": "Umkreis",
    "Reset": "Zurücksetzen",
    "Search": "Suche",
    "Search name and description": "Name und Beschreibung durchsuchen",
    "Shortest first": "Kürzeste zuerst",
    "Sort": "Sortierung",
    "Sport": "Sportart",
    "View": "Ansicht",
    "Your location is not available.": "Dein Standort ist nicht verfügbar.",
    "from": "von",
    "to": "bis",
    "within {r} km of your location": "im Umkreis von {r} km um deinen Standort",
    "within {r} km of {place}": "im Umkreis von {r} km um {place}",
    "{n} of {total} routes": "{n} von {total} Routen",
    "From": "Von",
    "Me": "Mir",
    "Shared by {name}": "Geteilt von {name}",
    "{n} routes": "{n} Routen",
    # folders (folders.py, folders.html)
    "A folder needs a name.": "Ein Ordner braucht einen Namen.",
    "Create": "Anlegen",
    "Delete the folder “{name}”? Its routes move to “{default}”.":
        "Den Ordner „{name}“ löschen? Seine Routen wandern nach „{default}“.",
    "Every route is in exactly one folder. Your folders are your own: nobody else sees them. "
    "A route without a folder of its own is in “{name}”.":
        "Jede Route liegt in genau einem Ordner. Deine Ordner gehören dir: niemand sonst sieht "
        "sie. Eine Route ohne eigenen Ordner liegt in „{name}“.",
    "Folder": "Ordner",
    "Folder not found": "Ordner nicht gefunden",
    "Folders": "Ordner",
    "General": "Allgemein",
    "Manage folders": "Ordner verwalten",
    "New folder": "Neuer Ordner",
    "Rename": "Umbenennen",
    "There is already a folder with this name.": "Einen Ordner mit diesem Namen gibt es schon.",
    "default": "Standard",
    "e.g. Fuerteventura": "z. B. Fuerteventura",
    # selection mode (routes.html, /routes/bulk)
    "All": "Alle",
    "Move": "Verschieben",
    "Select": "Auswählen",
    "Unknown action": "Unbekannte Aktion",
    "{n} routes moved.": "{n} Routen verschoben.",
    "Delete {n} routes? This cannot be undone.":
        "{n} Routen löschen? Das lässt sich nicht rückgängig machen.",
    "{n} routes deleted.": "{n} Routen gelöscht.",
    "Courses in Garmin Connect stay there - remove them under “My Garmin”.":
        "Strecken in Garmin Connect bleiben dort – entferne sie unter „Mein Garmin“.",
    "{n} selected": "{n} ausgewählt",
    # sharing (share.html, auth/myauth.py)
    "Back": "Zurück",
    "Done": "Fertig",
    "MyAuth does not list the users of MyGPXContainer.":
        "MyAuth nennt die Nutzer von MyGPXContainer nicht.",
    "Nobody else uses MyGPXContainer yet.": "Außer dir nutzt noch niemand MyGPXContainer.",
    "Pick at least one person.": "Wähle mindestens eine Person.",
    "Share": "Teilen",
    "Share…": "Teilen …",
    "Sharing is not available here.": "Teilen ist hier nicht verfügbar.",
    "Sharing needs MyAuth, which is not set up here.":
        "Teilen braucht MyAuth, und das ist hier nicht eingerichtet.",
    "Whoever you pick gets a copy of their own: they can change or delete it, and later "
    "changes on either side stay there.":
        "Wen du auswählst, bekommt eine eigene Kopie: zum Ändern oder Löschen, und spätere "
        "Änderungen bleiben auf der jeweiligen Seite.",
    "With": "Mit",
    "{n} already there": "{n} schon vorhanden",
    "{name}: {n} shared": "{name}: {n} geteilt",
    # loop suggestions (suggest.py, suggest.html)
    "My location": "Mein Standort",
    "No loop found from here. Try another start or distance.":
        "Von hier aus fand sich kein Rundkurs. Versuch einen anderen Start oder eine andere "
        "Distanz.",
    "No route at hand?": "Keine Route zur Hand?",
    "No suggestion": "Kein Vorschlag",
    "Pick a distance from {min} to {max} km.": "Wähle eine Distanz von {min} bis {max} km.",
    "Pick a start: your location or a place.": "Wähle einen Start: deinen Standort oder einen Ort.",
    "Start": "Start",
    "Suggest": "Vorschlagen",
    "Suggest a route": "Route vorschlagen",
    "Suggested by MyGPXContainer on {date}: {sport}, {profile}.":
        "Von MyGPXContainer vorgeschlagen am {date}: {sport}, {profile}.",
    "Suggestion {n}": "Vorschlag {n}",
    "Suggestions are not available right now. Please try again in a minute.":
        "Vorschläge gibt es gerade nicht. Bitte versuch es in einer Minute noch einmal.",
    "Suggestions are not set up here.": "Vorschläge sind hier nicht eingerichtet.",
    "Take over": "Übernehmen",
    "The terrain here is not “{profile}” - these come closest.":
        "Das Gelände hier ist nicht „{profile}“ – diese kommen am nächsten heran.",
    "There is no map for this area yet. An app admin can add it.":
        "Für diese Gegend gibt es noch keine Karte. Ein App-Admin kann sie hinzufügen.",
    "Three routes from your start - back to it, or to a destination. Your location stays on "
    "MyGPXContainer's own server; only what you type into a place field is looked up outside "
    "(Photon, OpenStreetMap).":
        "Drei Routen ab deinem Start – zurück dorthin oder zu einem Ziel. Dein Standort bleibt "
        "auf dem eigenen Server von MyGPXContainer; nur was du in ein Ortsfeld tippst, wird "
        "draußen nachgeschlagen (Photon, OpenStreetMap).",
    "A place or address": "Ein Ort oder eine Adresse",
    "Destination": "Ziel",
    "From A to B": "Von A nach B",
    "Kind": "Art",
    "No way found from the start to the destination.":
        "Vom Start zum Ziel fand sich kein Weg.",
    "Pick a destination at least {min} km away.":
        "Wähle ein Ziel, das mindestens {min} km entfernt ist.",
    "Start and destination are {crow} km apart - more than the {max} km a route may have.":
        "Start und Ziel liegen {crow} km auseinander – mehr als die {max} km, die eine Route "
        "haben darf.",
    "Every way from the start to the destination is longer than {max} km.":
        "Jeder Weg vom Start zum Ziel ist länger als {max} km.",
    "Routes up to {max} km": "Routen bis {max} km",
    "Pick a destination.": "Wähle ein Ziel.",
    "or a place or address": "oder ein Ort, eine Adresse",
    "Unknown suggestion": "Unbekannter Vorschlag",
    "{n} % on main roads": "{n} % auf Hauptstraßen",
    "{n} % unpaved": "{n} % unbefestigt",
    "Elevation profile": "Höhenprofil",
    "Elevation {lo}–{hi} m": "Höhe {lo}–{hi} m",
    # map regions (routing.py, admin_routing.html)
    "Add a region": "Region hinzufügen",
    "Building": "Wird gebaut",
    "Built on {date} in {min} min, {mb} MB": "Gebaut am {date} in {min} min, {mb} MB",
    "Built: {regions}": "Gebaut: {regions}",
    "Country or region, e.g. Austria, Canary Islands": "Land oder Region, z. B. Austria, Canary Islands",
    "Failed": "Fehlgeschlagen",
    "Geofabrik's list of regions is not reachable right now.":
        "Die Regionenliste von Geofabrik ist gerade nicht erreichbar.",
    "Last build failed: {error}": "Der letzte Bau ist fehlgeschlagen: {error}",
    "Loop suggestions work where a map is on this list. A change goes into a new build of "
    "the map, which starts within a minute and takes a while (Germany: about half an hour); "
    "until then the old map keeps answering.":
        "Rundkurs-Vorschläge gibt es dort, wo eine Karte auf dieser Liste steht. Eine Änderung "
        "geht in einen neuen Bau der Karte, der innerhalb einer Minute beginnt und eine Weile "
        "dauert (Deutschland: etwa eine halbe Stunde); bis dahin antwortet die alte Karte.",
    "Maps": "Karten",
    "Maps for loop suggestions": "Karten für Rundkurs-Vorschläge",
    "No map": "Keine Karte",
    "No region found for “{q}”.": "Keine Region gefunden für „{q}“.",
    "No region yet - loop suggestions work nowhere.":
        "Noch keine Region – Rundkurs-Vorschläge gibt es nirgends.",
    "Not allowed": "Nicht erlaubt",
    "Now: {step} ({regions}), since {date}": "Gerade: {step} ({regions}), seit {date}",
    "Only app admins manage the maps.": "Die Karten verwalten nur App-Admins.",
    "Ready": "Bereit",
    "Rebuild with fresh map data": "Mit frischen Kartendaten neu bauen",
    "Region": "Region",
    "Remove": "Entfernen",
    "Remove “{name}”? Loop suggestions there stop after the next build.":
        "„{name}“ entfernen? Dort gibt es nach dem nächsten Bau keine Rundkurs-Vorschläge mehr.",
    "Routing service not reached yet": "Routing-Dienst noch nicht erreicht",
    "State": "Zustand",
    "The map is also built afresh every month by itself.":
        "Die Karte wird außerdem jeden Monat von selbst neu gebaut.",
    "The map is being built. Suggestions come back in a few minutes.":
        "Die Karte wird gerade gebaut. Vorschläge gibt es in ein paar Minuten wieder.",
    "The regions are Geofabrik's extracts of OpenStreetMap.":
        "Die Regionen sind die OpenStreetMap-Auszüge von Geofabrik.",
    "Unknown region": "Unbekannte Region",
    "downloading {name}": "lade {name}",
    "importing": "importiere",
    "merging the regions": "füge die Regionen zusammen",
    "switching to the new map": "schalte auf die neue Karte um",
    "“{name}” is already covered by “{outer}”.": "„{name}“ ist schon in „{outer}“ enthalten.",
    # GPX problems
    "The file has no track with at least two points.":
        "Die Datei enthält keinen Track mit mindestens zwei Punkten.",
    "The file is larger than 10 MB.": "Die Datei ist größer als 10 MB.",
    "This GPX file is already the route “{name}”.":
        "Diese GPX-Datei ist schon die Route „{name}“.",
    "This is not a valid GPX file.": "Das ist keine gültige GPX-Datei.",
    # route detail
    "Added on {date}": "Hinzugefügt am {date}",
    "Shared by {name} on {date}": "Geteilt von {name} am {date}",
    "changed on {date}": "geändert am {date}",
    "Dark": "Dunkel",
    "Download GPX": "GPX herunterladen",
    "Edit": "Bearbeiten",
    "Elevation": "Höhe",
    "Loop": "Rundkurs",
    "Map": "Karte",
    "Point to point": "Von A nach B",
    "Satellite": "Satellit",
    "Shape": "Form",
    "Profile": "Profil",
    "Flat": "Flach",
    "Hilly": "Hügelig",
    "Mountainous": "Bergig",
    "Terrain": "Gelände",
    # edit, delete
    "A course in Garmin Connect stays there - remove it under “My Garmin”. Copies you shared "
    "stay with whoever got them.":
        "Eine Strecke in Garmin Connect bleibt dort – entferne sie unter „Mein Garmin“. "
        "Kopien, die du geteilt hast, bleiben bei denen, die sie bekommen haben.",
    "Delete": "Löschen",
    "Delete route": "Route löschen",
    "Route deleted.": "Route gelöscht.",
    "The route could not be deleted.": "Die Route ließ sich nicht löschen.",
    "Delete the route “{name}”? This cannot be undone.":
        "Die Route „{name}“ löschen? Das lässt sich nicht rückgängig machen.",
    "Edit route": "Route bearbeiten",
    "It may have been deleted in the meantime.": "Vielleicht wurde sie inzwischen gelöscht.",
    "Optional. Distance, elevation and map are taken from the new file.":
        "Optional. Distanz, Höhen und Karte kommen dann aus der neuen Datei.",
    "Replace GPX file": "GPX-Datei ersetzen",
    "Route not found": "Route nicht gefunden",
    "Save": "Speichern",
    # sports (sports.py)
    "Run": "Laufen", "Walk": "Gehen", "Bike": "Rad",
    "Running": "Laufen",
    "Trail running": "Trailrunning",
    "Street running": "Straßenlauf",
    "Track running": "Bahnlauf",
    "Ultra run": "Ultralauf",
    "Obstacle run": "Hindernislauf",
    "Walking": "Gehen",
    "Hiking": "Wandern",
    "Casual walking": "Spazierengehen",
    "Speed walking": "Schnelles Gehen",
    "Cycling": "Radfahren",
    "Road cycling": "Rennrad",
    "Gravel": "Gravel",
    "Mountain biking": "Mountainbike",
    "Enduro MTB": "Enduro-MTB",
    "Downhill": "Downhill",
    "Cyclocross": "Cyclocross",
    "Track cycling": "Bahnradsport",
    "Recumbent cycling": "Liegerad",
    "BMX": "BMX",
    "Hand cycling": "Handbike",
    "E-bike": "E-Bike",
    "E-mountain bike": "E-MTB",
    "E-enduro MTB": "E-Enduro-MTB",
    # auth pages
    "No access": "Kein Zugriff",
    "Your account is not enabled for MyGPXContainer. An administrator can change that in MyAuth.":
        "Dein Konto ist für MyGPXContainer nicht freigeschaltet. "
        "Ein Administrator kann das in MyAuth ändern.",
    "Sign-in unavailable": "Anmeldung nicht erreichbar",
    "The sign-in service MyAuth is not responding right now. Please try again in a moment.":
        "Der Anmeldedienst MyAuth antwortet gerade nicht. Bitte versuche es gleich noch einmal.",
    "You are signed in as {name} on behalf of {admin}.":
        "Du bist als {name} angemeldet – im Auftrag von {admin}.",
    "Go to account": "Zum Konto",
    "Sign out as {name}": "Als {name} abmelden",
}


def N_(text: str) -> str:
    """Marks a text for translation where it is defined; translated later,
    where it is shown (`tests/test_i18n.py` finds it)."""
    return text


def gettext(lang: str, text: str, **values) -> str:
    if lang == "de":
        text = DE.get(text, text)
    return text.format(**values) if values else text


def pick(user: dict | None, accept_language: str = "") -> str:
    lang = (user or {}).get("language")
    if lang in LANGS:
        return lang
    if not user:
        for part in accept_language.split(","):
            code = part.split(";")[0].strip()[:2].lower()
            if code in LANGS:
                return code
    return DEFAULT
