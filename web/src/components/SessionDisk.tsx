import Button from "@cloudscape-design/components/button"
import FormField from "@cloudscape-design/components/form-field"
import Input from "@cloudscape-design/components/input"
import Modal from "@cloudscape-design/components/modal"
import SpaceBetween from "@cloudscape-design/components/space-between"
import { useEffect, useState } from "react"
import type { Session } from "../api"
import { api } from "../shell"
import type { Sizes } from "../sizes"

export function SessionDisk({ session, run }: { session: Session; run: (fn: () => Promise<unknown>) => Promise<boolean> }) {
  const [limits, setLimits] = useState<Sizes["storage"]>()
  const [open, setOpen] = useState(false)
  const [capacity, setCapacity] = useState("")
  const [busy, setBusy] = useState(false)
  useEffect(() => { let active = true; api.listSizes().then(s => { if (active) setLimits(s.storage) }).catch(() => {}); return () => { active = false } }, [])
  if (!session.diskGB) return null
  const value = Number(capacity)
  const valid = limits && Number.isInteger(value) && value > session.diskGB && value <= limits.maxGB
  async function grow() {
    setBusy(true)
    const ok = await run(() => api.growDisk(session.id, value))
    setBusy(false)
    if (ok) setOpen(false)
  }
  return <span>
    disk: {session.diskGB} GB{" "}
    {limits && session.diskGB < limits.maxGB && <Button variant="inline-link" onClick={() => { setCapacity(String(session.diskGB)); setOpen(true) }}>expand disk</Button>}
    {open && <Modal visible={open} onDismiss={() => setOpen(false)} header={`Expand the disk of ${session.name}`} footer={<Button variant="primary" disabled={!valid} loading={busy} onClick={grow}>Expand disk</Button>}>
      <SpaceBetween size="m">
        <FormField label="Capacity (GB)" description={`Up to ${limits?.maxGB ?? 128} GB for your account. Files are preserved. Disks cannot be shrunk.`}>
          <Input type="number" value={capacity} onChange={({ detail }) => setCapacity(detail.value)} />
        </FormField>
      </SpaceBetween>
    </Modal>}
  </span>
}
