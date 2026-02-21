package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/tg123/sshpiper/libplugin"
	"github.com/urfave/cli/v2"
	"golang.org/x/crypto/ssh"
)

type plugin struct {
	EndpointURL  string
	BearerToken  string
	UpstreamHost string
	UpstreamPort int
	UpstreamUser string
	client       *http.Client
	banners      sync.Map
}

type upstreamSpec struct {
	Host       string `json:"host"`
	Port       int    `json:"port"`
	User       string `json:"user"`
	PrivateKey string `json:"private_key"`
}

type provisionResponse struct {
	Success bool         `json:"success"`
	Error   string       `json:"error"`
	Banner  string       `json:"banner"`
	Upstream upstreamSpec `json:"upstream"`
}

type provisionRequest struct {
	PublicKey string `json:"public_key"`
}

func newPlugin() *plugin {
	return &plugin{
		client: &http.Client{Timeout: 20 * time.Second},
	}
}

func (p *plugin) normalizePublicKey(key []byte) (string, error) {
	pub, err := ssh.ParsePublicKey(key)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(ssh.MarshalAuthorizedKey(pub))), nil
}

func (p *plugin) provision(key []byte) (*provisionResponse, error) {
	normalized, err := p.normalizePublicKey(key)
	if err != nil {
		return nil, err
	}

	reqBody, err := json.Marshal(provisionRequest{PublicKey: normalized})
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequest(http.MethodPost, p.EndpointURL, bytes.NewReader(reqBody))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+p.BearerToken)

	resp, err := p.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	payload, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	result := &provisionResponse{}
	if err := json.Unmarshal(payload, result); err != nil {
		return nil, err
	}

	if resp.StatusCode != http.StatusOK || !result.Success {
		if result.Error == "" {
			result.Error = fmt.Sprintf("provision failed with status %d", resp.StatusCode)
		}
		return nil, fmt.Errorf(result.Error)
	}

	if result.Upstream.Host == "" {
		result.Upstream.Host = p.UpstreamHost
	}
	if result.Upstream.Port == 0 {
		result.Upstream.Port = p.UpstreamPort
	}
	if result.Upstream.User == "" {
		result.Upstream.User = p.UpstreamUser
	}

	if result.Upstream.Host == "" || result.Upstream.User == "" || result.Upstream.PrivateKey == "" {
		return nil, fmt.Errorf("missing upstream parameters in provision response")
	}

	return result, nil
}

func main() {
	p := newPlugin()

	libplugin.CreateAndRunPluginTemplate(&libplugin.PluginTemplate{
		Name:  "dojo-sshpiper-plugin",
		Usage: "sshpiperd plugin for dojo ssh auto account creation",
		Flags: []cli.Flag{
			&cli.StringFlag{
				Name:        "endpoint",
				EnvVars:     []string{"SSHPIPER_PROVISION_ENDPOINT"},
				Required:    true,
				Destination: &p.EndpointURL,
			},
			&cli.StringFlag{
				Name:        "token",
				EnvVars:     []string{"SSHPIPER_PROVISION_TOKEN"},
				Required:    true,
				Destination: &p.BearerToken,
			},
			&cli.StringFlag{
				Name:        "upstream-host",
				Value:       "127.0.0.1",
				EnvVars:     []string{"SSHPIPER_UPSTREAM_HOST"},
				Destination: &p.UpstreamHost,
			},
			&cli.IntFlag{
				Name:        "upstream-port",
				Value:       2222,
				EnvVars:     []string{"SSHPIPER_UPSTREAM_PORT"},
				Destination: &p.UpstreamPort,
			},
			&cli.StringFlag{
				Name:        "upstream-user",
				Value:       "hacker",
				EnvVars:     []string{"SSHPIPER_UPSTREAM_USER"},
				Destination: &p.UpstreamUser,
			},
		},
		CreateConfig: func(_ *cli.Context) (*libplugin.SshPiperPluginConfig, error) {
			return &libplugin.SshPiperPluginConfig{
				NextAuthMethodsCallback: func(conn libplugin.ConnMetadata) ([]string, error) {
					_ = conn
					return []string{"publickey"}, nil
				},
				PublicKeyCallback: func(conn libplugin.ConnMetadata, key []byte) (*libplugin.Upstream, error) {
					result, err := p.provision(key)
					if err != nil {
						return nil, err
					}
					if result.Banner != "" {
						p.banners.Store(conn.UniqueID(), result.Banner)
					}
					return &libplugin.Upstream{
						Host:          result.Upstream.Host,
						Port:          int32(result.Upstream.Port),
						UserName:      result.Upstream.User,
						IgnoreHostKey: true,
						Auth:          libplugin.CreatePrivateKeyAuth([]byte(result.Upstream.PrivateKey)),
					}, nil
				},
				BannerCallback: func(conn libplugin.ConnMetadata) string {
					if banner, ok := p.banners.LoadAndDelete(conn.UniqueID()); ok {
						return banner.(string)
					}
					return ""
				},
			}, nil
		},
	})
}
