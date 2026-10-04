# Grow existing session disks to 32 GiB

Run this one-time migration before deploying the 32 GiB billing catalogue.
It is deliberately separate from the production Kustomization: normal releases
must not launch migrations. No live migration has been performed by this change.

The Job selects only non-deleting `data-s-*` PVCs with a Sandbox owner in
`agents.x-k8s.io` and the `browserjs-zonal` storage class. It requests 32Gi only
when the current request is smaller, using resourceVersion to reject concurrent
changes. Larger disks are preserved. The namespace Role permits only reading
and patching PVCs; it does not permit deleting claims or accessing Secrets.

Check the cluster context and review the claims before applying:

```sh
kubectl config current-context
kubectl -n browserjs-sessions get pvc
kubectl get storageclass browserjs-zonal -o yaml
kubectl kustomize deploy/migrations/session-disks-32gib
kubectl apply -k deploy/migrations/session-disks-32gib
kubectl -n browserjs-sessions logs -f job/session-disks-32gib
kubectl -n browserjs-sessions get job session-disks-32gib
kubectl -n browserjs-sessions get pvc
```

The live storage class must allow volume expansion. The Job waits up to 15
minutes per attempt for selected PVC status capacities to reach at least 32Gi.
It fails with the names of claims still pending. Requests already sent remain
in effect even if the Job fails. Inspect PVC conditions/events; stopped sessions
may need to start and mount the disk to finish filesystem expansion. Confirm
`df -h /data` in running sessions as well as PVC capacity before rolling out the
catalogue, which assumes every session has the same disk size.

A PVC deleted during migration remains in the pending report; inspect the
missing claim before rerunning. The Job does not recreate claims. Recheck claims
created while migration ran; update templates and drain/replenish the old warm
pool as part of rollout so no new 5Gi claims appear after verification.

To rerun after resolving a failure, delete only the Job and apply again:

```sh
kubectl -n browserjs-sessions delete job session-disks-32gib
kubectl apply -k deploy/migrations/session-disks-32gib
```

After verification, remove the migration Job, ConfigMap and its RBAC:

```sh
kubectl delete -k deploy/migrations/session-disks-32gib
```

Expansion preserves existing files and cannot be undone by shrinking the claim.
Do not edit PV capacity or recreate PVCs. See the
[GKE volume expansion guide](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/persistent-volumes/volume-expansion).
