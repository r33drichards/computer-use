import Button from "@cloudscape-design/components/button"
import { useCallback, useEffect, useRef, useState } from "react"
import { api, ApiError, type DesktopHistory, type HistoryClip } from "../api"
import { signedOutHandled } from "../auth/signedOut"
import { usePolling } from "../usePolling"
import { VncPane } from "./VncPane"
import "./DesktopViewer.css"

const CLIP_NAME = /^\d{13}-[a-f0-9]{8}\.mp4$/

export function clipAt(clips: HistoryClip[], time: number) {
  // Gaps (sleep, startup, resize) seek to the next available recording.
  return clips.find(c => time < c.start + c.duration * 1000) ?? clips.at(-1)
}

function behind(time: number, latest: number) {
  const seconds = Math.max(0, Math.round((latest - time) / 1000))
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s behind live`
}

export function DesktopViewer({ sessionId, controls }: { sessionId: string; controls?: HTMLElement | null }) {
  const [history, setHistory] = useState<DesktopHistory | null>(null)
  const [unavailable, setUnavailable] = useState("")
  const [minutes, setMinutes] = useState("5")
  const [saving, setSaving] = useState(false)
  const [replay, setReplay] = useState(false)
  const [selection, setSelection] = useState<{ clip: HistoryClip; offset: number; revision: number } | null>(null)
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [note, setNote] = useState("")
  const video = useRef<HTMLVideoElement>(null)
  const viewer = useRef<HTMLDivElement>(null)
  const initialized = useRef(false)
  const gone = useRef(false)
  // A poll started before a settings write must not overwrite its result.
  const generation = useRef(0)
  useEffect(() => {
    gone.current = false
    return () => { gone.current = true; generation.current++ }
  }, [])

  const load = useCallback(async () => {
    const mine = generation.current
    try {
      const result = await api.getHistory(sessionId)
      if (gone.current || mine !== generation.current) return
      setHistory(result)
      setUnavailable("")
      if (!initialized.current) {
        setMinutes(String(result.seconds / 60))
        initialized.current = true
      }
    } catch (err) {
      if (gone.current || mine !== generation.current || signedOutHandled(err)) return
      setUnavailable(err instanceof ApiError && err.status === 501 ? err.message : "History is unavailable right now.")
    }
  }, [sessionId])
  usePolling(load, true, 5000)

  const clips = history?.clips.filter(c => CLIP_NAME.test(c.name)) ?? []
  const first = clips[0]?.start ?? 0
  const last = clips.at(-1)
  const latest = last ? last.start + last.duration * 1000 : first

  function seek(time: number, play = playing) {
    const clip = clipAt(clips, time)
    if (!clip) return
    const offset = Math.max(0, Math.min((time - clip.start) / 1000, clip.duration - 0.05))
    setSelection(old => ({ clip, offset, revision: (old?.revision ?? 0) + 1 }))
    setPosition(clip.start + offset * 1000)
    setReplay(true)
    setPlaying(play)
    setNote("")
  }

  useEffect(() => {
    if (!selection || !history || history.clips.some(c => c.name === selection.clip.name)) return
    setSelection(null)
    setPlaying(false)
    setNote("This recording has expired. Choose another point or Go Live.")
  }, [history, selection])

  function prepare() {
    const el = video.current
    if (!el || !selection) return
    el.currentTime = selection.offset
    el.playbackRate = speed
    if (playing) void el.play().catch(() => { setPlaying(false); setNote("Press Play to continue.") })
  }
  useEffect(() => {
    const el = video.current
    if (el && el.readyState >= 1) prepare()
  }, [selection])
  useEffect(() => {
    const el = video.current
    if (!el) return
    el.playbackRate = speed
    if (playing) void el.play().catch(() => setPlaying(false))
    else el.pause()
  }, [playing, speed])

  function next() {
    const index = clips.findIndex(c => c.name === selection?.clip.name)
    const following = clips[index + 1]
    if (index >= 0 && following) seek(following.start, true)
    else {
      setPlaying(false)
      setNote("You’ve reached the latest recording. Go Live to interact with the desktop.")
    }
  }

  async function save() {
    setSaving(true)
    setNote("")
    const mine = ++generation.current
    try {
      const result = await api.setHistory(sessionId, Number(minutes) * 60)
      if (gone.current || mine !== generation.current) return
      setHistory(result)
      setMinutes(String(result.seconds / 60))
      setUnavailable("")
      initialized.current = true
      setNote(result.seconds ? "History window saved." : "Recording is off and saved history has been deleted.")
    } catch (err) {
      if (!gone.current && !signedOutHandled(err)) setNote(err instanceof Error ? err.message : "Couldn’t save the history window.")
    } finally {
      if (!gone.current) setSaving(false)
    }
  }

  const validMinutes = minutes.trim() !== "" && Number.isInteger(Number(minutes)) && Number(minutes) >= 0 && Number(minutes) <= 60
  return (
    <div className="desktop-viewer" ref={viewer}>
      <div className="desktop-history wf-box">
        <div className="desktop-history-bar">
          <strong>{replay ? behind(position, Date.now()) : "Live desktop"}</strong>
          <Button disabled={!clips.length || !!unavailable} onClick={() => seek(Math.max(first, latest - 30000), false)}>Rewind 30s</Button>
          <Button disabled={!replay} onClick={() => {
            setReplay(false); setPlaying(false); setSelection(null); setNote("")
          }}>Go Live</Button>
          <label>History window (minutes)
            <input aria-label="History window in minutes" type="number" min="0" max="60" step="1"
              value={minutes} onChange={e => setMinutes(e.target.value)} disabled={!history || saving} />
          </label>
          <Button loading={saving} disabled={!history || !validMinutes || Number(minutes) * 60 === history.seconds}
            onClick={save}>Save</Button>
        </div>
        <input className="desktop-history-timeline" aria-label="Desktop history timeline" type="range"
          min={first} max={Math.max(first + 1, latest)} step="100"
          value={replay ? Math.max(first, Math.min(position, latest)) : latest}
          disabled={!clips.length || !!unavailable} onChange={e => seek(Number(e.target.value), false)} />
        <div className="desktop-history-bar desktop-history-caption">
          <span>{clips.length ? `${new Date(first).toLocaleTimeString()} – ${new Date(latest).toLocaleTimeString()}` :
            history?.seconds === 0 ? "Recording is off." : "Waiting for the first recording…"}</span>
          <span>0 turns recording off and deletes history. Up to 60 minutes; storage is capped at 256 MiB.</span>
        </div>
        {replay && <div className="desktop-history-bar">
          <Button disabled={!selection} onClick={() => setPlaying(p => !p)}>{playing ? "Pause" : "Play"}</Button>
          {document.fullscreenEnabled && <Button onClick={async () => {
            try {
              if (document.fullscreenElement) await document.exitFullscreen()
              else await viewer.current?.requestFullscreen()
            } catch { setNote("Full screen is unavailable in this browser.") }
          }}>Full screen</Button>}
          <label>Playback speed <select aria-label="Playback speed" value={speed} onChange={e => setSpeed(Number(e.target.value))}>
            {[0.5, 1, 1.5, 2].map(n => <option key={n} value={n}>{n}×</option>)}
          </select></label>
          <span>Watching history. The desktop continues running; input is disabled.</span>
        </div>}
        {(unavailable || history?.error || note) && <p role="status">{unavailable || history?.error || note}</p>}
      </div>
      {replay ? <div className="desktop-history-playback">
        {selection ? <video ref={video} muted playsInline preload="auto"
          src={`/api/sessions/${encodeURIComponent(sessionId)}/history/${selection.clip.name}`}
          onLoadedMetadata={prepare} onEnded={next}
          onTimeUpdate={() => { if (video.current) setPosition(selection.clip.start + video.current.currentTime * 1000) }}
          onError={() => { setPlaying(false); setNote("This clip couldn’t be loaded. Try another point or Go Live.") }} /> :
          <p>{note || "Choose a point on the timeline."}</p>}
      </div> : <VncPane sessionId={sessionId} controls={controls} />}
    </div>
  )
}
