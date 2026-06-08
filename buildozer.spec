[app]
title = SpotDL
package.name = spotdl
package.domain = com.spotdlapp

source.dir = app
source.include_exts = py,png,jpg,kv,atlas

version = 1.0

requirements = python3,kivy==2.3.0,spotdl,yt-dlp,mutagen,pillow,requests,cryptography,charset-normalizer,certifi,urllib3,idna,spotipy,ytmusicapi,syncedlyrics,beautifulsoup4,lxml

orientation = portrait
fullscreen = 0

android.permissions = INTERNET, WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE, MANAGE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 26
android.ndk = 25b
android.sdk = 33
android.accept_sdk_license = True
android.arch = arm64-v8a

android.gradle_dependencies = 'androidx.appcompat:appcompat:1.6.1'

[buildozer]
log_level = 2
warn_on_root = 1
