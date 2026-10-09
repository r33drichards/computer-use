package proxy

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"mime"
	"net/http"
	"regexp"
	"strconv"
)

var historyClipName = regexp.MustCompile(`^\d{13}-[a-f0-9]{8}\.mp4$`)

type historyClip struct {
	Name     string  `json:"name"`
	Start    int64   `json:"start"`
	Duration float64 `json:"duration"`
	Bytes    int64   `json:"bytes"`
}

type historyStatus struct {
	Seconds  int           `json:"seconds"`
	MaxBytes int64         `json:"max_bytes"`
	Clips    []historyClip `json:"clips"`
	Error    string        `json:"error"`
}

func (p *Proxy) registerHistory(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/sessions/{id}/history", p.history)
	mux.HandleFunc("PUT /api/sessions/{id}/history", p.history)
	mux.HandleFunc("GET /api/sessions/{id}/history/{name}", p.history)
}

// History never wakes a pod or counts as activity. Recording runs only while
// the desktop is awake; reviewing it must not defeat idle sleep or billing.
func (p *Proxy) history(w http.ResponseWriter, r *http.Request) {
	id, ok := p.fileSession(w, r)
	if !ok {
		return
	}
	name := r.PathValue("name")
	if name != "" && !historyClipName.MatchString(name) {
		fileError(w, http.StatusNotFound, "clip not found")
		return
	}
	var body io.Reader
	if r.Method == http.MethodPut {
		if media, _, _ := mime.ParseMediaType(r.Header.Get("Content-Type")); media != "application/json" {
			fileError(w, http.StatusUnsupportedMediaType, "the body must be JSON")
			return
		}
		var asked struct {
			Seconds *int `json:"seconds"`
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024)).Decode(&asked) != nil ||
			asked.Seconds == nil || *asked.Seconds < 0 || *asked.Seconds > 3600 {
			fileError(w, http.StatusBadRequest, "history must be 0 to 3600 whole seconds")
			return
		}
		encoded, _ := json.Marshal(asked)
		body = bytes.NewReader(encoded)
	}
	s, err := p.running(r.Context(), id)
	if errors.Is(err, ErrNotRunning) {
		fileError(w, http.StatusConflict, "history is available while the session is running")
		return
	}
	if err != nil {
		lookupFailed(w, r, id, err)
		return
	}
	if name != "" {
		p.forwardWith(w, r, s, browserPort, "/history/"+name, p.quick, func(resp *http.Response) {
			length, contentRange := resp.Header.Get("Content-Length"), resp.Header.Get("Content-Range")
			clear(resp.Header)
			resp.Header.Set("Cache-Control", "no-store")
			if length != "" {
				resp.Header.Set("Content-Length", length)
			}
			if resp.StatusCode == http.StatusOK || resp.StatusCode == http.StatusPartialContent {
				resp.Header.Set("Content-Type", "video/mp4")
				resp.Header.Set("Accept-Ranges", "bytes")
			} else {
				resp.Header.Set("Content-Type", "text/plain; charset=utf-8")
			}
			if contentRange != "" {
				resp.Header.Set("Content-Range", contentRange)
			}
		})
		return
	}
	// Fresh request: never pass browser credentials or fetch headers to the pod.
	req, err := http.NewRequestWithContext(r.Context(), r.Method, "http://"+p.Target(s, browserPort)+"/history", body)
	if err != nil {
		fileError(w, 502, "history is unavailable")
		return
	}
	req.Host = "localhost:" + strconv.Itoa(browserPort)
	req.Header.Set("Content-Type", "application/json")
	resp, err := p.quick.RoundTrip(req)
	if err != nil {
		p.Waker.Invalidate(id)
		fileError(w, 502, "history is unavailable")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		fileError(w, http.StatusNotImplemented, "this session image does not support desktop history")
		return
	}
	var status historyStatus
	if resp.StatusCode != 200 || json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&status) != nil ||
		status.Seconds < 0 || status.Seconds > 3600 || status.MaxBytes <= 0 || status.MaxBytes > 256<<20 {
		fileError(w, 502, "the session did not return its history")
		return
	}
	clips := make([]historyClip, 0, len(status.Clips))
	var previous int64
	for _, c := range status.Clips {
		if !historyClipName.MatchString(c.Name) || c.Start <= 0 || c.Start < previous ||
			c.Duration <= 0 || c.Duration > 6 || c.Bytes <= 0 || c.Bytes > status.MaxBytes {
			continue
		}
		clips = append(clips, c)
		previous = c.Start
	}
	status.Clips = clips
	if status.Error != "" {
		status.Error = "Desktop recording is unavailable; retrying."
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	_ = json.NewEncoder(w).Encode(status)
}
