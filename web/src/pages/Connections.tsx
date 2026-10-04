import Alert from "@cloudscape-design/components/alert"
import Box from "@cloudscape-design/components/box"
import Button from "@cloudscape-design/components/button"
import Container from "@cloudscape-design/components/container"
import Header from "@cloudscape-design/components/header"
import SpaceBetween from "@cloudscape-design/components/space-between"
import { useCallback, useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { ApiError, type GitHubConnection } from "../api"
import { signedOutHandled } from "../auth/signedOut"
import { Shell, api } from "../shell"

export function Connections() {
  const [connection, setConnection] = useState<GitHubConnection | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [params] = useSearchParams()
  const load = useCallback(async () => {
    try { setConnection(await api.githubConnection()) }
    catch (e) {
      if (signedOutHandled(e)) return
      if (e instanceof ApiError && (e.status === 404 || e.status === 405)) setUnavailable(true)
      else setError(e instanceof Error ? e.message : String(e))
    }
  }, [])
  useEffect(() => { void load() }, [load])
  async function connect() {
    setBusy(true); setError("")
    try {
      const { url } = await api.connectGitHub()
      const target = new URL(url)
      if (target.origin !== "https://github.com" || target.pathname !== "/login/oauth/authorize") throw new Error("Invalid GitHub authorization URL")
      window.location.assign(url)
    } catch (e) { if (!signedOutHandled(e)) setError(e instanceof Error ? e.message : String(e)); setBusy(false) }
  }
  async function disconnect() {
    setBusy(true); setError("")
    try { await api.disconnectGitHub() }
    catch (e) { if (!signedOutHandled(e)) setError(e instanceof Error ? e.message : String(e)) }
    finally { await load(); setBusy(false) }
  }
  return <Shell breadcrumbs={[{ text: "Connections", href: "/connections" }]}>
    <SpaceBetween size="l">
      <Header variant="h1">Account connections</Header>
      {error && <Alert type="error">{error}</Alert>}
      {params.get("github") === "error" && <Alert type="error">GitHub authorization could not be completed. Try connecting again.</Alert>}
      {params.get("github") === "connected" && connection?.connected && <Alert type="success">GitHub connected. Select the repositories Computer Use can access on GitHub.</Alert>}
      <Container header={<Header variant="h2">GitHub</Header>}>
        <SpaceBetween size="m">
          {unavailable ? <Box>GitHub connections are not configured on this deployment.</Box> : !connection ? <Box>Loading connection…</Box> : <SpaceBetween size="m">
            <Box>{connection.connected ? `Connected as @${connection.login}` : "Connect your GitHub account to authenticate Git in new sessions automatically."}</Box>
            {connection.needs_reconnect && <Alert type="warning">Your GitHub authorization has expired. Reconnect to use it in new sessions.</Alert>}
            <Box>Install the Computer Use GitHub App on your account or organization and choose the repositories it can access. Organization access may require an administrator’s approval.</Box>
            <SpaceBetween size="s" direction="horizontal">
              <Button variant="primary" loading={busy} onClick={() => void connect()}>{connection.connected ? "Reconnect GitHub" : "Connect GitHub"}</Button>
              {connection.connected && <Button href={connection.install_url} target="_blank">Select repositories on GitHub</Button>}
              {connection.connected && <Button disabled={busy} onClick={() => void disconnect()}>Disconnect</Button>}
            </SpaceBetween>
            <Box>New sessions use this connection by default. Anyone who can run commands in a session can use its granted GitHub access. After reconnecting, create a new session to use the new connection.</Box>
          </SpaceBetween>}
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  </Shell>
}
