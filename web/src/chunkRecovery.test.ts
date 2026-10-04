import { describe, expect, it, vi } from "vitest"
import { installChunkRecovery } from "./chunkRecovery"

function browser(storage = new Map<string, string>()) {
  const events = new EventTarget()
  const reload = vi.fn()
  const target = Object.assign(events, {
    sessionStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value) },
    },
    location: { reload },
  })
  installChunkRecovery(target as unknown as Window, "entry-v1.js")
  return { target, reload }
}

describe("chunk recovery", () => {
  it("reloads once, including across page loads with the same bundle", () => {
    const storage = new Map<string, string>()
    const first = browser(storage)
    first.target.dispatchEvent(new Event("vite:preloadError"))
    first.target.dispatchEvent(new Event("vite:preloadError"))
    expect(first.reload).toHaveBeenCalledTimes(1)
    const next = browser(storage)
    next.target.dispatchEvent(new Event("vite:preloadError"))
    expect(next.reload).not.toHaveBeenCalled()
    installChunkRecovery(next.target as unknown as Window, "entry-v2.js")
    next.target.dispatchEvent(new Event("vite:preloadError"))
    expect(next.reload).toHaveBeenCalledTimes(1)
  })

  it("does not loop when session storage is unavailable", () => {
    const { target, reload } = browser()
    target.sessionStorage.getItem = () => { throw new Error("Storage blocked") }
    expect(() => target.dispatchEvent(new Event("vite:preloadError"))).not.toThrow()
    expect(reload).not.toHaveBeenCalled()
  })
})
