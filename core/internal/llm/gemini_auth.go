package llm

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"

	"golang.org/x/oauth2"
	"golang.org/x/oauth2/google"
)

// getGeminiClientWithAuth handles the OAuth2 flow to get an authenticated HTTP client
func getGeminiClientWithAuth(ctx context.Context, model string, projectID, clientID, clientSecret string) (*http.Client, string, error) {
	// 1. Ensure Project ID is set (ask first, as requested)
	if projectID == "" {
		fmt.Printf("\n--- Gemini Setup ---\n")
		fmt.Printf("Enter your Google Cloud Project ID (string, e.g. 'my-project-id', NOT number): ")
		fmt.Scanln(&projectID)
		if projectID == "" {
			return nil, "", fmt.Errorf("project ID is required")
		}
		fmt.Printf("Using Project ID: %s (Add 'gemini.project_id' to config.yaml to skip this)\n", projectID)
	}

	// 2. Determine OAuth Configuration
	//    Look for client_secret.json first
	secretPath := "client_secret.json"
	var config *oauth2.Config

	if _, err := os.Stat(secretPath); err == nil {
		b, err := os.ReadFile(secretPath)
		if err != nil {
			return nil, "", fmt.Errorf("unable to read client secret file: %v", err)
		}
		config, err = google.ConfigFromJSON(b, "https://www.googleapis.com/auth/cloud-platform", "https://www.googleapis.com/auth/userinfo.email")
		if err != nil {
			return nil, "", fmt.Errorf("unable to parse client secret file to config: %v", err)
		}
	} else {
		if clientID == "" || clientSecret == "" {
			return nil, "", fmt.Errorf("client_id and client_secret are required for OAuth flow (add them to config.yaml under 'gemini')")
		}
		// Use Configured Creds
		config = &oauth2.Config{
			ClientID:     clientID,
			ClientSecret: clientSecret,
			Scopes: []string{
				"https://www.googleapis.com/auth/cloud-platform",
				"https://www.googleapis.com/auth/userinfo.email",
				"https://www.googleapis.com/auth/userinfo.profile",
			},
			Endpoint:    google.Endpoint,
			RedirectURL: "http://localhost:8085/oauth2callback",
		}
	}

	// 3. Get Token (cached or web)
	home, _ := os.UserHomeDir()
	tokenFile := filepath.Join(home, ".config", "druppie", "token.json")

	tok, err := tokenFromFile(tokenFile)
	if err != nil || !tok.Valid() {
		// No valid token, do the web dance
		tok, err = getTokenFromWeb(ctx, config)
		if err != nil {
			return nil, "", err
		}
		saveToken(tokenFile, tok)
	}

	// 4. Create Authenticated HTTP Client
	return config.Client(ctx, tok), projectID, nil
}

// getTokenFromWeb starts a local server to listen for the auth code
func getTokenFromWeb(ctx context.Context, config *oauth2.Config) (*oauth2.Token, error) {
	// Use fixed port 8085 to match the Redirect URI whitelist
	l, err := net.Listen("tcp", "127.0.0.1:8085")
	if err != nil {
		return nil, fmt.Errorf("failed to start local listener on port 8085 (is it in use?): %w", err)
	}
	defer l.Close()

	// Config already has correct RedirectURL

	authURL := config.AuthCodeURL("state-token", oauth2.AccessTypeOffline, oauth2.SetAuthURLParam("prompt", "consent"))
	fmt.Printf("\n--- Google Authentication Required ---\n")
	fmt.Printf("1. Open the following link in your browser:\n\n%v\n\n", authURL)
	fmt.Printf("2. Authenticate and accept permissions.\n")
	fmt.Printf("3. The browser will redirect to localhost:8085 and we will capture the code automatically.\n")

	codeCh := make(chan string)
	errCh := make(chan error)

	server := &http.Server{
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path != "/oauth2callback" {
				http.NotFound(w, r)
				return
			}
			code := r.URL.Query().Get("code")
			if code != "" {
				codeCh <- code
				fmt.Fprintf(w, "Authentication successful! You can close this window.")
			} else {
				errCh <- fmt.Errorf("no code found in response")
				fmt.Fprintf(w, "Authentication failed! No code found.")
			}
		}),
	}

	go func() {
		if err := server.Serve(l); err != nil && err != http.ErrServerClosed {
			errCh <- err
		}
	}()

	fmt.Println("Waiting for callback...")

	// Wait for code or error
	select {
	case code := <-codeCh:
		server.Shutdown(ctx)
		return config.Exchange(ctx, code)
	case err := <-errCh:
		server.Shutdown(ctx)
		return nil, err
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func tokenFromFile(file string) (*oauth2.Token, error) {
	f, err := os.Open(file)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	tok := &oauth2.Token{}
	err = json.NewDecoder(f).Decode(tok)
	return tok, err
}

func saveToken(path string, token *oauth2.Token) {
	fmt.Printf("Saving credential file to: %s\n", path)
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		log.Printf("Warning: failed to create config dir: %v", err)
	}

	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_TRUNC, 0600)
	if err != nil {
		log.Printf("Unable to cache oauth token: %v", err)
		return
	}
	defer f.Close()
	json.NewEncoder(f).Encode(token)
}
