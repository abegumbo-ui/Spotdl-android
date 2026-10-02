# SpotDL Android

A small Android app: paste a link, press **Go**, and watch the progress.
Downloads are saved to a folder called **SpotDL Downloader** in your phone's
internal storage, organised as `<Artist>/<Album>/<Track>`.

Accepted links: YouTube or YouTube Music (video, playlist, album, artist),
and Spotify (track, album, playlist). You can also type an artist name to
download their albums and singles.

On first launch Android asks for permission. Allow **All files access** so
the app can create the `SpotDL Downloader` folder.

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

Formats: `m4a` (AAC, tagged with cover art) or `opus` (saved as `.webm`,
untagged). Without ffmpeg, MP3 or FLAC conversion isn't possible.

If the permission isn't granted, files go to the app's private storage
instead. The path is shown on screen.

## Files

- `main.py`: Kivy user interface
- `spotdl_bridge.py`: search, download and tagging logic
- `buildozer.spec`: Android build configuration
- `.github/workflows/build.yml`: GitHub Actions workflow that builds the APK
