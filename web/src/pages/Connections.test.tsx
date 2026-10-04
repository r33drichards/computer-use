// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "../api"
import { renderAt, startBackend } from "../test/harness"
import { Connections } from "./Connections"
import { CreateSession } from "./CreateSession"

vi.mock("../components/MonacoEditor", () => ({ default: () => null }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.__BROWSERJS_CFG__ = undefined })
const connection = { connected: true, login: "alice", install_url: "https://github.com/apps/computer-use/installations/new" }

describe("GitHub connections", () => {
  it("shows connected identity, repository selection and disconnect", async () => {
    startBackend()
    vi.spyOn(api, "githubConnection").mockResolvedValue(connection)
    const disconnect = vi.spyOn(api, "disconnectGitHub").mockResolvedValue(undefined)
    renderAt("/connections", [{ path: "/connections", element: <Connections /> }])
    await screen.findByText("Connected as @alice")
    expect(screen.getByRole("link", { name: "Select repositories on GitHub" }).getAttribute("href")).toBe(connection.install_url)
    vi.mocked(api.githubConnection).mockResolvedValue({ ...connection, connected: false })
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }))
    await waitFor(() => expect(disconnect).toHaveBeenCalledOnce())
    await screen.findByRole("button", { name: "Connect GitHub" })
  })

  it("enables GitHub by default and allows opt-out in session creation", async () => {
    const server = startBackend()
    window.__BROWSERJS_CFG__ = { githubConnections: true }
    vi.spyOn(api, "githubConnection").mockResolvedValue(connection)
    renderAt("/sessions/create", [{ path: "/sessions/create", element: <CreateSession /> }])
    const checkbox = await screen.findByRole("checkbox", { name: "Use GitHub connection as @alice" }) as HTMLInputElement
    expect(checkbox.checked).toBe(true)
    fireEvent.click(checkbox)
    fireEvent.click(screen.getByRole("button", { name: "Create session" }))
    await waitFor(() => expect(server.writes().find(r => r.path === "/api/sessions")?.body.github).toBe(false))
  })

  it("sends the default GitHub binding when creating a connected session", async () => {
    const server = startBackend()
    window.__BROWSERJS_CFG__ = { githubConnections: true }
    vi.spyOn(api, "githubConnection").mockResolvedValue(connection)
    renderAt("/sessions/create", [{ path: "/sessions/create", element: <CreateSession /> }])
    await screen.findByRole("checkbox", { name: "Use GitHub connection as @alice" })
    fireEvent.click(screen.getByRole("button", { name: "Create session" }))
    await waitFor(() => expect(server.writes().find(r => r.path === "/api/sessions")?.body.github).toBe(true))
  })
  it("requires reconnect or opt-out when the connection has expired", async () => {
    startBackend()
    window.__BROWSERJS_CFG__ = { githubConnections: true }
    vi.spyOn(api, "githubConnection").mockResolvedValue({ ...connection, needs_reconnect: true })
    renderAt("/sessions/create", [{ path: "/sessions/create", element: <CreateSession /> }])
    const checkbox = await screen.findByRole("checkbox", { name: "Use GitHub connection as @alice" })
    const create = screen.getByRole("button", { name: "Create session" }) as HTMLButtonElement
    expect(create.disabled).toBe(true)
    fireEvent.click(checkbox)
    expect(create.disabled).toBe(false)
  })

})
