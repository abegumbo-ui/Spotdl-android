# SpotDL Android

A small Android app: paste a link, press **Go**, and watch the progress.
Downloads are saved to a folder called **SpotDL Downloader** in your phone's
internal storage, organised as `<Artist>/<Album>/<Song title>`.

Accepted links: YouTube or YouTube Music (song, video, playlist, album, artist
or channel in any address style, including `@name`), and Spotify (track, album,
playlist, artist). You can also type an artist name to download their albums
and singles.

- A normal YouTube video of a song is matched to the same song on YouTube Music
  (by title, artist and length) and the audio comes from YouTube Music.
- Artist links download the artist's albums and singles from YouTube Music. For
  a Spotify artist link the artist's name is read from Spotify first.

On first launch Android asks for permission. Allow **All files access** so
the app can create the `SpotDL Downloader` folder.

## Searching for songs and artists

Press **Search** (next to Go) and type a song or an artist.

- **Songs:** results from Spotify and YouTube Music appear together. A song
  found on both is one row with two covers; tap a cover to choose whose title,
  album and cover art to use (the audio always comes from YouTube Music). Tick
  the songs you want and press **Download**.
- **Artists:** tap an artist's cover to open all their albums and singles.
  Tick whole albums, or press **+** to open an album and pick single songs.
  **Use Spotify / Use YouTube Music** at the top switches which service the
  album list comes from.
- If Spotify can't be reached, YouTube Music results are still shown with a note.

## Getting the APK (no Android Studio needed)

GitHub builds the APK automatically on every push.

1. Open the **Actions** tab of this repository.
2. Click the latest **Build SpotDL APK** run with a green check mark.
3. Scroll down to **Artifacts** and download **SpotDL-APK** (a zip file).
4. Unzip it on your phone and open the `.apk` file. Allow "install from
   unknown sources" if Android asks.

To start a build by hand: **Actions → Build SpotDL APK → Run workflow**.

If a build fails, download the **build-log** artifact from that run to see why.

## How it works

The original `spotdl` package can't run on Android (it needs ffmpeg and
compiled libraries that python-for-android can't build), so the app uses
pure-Python libraries instead:

- **ytmusicapi**: finds the artist and lists their albums and singles
- **yt-dlp**: downloads the audio
- **mutagen**: writes title, artist, album, track number and cover art

Formats: `mp3` (converted on the phone, tagged with cover art), `m4a`
(AAC, tagged with cover art) or `opus` (saved as `.webm`, untagged).

**Auto-update:** each time a download starts the app fetches the newest yt-dlp and
ytmusicapi from PyPI (both are pure Python), so YouTube changes don't break it.
If the phone is offline it uses the last version it downloaded.

**Right version of a song:** Spotify links carry the track length. The app
picks the YouTube Music version whose length matches, instead of the first
search result, and uses the album's square cover art.

The APK is built for 64-bit phones (arm64-v8a), which is nearly every phone
made since 2017.

If the permission isn't granted, files go to the app's private storage
instead. The path is shown on screen.

## Files

- `main.py`: the main screen
- `ui_kit.py`: the app's look (colours, rounded cards, buttons, icons, progress bars)
- `spotdl_bridge.py`: search, download, MP3 conversion and tagging logic
- `search.py` / `search_screen.py`: song and artist search on Spotify and YouTube Music
- `service.py`: runs the download in the background and reports progress
- `report.py`: writes the PDF report
- `updater.py`: downloads the latest yt-dlp / ytmusicapi on startup
- `buildozer.spec`: Android build configuration
- `.github/workflows/build.yml`: GitHub Actions workflow that builds the APK

## What you see while it runs

- The album art and details of the song being downloaded
- An overall bar with "X of Y done - Z left", and a list of every song with
  its status (waiting / downloading / done / FAILED with the reason)
- When a link has more than one song, a PDF report is saved to
  `SpotDL Downloader/Reports/` listing what downloaded and what failed

Only YouTube Music audio tracks are ever downloaded, never video. Pasting a
music-video link downloads its YouTube Music audio version; if there isn't one,
the song is reported as unavailable instead.

## Background downloads

Downloads run in an Android foreground service, so you can press Go and then
leave the app, switch to another one, or lock the screen. A notification shows
while it works, and another one appears when it finishes. The app screen only
shows progress; reopening it picks up the live progress again. Press **Cancel**
in the app to stop.

## Track order

File names are just the song title. The track number (e.g. 3 of 12), album,
album artist and cover are stored inside each file's tags, so music players
keep the album in its real order even if you rename the files.

## Big playlists and retrying failures

- There is no limit on the number of songs. Spotify's public page only lists the
  first 100 songs of a playlist, so the app reads the full listing from Spotify
  in pages of 100. If Spotify refuses, the log says so and only the first 100
  are downloaded.
- Songs are found and downloaded one after another, so downloading starts
  immediately even for a playlist of thousands. The screen shows the songs
  around the current one, with overall counts for the whole job.
- Finished songs are remembered (hidden file `.spotdl_done.txt` in
  `SpotDL Downloader`), so pressing Go again on the same link, for example after
  a cancel or a phone restart, skips everything already downloaded.
- When a job ends with failed songs, a **Retry N failed** button appears. It
  downloads only those songs again and writes a second PDF report.

## Look and feel

A dark theme with rounded cards: a link box with a Paste shortcut, a
MP3 / M4A / Opus switch, a Download button that becomes Cancel while a job
runs, a card with the cover art and smooth progress bars for the song being
downloaded, and a status pill on every song (Waiting, Downloading, Done, Had it,
Failed). Icons and bars are drawn in code, so there are no image files to ship
apart from the app icon and loading screen in `assets/`.
