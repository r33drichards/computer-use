# Desktop history MVP

The session page offers a rolling desktop recording alongside live VNC.
Use **Rewind 30s** or drag the timeline to review previous activity, then
**Go Live** to reconnect and interact. Playback is read-only: the session
continues running, and rewinding does not restore computer state.

Each session starts with a five-minute history window. Set its window to
1–60 whole minutes, or 0 to turn recording off and immediately delete its
history. Settings are stored on that session's volume and survive restarts.
Clips expire by wall-clock time; a 256 MiB cap can shorten the available window.

The browser image records the whole X11 desktop, including its cursor, in
five-second H.264 MP4 clips at 10 fps. Capture runs independently of viewers
while the pod is awake. Sleep, startup, resizes, and encoder restarts may leave
gaps; seeking into a gap selects the next available clip. Playback supports
pause, seek, speed changes, and full screen. Switching between clips may buffer
briefly. The newest completed clip trails live by roughly five seconds.

History routes are on the authenticated app host and have the same owner/admin
access checks as VNC. Polling, playback, and configuring history neither wake
a session nor renew its idle timer. Going live reconnects VNC, which counts as
activity as before. History is accessible only while the session is running;
after waking, unexpired clips on the volume are available again. Deleting the
session and its disk removes the history too.

## Deployment and validation

Deploy both the backend/web app and the rebuilt browser image. Existing images
without the recording endpoint report history as unsupported and retain live
VNC. The session-mode entrypoint sets `HISTORY_DIR` to `/data/chrome/desktop-history`;
the image supplies FFmpeg, ffprobe, and xdpyinfo. Standalone images do not enable
history automatically.

The API is `GET /api/sessions/{id}/history` (settings, recording status, and clip
metadata), `PUT` on that path with `{ "seconds": 300 }`, and authenticated
`GET /api/sessions/{id}/history/{clip-name}` with byte-range support. Responses
are uncached. Recorder failures appear in the viewer and retry automatically.

Run `node --test images/browser/test/history.test.mjs`, the backend proxy tests,
and the web tests/build. The browser image's `history-smoke` check verifies real
X11 recording and MP4 decoding on Linux.
