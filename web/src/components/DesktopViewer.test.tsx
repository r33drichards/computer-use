// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api, type DesktopHistory } from "../api"
import { clipAt, DesktopViewer } from "./DesktopViewer"

vi.mock("./VncPane", () => ({ VncPane: () => <div data-testid="live-desktop">Interactive desktop</div> }))

const start = 1720000000000
const clips = [0, 10000].map(offset => ({ name: `${start + offset}-1234abcd.mp4`, start: start + offset, duration: 5, bytes: 10 }))
const status: DesktopHistory = { seconds: 300, max_bytes: 256 << 20, clips, error: "" }

beforeEach(() => {
  vi.spyOn(api, "getHistory").mockResolvedValue(status)
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {})
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe("desktop DVR", () => {
  it("selects the next clip across a recording gap", () => {
    expect(clipAt(clips, start + 7000)).toEqual(clips[1])
    expect(clipAt(clips, start + 1000)).toEqual(clips[0])
  })

  it("disconnects the interactive desktop while scrubbing and reconnects on Go Live", async () => {
    const { container } = render(<DesktopViewer sessionId="s-aaaaaaaaaa" />)
    await waitFor(() => expect(screen.getByRole("slider")).toHaveProperty("disabled", false))
    expect(screen.getByTestId("live-desktop")).toBeTruthy()
    fireEvent.change(screen.getByRole("slider"), { target: { value: start + 7000 } })
    expect(screen.queryByTestId("live-desktop")).toBeNull()
    const el = container.querySelector("video")!
    expect(el.getAttribute("src")).toContain(clips[1].name)
    fireEvent.loadedMetadata(el)
    expect(el.currentTime).toBe(0)
    fireEvent.click(screen.getByRole("button", { name: "Go Live" }))
    expect(container.querySelector("video")).toBeNull()
    expect(screen.getByTestId("live-desktop")).toBeTruthy()
  })

  it("plays across clips and stays read-only at the newest recording", async () => {
    const { container } = render(<DesktopViewer sessionId="s-aaaaaaaaaa" />)
    await waitFor(() => expect(screen.getByRole("slider")).toHaveProperty("disabled", false))
    fireEvent.click(screen.getByRole("button", { name: "Rewind 30s" }))
    const el = container.querySelector("video")!
    fireEvent.loadedMetadata(el)
    fireEvent.click(screen.getByRole("button", { name: "Play" }))
    fireEvent.ended(el)
    expect(el.getAttribute("src")).toContain(clips[1].name)
    fireEvent.ended(el)
    expect(screen.getByText(/reached the latest recording/)).toBeTruthy()
    expect(screen.queryByTestId("live-desktop")).toBeNull()
  })

  it("saves a per-session window and clearing history stops playback", async () => {
    vi.spyOn(api, "setHistory").mockResolvedValue({ ...status, seconds: 0, clips: [] })
    render(<DesktopViewer sessionId="s-aaaaaaaaaa" />)
    await waitFor(() => expect(screen.getByRole("slider")).toHaveProperty("disabled", false))
    fireEvent.click(screen.getByRole("button", { name: "Rewind 30s" }))
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "0" } })
    fireEvent.click(screen.getByRole("button", { name: "Save" }))
    await waitFor(() => expect(api.setHistory).toHaveBeenCalledWith("s-aaaaaaaaaa", 0))
    await screen.findByText("Recording is off.")
    expect(screen.queryByTestId("live-desktop")).toBeNull()
    expect(screen.getByRole("button", { name: "Play" })).toHaveProperty("disabled", true)
  })
})
