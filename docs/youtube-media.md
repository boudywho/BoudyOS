# Owner YouTube/media workflow

Use `.yt <URL>` from the BoudyOS owner account in the destination chat. The
assistant bot presents metadata, available practical video resolutions, M4A and
MP3 audio choices, timestamp controls, and a final confirmation. The downloaded
file is sent by the user account into the same chat as a reply to the original
command.

Timestamp choices include the full media, first 60 seconds, last 30 seconds, or
a custom follow-up such as `1:20-2:10`, `-45`, `3:00-`, or
`1:20-2:10, 4:00-4:30`. Use `.ytcancel` in the same chat, or the Cancel button,
to stop its pending or active request.

The assistant bot must be present in the chat and permitted to send and edit
messages so it can host the callback controls. FFmpeg and the pinned media
requirements (including yt-dlp) must be installed. Format sizes are estimates,
not filters; no Bot API 49 MiB rule is applied to this normal-user upload flow.
An operator can explicitly set `YTDL_MAX_BYTES` as a hard local safety ceiling.

Only download public media or media you are authorized to access, and follow
the source site's terms and applicable copyright law. This workflow does not
use cookies or attempt to bypass logins, DRM, paywalls, or CAPTCHAs. Playlists
are intentionally treated as a single-item request. URL search (`.yts`) is not
part of this release. Automated tests use fake extractor boundaries; no live
Telegram or YouTube smoke test is claimed.
