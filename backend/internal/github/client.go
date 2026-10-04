package github

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Client struct {
	HTTP                                       *http.Client
	ClientID, ClientSecret, PublicURL, AppSlug string
	apiURL, oauthURL                           string
}

func NewClient(id, secret, publicURL, slug string) *Client {
	return &Client{HTTP: &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}, ClientID: id, ClientSecret: secret, PublicURL: publicURL, AppSlug: slug, apiURL: "https://api.github.com", oauthURL: "https://github.com"}
}
func (c *Client) callbackURL() string { return c.PublicURL + "/api/connections/github/callback" }
func (c *Client) installURL() string {
	return "https://github.com/apps/" + url.PathEscape(c.AppSlug) + "/installations/new"
}
func (c *Client) exchange(ctx context.Context, values url.Values) (connection, error) {
	values.Set("client_id", c.ClientID)
	values.Set("client_secret", c.ClientSecret)
	req, err := http.NewRequestWithContext(ctx, "POST", c.oauthURL+"/login/oauth/access_token", strings.NewReader(values.Encode()))
	if err != nil {
		return connection{}, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	res, err := c.HTTP.Do(req)
	if err != nil {
		return connection{}, errors.New("GitHub token exchange failed")
	}
	defer res.Body.Close()
	var v struct {
		Access         string `json:"access_token"`
		Refresh        string `json:"refresh_token"`
		Expires        int64  `json:"expires_in"`
		RefreshExpires int64  `json:"refresh_token_expires_in"`
		Error          string `json:"error"`
	}
	if res.StatusCode != 200 || json.NewDecoder(io.LimitReader(res.Body, 65536)).Decode(&v) != nil || v.Error != "" || v.Access == "" {
		return connection{}, ErrDisconnected
	}
	if v.Expires <= 0 || v.Refresh == "" || v.RefreshExpires <= 0 {
		return connection{}, errors.New("enable expiring user access tokens for the GitHub App")
	}
	now := time.Now()
	return connection{Access: v.Access, Refresh: v.Refresh, Expires: now.Add(time.Duration(v.Expires) * time.Second), RefreshExpires: now.Add(time.Duration(v.RefreshExpires) * time.Second)}, nil
}
func (c *Client) api(ctx context.Context, method, path, token string, body any, result any) error {
	var data []byte
	var err error
	if body != nil {
		data, err = json.Marshal(body)
		if err != nil {
			return err
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, c.apiURL+path, bytes.NewReader(data))
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	} else {
		req.SetBasicAuth(c.ClientID, c.ClientSecret)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	res, err := c.HTTP.Do(req)
	if err != nil {
		return errors.New("GitHub request failed")
	}
	defer res.Body.Close()
	if res.StatusCode == 401 {
		return ErrDisconnected
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return fmt.Errorf("GitHub request failed (%d)", res.StatusCode)
	}
	if result != nil {
		return json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(result)
	}
	return nil
}
func (c *Client) identify(ctx context.Context, token string) (string, int64, error) {
	var u struct {
		Login string
		ID    int64
	}
	err := c.api(ctx, "GET", "/user", token, nil, &u)
	if err == nil && (u.Login == "" || u.ID == 0) {
		err = ErrDisconnected
	}
	return u.Login, u.ID, err
}
func (c *Client) revoke(ctx context.Context, token string) error {
	return c.api(ctx, "DELETE", "/applications/"+url.PathEscape(c.ClientID)+"/grant", "", map[string]string{"access_token": token}, nil)
}
