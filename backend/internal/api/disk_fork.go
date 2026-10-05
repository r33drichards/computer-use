package api

import (
	"github.com/r33drichards/computer-use/backend/internal/auth"
	"net/http"
)

// This staged release intentionally has NO enable switch or controller. Never
// fall back to Create, Sleep (memory checkpoint), or source disk reuse. Both
// surfaces fail closed until all admission and physical CSI gates are reviewed.
func (a *API) registerDiskFork(mux *http.ServeMux) {
	for _, prefix := range []string{"/api", "/v1"} {
		mux.HandleFunc("POST "+prefix+"/sessions/{id}/fork", a.session(func(w http.ResponseWriter, r *http.Request, id string) { a.diskForkDisabled(w) }))
		mux.HandleFunc("GET "+prefix+"/fork-operations/{operation}", a.user(func(w http.ResponseWriter, r *http.Request, u auth.User) { a.diskForkDisabled(w) }))
	}
}
func (a *API) diskForkDisabled(w http.ResponseWriter) {
	writeJSON(w, http.StatusNotImplemented, map[string]string{"code": "disk_fork_disabled", "error": "disk fork is unavailable: admission and CSI controller are not enabled"})
}
