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

## One search bar

Type in the box on the main screen (or paste a link) and press **Search**.

- **Words:** Spotify and YouTube Music are searched at the same time, like a
  normal search bar. You get a top result, then Songs, Artists and Albums.
  Results appear as soon as the first service answers.
- **A link** (YouTube, YouTube Music or Spotify: song, album, playlist, artist,
  channel) shows a card saying what it is before anything is downloaded.
- **Artists** open to an artist page: Play, Shuffle and Download all, their top
  songs, and every album and single (tick them, or tap to open one).
- **Albums** open to the track list with Play, Shuffle, Queue and Download.
- **Songs:** a song found on both services is one row with two covers; tap a
  cover to choose whose title, album and cover art to use (the audio always
  comes from YouTube Music). Tap the title for the song's card. Tick songs and
  press **Download**.
- If Spotify can't be reached it is skipped after a few seconds (and left alone
  for 5 minutes), and YouTube Music results are still shown.

## Any website

Type or paste the address of a web page that has audio or video on it, with or
without `https://` (for example `example.com/some-page.html`). The app looks for
the media on the page (many sites such as SoundCloud and Bandcamp work, and plain
pages with a built-in player often do) and shows a card; **Download the audio**
saves it. Only the sound is kept: if the page only has video, its audio is saved
as an MP3. Titles and pictures come from the page, not YouTube Music.

It cannot get audio from copy-protected services (Spotify, Apple Music, Netflix,
Tidal), from pages that need a login, or from players it cannot read; the card
says so instead of failing silently.

## Faster downloads

Up to 5 songs download at the same time (Settings, default 3). Songs finish
in any order; track numbers are in the tags, so nothing is lost. Cancel and the
3 attempts per song work as before.

## Settings

The gear next to Library opens Settings:

- **Songs at once** (1 to 5).
- **Updates:** installed yt-dlp and ytmusicapi versions, when they were last
  checked, an automatic check at most **once a day** (only when a download
  starts, never during search; can be turned off) and **Check for updates now**.
- **Past downloads:** your recent jobs, each with **Fill gaps** and **Redo all**.
- **Check my library for broken songs:** finds empty, very short or unreadable
  files and offers to redo just those.
- **Upgrade mode** (off by default): when you download something you already
  have, also redo songs with no cover art or saved in a different format than
  the one selected.

If you press Download on something you already (partly) have, the app asks:
**Fill the gaps**, **Redo failed songs only** or **Redo everything**. A redo
builds each song in a side folder and replaces the old file only when the new
one is complete, so a failed redo never costs you a song.

## Listening before you download

Every song in the Search screen has a round **play** button. It finds the song
on YouTube Music exactly the way the download would, then streams that audio,
and a player bar shows the YouTube Music title, artist and album it matched, with
a seek bar. That is how you check it is the right song before downloading. Songs
that have finished downloading get the same button in the main list, and play
from the saved file. Tap a song's text to open its card: big cover, title, artist, album, year and
length, plus the YouTube Music song the download would use (with how many seconds
its length differs). Play it there, then press **Add to download** (tick boxes
still work on the list). Only one song plays at a time. Audio only, never video.

## Library and player

Press **Library** (top right of the main screen) to browse every song you have
downloaded. It reads the files' own tags, so it also finds songs you added by hand.

- **Songs / Albums / Artists / Lists / Favorites** tabs, a search box, and sorting
  (artist, title, newest, most played). Long lists load 80 at a time.
- Tap a song to play it; the rest of the list becomes the queue. The **...** menu
  has Play next, Add to queue, Add to playlist, Favorite, Song info and
  Delete from phone. The heart keeps a song in Favorites.
- **Lists:** your own playlists, plus Recently played, Most played and
  Recently added.
- **Shuffle** at the top plays the current list in random order.
- **Now playing** (tap the player bar): big cover, seek bar, previous / next,
  shuffle, repeat (off / all / one), favorite, a sleep timer (15 / 30 / 60 min)
  and the **Up next** queue, where you can jump to or remove songs.
- The Android back button closes the top screen first.
- Songs found in Search can be queued too (**Play next / Add to queue** on a
  song's card); they stream until you download them.

## Other alphabets

Titles in Hebrew, Spanish, Russian, Greek, Arabic, Armenian, Georgian and more
show with their real letters (nothing is translated). Hebrew and Arabic read right
to left. Chinese, Japanese, Korean, Thai and Indian scripts use the phone's own
fonts. The PDF report embeds a font so these letters appear there too.
Limits: Arabic letters are shown separately instead of joined, and Chinese,
Japanese and Korean show as boxes in the PDF.

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
- `search.py` / `search_screen.py` / `artist_page.py` / `album_page.py` / `browse_ui.py`: the search bar, artist and album pages
- `settings.py` / `settings_screen.py` / `history.py` / `history_screen.py`: settings, update schedule, past downloads
- `service.py`: runs the download in the background and reports progress
- `player.py` / `player_ui.py` / `now_playing.py`: the queue player, mini bar and full player
- `library.py` / `library_screen.py` / `sheets.py` / `covers.py`: the library, its screens and pop-ups
- `song_detail.py`: the song card in Search
- `fonts.py` / `pdf_font.py`: letters from other alphabets on screen and in the PDF
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
