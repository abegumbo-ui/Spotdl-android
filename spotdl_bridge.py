"""
spotdl_bridge.py — called from main.py in a background thread.
The `ui` object has a .log(msg, kind) method that routes back to the Kivy UI.
"""
import os
import traceback


def download_artist(artist_query: str, output_path: str, audio_format: str, ui):
    def log(msg, kind='info'):
        ui.log(str(msg), kind)

    try:
        log('Importing SpotDL...', 'info')
        from spotdl import Spotdl

        log('SpotDL ready ✓', 'success')
        os.makedirs(output_path, exist_ok=True)

        output_template = os.path.join(
            output_path, '{artist}', '{album}', '{title}.{output-ext}'
        )

        spotdl_instance = Spotdl(
            client_id='5f573c9620494bae87890c0f08a60293',
            client_secret='212476d9b0f3472eaa762d90b19b0ba8',
            downloader_settings={
                'output': output_template,
                'format': audio_format,
                'bitrate': 'auto',
                'threads': 2,
                'overwrite': 'skip',
                'log_level': 'ERROR',
            }
        )

        log(f"Searching for artist: '{artist_query}'...", 'info')
        songs = spotdl_instance.search([f'artist:{artist_query}'])

        if not songs:
            log(f"No tracks found for '{artist_query}'.", 'error')
            log("Try the exact name as it appears on Spotify.", 'warning')
            return

        total = len(songs)
        log(f'Found {total} tracks. Downloading...', 'success')

        done, failed = 0, 0
        for i, song in enumerate(songs, 1):
            try:
                log(f'[{i}/{total}] {song.artist} – {song.name}', 'info')
                spotdl_instance.download(song)
                done += 1
                log(f'  ✓ Saved', 'success')
            except Exception as e:
                failed += 1
                log(f'  ✗ {e}', 'error')

        log('━' * 30, 'info')
        log(f'Complete: {done} downloaded, {failed} failed.', 'success')

    except ImportError as e:
        log(f'Import error: {e}', 'error')
        log(traceback.format_exc(), 'error')
    except Exception as e:
        log(f'Error: {e}', 'error')
        log(traceback.format_exc(), 'error')
