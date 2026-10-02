[app]
title = SpotDL
package.name = spotdl
package.domain = com.spotdlapp

# App sources live at the repository root.
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
source.exclude_dirs = .github, .buildozer, bin, tests

version = 1.4

# Only pure-Python libraries (plus p4a recipes) so the build works on Android.
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,pyjnius,android,openssl,sqlite3,certifi,requests,urllib3,idna,charset-normalizer,yt-dlp,ytmusicapi,mutagen,av,ffpyplayer_codecs

orientation = portrait
fullscreen = 0

android.permissions = INTERNET, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE, READ_MEDIA_AUDIO, MANAGE_EXTERNAL_STORAGE, FOREGROUND_SERVICE, POST_NOTIFICATIONS, WAKE_LOCK, ACCESS_WIFI_STATE
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.accept_sdk_license = True
android.archs = arm64-v8a
android.allow_backup = True

# The download job runs in this service so it keeps going with the app closed
# or the screen off (python-for-android foreground service + notification).
services = downloader:service.py:foreground

# Pinned stable python-for-android release (Python 3.11).
p4a.branch = v2024.01.21
p4a.local_recipes = ./p4a-recipes

[buildozer]
log_level = 2
warn_on_root = 0
