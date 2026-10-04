// An open tab can still reference chunks removed by a newer deployment.
// Retry once per entry bundle and tab; persistent failures must not reload forever.
export function installChunkRecovery(target: Window, bundleURL: string) {
  const key = `chunk-recovery:${bundleURL}`
  target.addEventListener("vite:preloadError", () => {
    try {
      if (target.sessionStorage.getItem(key)) return
      target.sessionStorage.setItem(key, "1")
    } catch {
      // Without storage we cannot guarantee that a reload will terminate.
      return
    }
    target.location.reload()
  })
}
