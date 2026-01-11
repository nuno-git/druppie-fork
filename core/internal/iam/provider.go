package iam

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/go-chi/chi/v5"
	"github.com/sjhoeksma/druppie/core/internal/config"
	"golang.org/x/crypto/bcrypt"
)

// User represents an authenticated user
type User struct {
	ID       string   `json:"id"`
	Username string   `json:"username"`
	Email    string   `json:"email"`
	Groups   []string `json:"groups"` // Group IDs
}

type StoredUser struct {
	ID           string   `json:"id"`
	Username     string   `json:"username"`
	PasswordHash string   `json:"password_hash"`
	Email        string   `json:"email"`
	Groups       []string `json:"groups"` // Group IDs
}

type StoredGroup struct {
	ID           string   `json:"id"`
	Name         string   `json:"name"`
	MemberGroups []string `json:"member_groups"` // Groups included in this group (Nested)
}

type LoginRequest struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type LoginResponse struct {
	Token string `json:"token"`
	User  User   `json:"user"`
}

// Provider defines the interface for IAM providers
type Provider interface {
	Middleware() func(http.Handler) http.Handler
	GetUser(r *http.Request) (*User, error)
	RegisterRoutes(r chi.Router)
}

type contextKey string

const userContextKey contextKey = "iam_user"

// NewProvider creates the IAM provider
// NewProvider creates the IAM provider
func NewProvider(cfg config.IAMConfig, baseDir string) (Provider, error) {
	switch strings.ToLower(cfg.Provider) {
	case "keycloak":
		return NewKeycloakProvider(cfg.Keycloak), nil
	case "local":
		return NewLocalProvider(baseDir)
	case "demo":
		return NewDemoProvider(), nil
	default:
		fmt.Printf("Unknown IAM provider '%s', defaulting to local\n", cfg.Provider)
		return NewLocalProvider(baseDir)
	}
}

// --- Local Provider ---

type LocalProvider struct {
	storeDir string
	users    map[string]*StoredUser  // username -> user
	groups   map[string]*StoredGroup // id -> group
	sessions map[string]string       // token -> username
	mu       sync.RWMutex
}

func NewLocalProvider(baseDir string) (*LocalProvider, error) {
	iamDir := filepath.Join(baseDir, ".druppie", "iam")
	if err := os.MkdirAll(iamDir, 0755); err != nil {
		return nil, err
	}

	p := &LocalProvider{
		storeDir: iamDir,
		users:    make(map[string]*StoredUser),
		groups:   make(map[string]*StoredGroup),
		sessions: make(map[string]string),
	}

	if err := p.loadUsers(); err != nil {
		return nil, err
	}
	if err := p.loadGroups(); err != nil {
		return nil, err
	}
	if err := p.loadSessions(); err != nil {
		return nil, err
	}

	// Ensure admin GROUP exists
	if _, ok := p.groups["group-admin"]; !ok {
		p.groups["group-admin"] = &StoredGroup{ID: "group-admin", Name: "Administrators"}
		_ = p.saveGroups()
		fmt.Println("[IAM] Created default admin group (group-admin)")
	}

	// Ensure admin USER exists and has admin group
	if u, ok := p.users["admin"]; !ok {
		hash, _ := bcrypt.GenerateFromPassword([]byte("admin"), bcrypt.DefaultCost)
		admin := &StoredUser{
			ID:           "user-admin",
			Username:     "admin",
			PasswordHash: string(hash),
			Email:        "admin@druppie.local",
			Groups:       []string{"group-admin"},
		}
		p.users["admin"] = admin
		_ = p.saveUsers()
		fmt.Println("[IAM] Created default admin user (username: admin, password: admin)")
	} else {
		// Fix existing admin if missing group (migration fix)
		hasGroup := false
		for _, g := range u.Groups {
			if g == "group-admin" {
				hasGroup = true
				break
			}
		}
		if !hasGroup {
			u.Groups = append(u.Groups, "group-admin")
			_ = p.saveUsers()
			fmt.Println("[IAM] Fixed admin user: assigned 'group-admin' group")
		}
	}

	return p, nil
}

func (p *LocalProvider) loadUsers() error {
	path := filepath.Join(p.storeDir, "users.json")
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var usersList []*StoredUser
	if err := json.Unmarshal(data, &usersList); err != nil {
		return err
	}
	for _, u := range usersList {
		p.users[u.Username] = u
	}
	return nil
}

func (p *LocalProvider) loadGroups() error {
	path := filepath.Join(p.storeDir, "groups.json")
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var groupsList []*StoredGroup
	if err := json.Unmarshal(data, &groupsList); err != nil {
		return err
	}
	for _, g := range groupsList {
		p.groups[g.ID] = g
	}
	return nil
}

func (p *LocalProvider) saveUsers() error {
	path := filepath.Join(p.storeDir, "users.json")
	var usersList []*StoredUser
	for _, u := range p.users {
		usersList = append(usersList, u)
	}
	data, err := json.MarshalIndent(usersList, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0644)
}

func (p *LocalProvider) saveGroups() error {
	path := filepath.Join(p.storeDir, "groups.json")
	var groupsList []*StoredGroup
	for _, g := range p.groups {
		groupsList = append(groupsList, g)
	}
	data, err := json.MarshalIndent(groupsList, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0644)
}

func (p *LocalProvider) loadSessions() error {
	path := filepath.Join(p.storeDir, "sessions.json")
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, &p.sessions)
}

func (p *LocalProvider) saveSessions() error {
	path := filepath.Join(p.storeDir, "sessions.json")
	data, err := json.MarshalIndent(p.sessions, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0644)
}

func (p *LocalProvider) ReloadSessions() error {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.loadSessions()
}

// Login performs authentication for CLI
func (p *LocalProvider) Login(username, password string) (string, *User, error) {
	p.mu.RLock()
	u, ok := p.users[username]
	p.mu.RUnlock()

	if !ok {
		return "", nil, fmt.Errorf("invalid credentials")
	}

	if err := bcrypt.CompareHashAndPassword([]byte(u.PasswordHash), []byte(password)); err != nil {
		return "", nil, fmt.Errorf("invalid credentials")
	}

	token := generateToken()
	p.mu.Lock()
	p.sessions[token] = u.Username
	_ = p.saveSessions()
	p.mu.Unlock()

	return token, &User{
		ID:       u.ID,
		Username: u.Username,
		Email:    u.Email,
		Groups:   u.Groups,
	}, nil
}

// Logout removes the session for CLI
func (p *LocalProvider) Logout(token string) error {
	p.mu.Lock()
	delete(p.sessions, token)
	err := p.saveSessions()
	p.mu.Unlock()
	return err
}

func (p *LocalProvider) GetUserByToken(token string) (*User, bool) {
	p.mu.RLock()
	username, ok := p.sessions[token]
	p.mu.RUnlock()

	if !ok {
		return nil, false
	}

	p.mu.RLock()
	stored, exists := p.users[username]
	p.mu.RUnlock()

	if !exists {
		return nil, false
	}

	return &User{
		ID:       stored.ID,
		Username: stored.Username,
		Email:    stored.Email,
		Groups:   stored.Groups,
	}, true
}

func (p *LocalProvider) Middleware() func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if strings.HasSuffix(r.URL.Path, "/iam/login") || strings.HasSuffix(r.URL.Path, "/v1/health") {
				next.ServeHTTP(w, r)
				return
			}

			auth := r.Header.Get("Authorization")
			if auth == "" || !strings.HasPrefix(auth, "Bearer ") {
				http.Error(w, "Unauthorized: Login required", http.StatusUnauthorized)
				return
			}

			token := strings.TrimPrefix(auth, "Bearer ")
			p.mu.RLock()
			username, ok := p.sessions[token]
			p.mu.RUnlock()

			if ok {
				p.mu.RLock()
				stored, exists := p.users[username]
				var groups []string
				if exists {
					groups = stored.Groups
				}
				p.mu.RUnlock()

				if exists {
					u := &User{
						ID:       stored.ID,
						Username: stored.Username,
						Email:    stored.Email,
						Groups:   groups,
					}
					ctx := context.WithValue(r.Context(), userContextKey, u)
					next.ServeHTTP(w, r.WithContext(ctx))
					return
				}
			}
			http.Error(w, "Unauthorized: Invalid token", http.StatusUnauthorized)
		})
	}
}

func (p *LocalProvider) GetUser(r *http.Request) (*User, error) {
	u, ok := r.Context().Value(userContextKey).(*User)
	if !ok {
		return nil, fmt.Errorf("unauthorized")
	}
	return u, nil
}

func (p *LocalProvider) RegisterRoutes(r chi.Router) {
	r.Route("/iam", func(r chi.Router) {
		r.Post("/login", p.handleLogin)
		r.Post("/logout", p.handleLogout)

		r.Group(func(admin chi.Router) {
			admin.Use(p.RequireAdmin)
			// Users
			admin.Get("/users", p.handleListUsers)
			admin.Post("/users", p.handleCreateUser)
			admin.Put("/users/{username}", p.handleUpdateUser)
			admin.Delete("/users/{username}", p.handleDeleteUser)

			// Groups
			admin.Get("/groups", p.handleListGroups)
			admin.Post("/groups", p.handleCreateGroup)
			admin.Put("/groups/{id}", p.handleUpdateGroup)
			admin.Delete("/groups/{id}", p.handleDeleteGroup)
		})
	})
}

func (p *LocalProvider) RequireAdmin(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u, err := p.GetUser(r)
		if err != nil {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}
		isAdmin := false
		for _, g := range u.Groups {
			if g == "group-admin" || g == "admin" {
				isAdmin = true
				break
			}
		}
		if !isAdmin {
			http.Error(w, "Forbidden: Admins only", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// Handlers

func (p *LocalProvider) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req LoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request", http.StatusBadRequest)
		return
	}

	token, user, err := p.Login(req.Username, req.Password)
	if err != nil {
		http.Error(w, "Invalid credentials", http.StatusUnauthorized)
		return
	}

	resp := LoginResponse{Token: token, User: *user}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (p *LocalProvider) handleLogout(w http.ResponseWriter, r *http.Request) {
	auth := r.Header.Get("Authorization")
	if auth != "" && strings.HasPrefix(auth, "Bearer ") {
		token := strings.TrimPrefix(auth, "Bearer ")
		_ = p.Logout(token)
	}
	w.WriteHeader(http.StatusOK)
}

// Users CRUD

func (p *LocalProvider) handleListUsers(w http.ResponseWriter, r *http.Request) {
	p.mu.RLock()
	defer p.mu.RUnlock()

	// Let's project to safe struct
	type SafeUser struct {
		ID       string   `json:"id"`
		Username string   `json:"username"`
		Email    string   `json:"email"`
		Groups   []string `json:"groups"`
	}
	var res []SafeUser
	for _, u := range p.users {
		res = append(res, SafeUser{u.ID, u.Username, u.Email, u.Groups})
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(res)
}

func (p *LocalProvider) handleCreateUser(w http.ResponseWriter, r *http.Request) {
	// Password separately?
	type CreateReq struct {
		StoredUser
		Password string `json:"password"`
	}
	var creq CreateReq
	if err := json.NewDecoder(r.Body).Decode(&creq); err != nil {
		http.Error(w, "Invalid", http.StatusBadRequest)
		return
	}

	p.mu.Lock()
	defer p.mu.Unlock()

	if _, exists := p.users[creq.Username]; exists {
		http.Error(w, "Exists", http.StatusConflict)
		return
	}

	hash, _ := bcrypt.GenerateFromPassword([]byte(creq.Password), bcrypt.DefaultCost)
	creq.PasswordHash = string(hash)
	creq.ID = "user-" + creq.Username

	p.users[creq.Username] = &creq.StoredUser
	_ = p.saveUsers()
	w.WriteHeader(http.StatusCreated)
}

func (p *LocalProvider) handleUpdateUser(w http.ResponseWriter, r *http.Request) {
	username := chi.URLParam(r, "username")
	type UpdateReq struct {
		Email    string   `json:"email"`
		Groups   []string `json:"groups"`
		Password string   `json:"password,omitempty"`
	}
	var req UpdateReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid", http.StatusBadRequest)
		return
	}

	p.mu.Lock()
	defer p.mu.Unlock()

	u, ok := p.users[username]
	if !ok {
		http.Error(w, "Not found", http.StatusNotFound)
		return
	}

	u.Email = req.Email
	u.Groups = req.Groups
	if req.Password != "" {
		hash, _ := bcrypt.GenerateFromPassword([]byte(req.Password), bcrypt.DefaultCost)
		u.PasswordHash = string(hash)
	}

	_ = p.saveUsers()
	w.WriteHeader(http.StatusOK)
}

func (p *LocalProvider) handleDeleteUser(w http.ResponseWriter, r *http.Request) {
	username := chi.URLParam(r, "username")
	if username == "admin" {
		http.Error(w, "Forbidden", http.StatusForbidden)
		return
	}
	p.mu.Lock()
	delete(p.users, username)
	_ = p.saveUsers()
	p.mu.Unlock()
	w.WriteHeader(http.StatusOK)
}

// Groups CRUD

func (p *LocalProvider) handleListGroups(w http.ResponseWriter, r *http.Request) {
	p.mu.RLock()
	defer p.mu.RUnlock()
	var res []*StoredGroup
	for _, g := range p.groups {
		res = append(res, g)
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(res)
}

func (p *LocalProvider) handleCreateGroup(w http.ResponseWriter, r *http.Request) {
	var req StoredGroup
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid", http.StatusBadRequest)
		return
	}
	if req.ID == "" {
		req.ID = "group-" + strings.ToLower(strings.ReplaceAll(req.Name, " ", "-"))
	}

	p.mu.Lock()
	defer p.mu.Unlock()
	if _, exists := p.groups[req.ID]; exists {
		http.Error(w, "Exists", http.StatusConflict)
		return
	}
	p.groups[req.ID] = &req
	_ = p.saveGroups()
	w.WriteHeader(http.StatusCreated)
}

func (p *LocalProvider) handleUpdateGroup(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	var req StoredGroup
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid", http.StatusBadRequest)
		return
	}

	p.mu.Lock()
	defer p.mu.Unlock()
	g, ok := p.groups[id]
	if !ok {
		http.Error(w, "Not found", http.StatusNotFound)
		return
	}
	g.Name = req.Name
	g.MemberGroups = req.MemberGroups
	_ = p.saveGroups()
	w.WriteHeader(http.StatusOK)
}

func (p *LocalProvider) handleDeleteGroup(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	p.mu.Lock()
	delete(p.groups, id)
	_ = p.saveGroups()
	p.mu.Unlock()
	w.WriteHeader(http.StatusOK)
}

func generateToken() string {
	b := make([]byte, 16)
	rand.Read(b)
	return hex.EncodeToString(b)
}

// --- Keycloak Stub ---

type KeycloakProvider struct {
	cfg config.KeycloakConfig
}

func NewKeycloakProvider(cfg config.KeycloakConfig) *KeycloakProvider {
	return &KeycloakProvider{cfg: cfg}
}

func (p *KeycloakProvider) Middleware() func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Mock Keycloak User
			ctx := context.WithValue(r.Context(), userContextKey, &User{
				ID:       "keycloak-user",
				Username: "kcuser",
				Email:    "user@keycloak.local",
				Groups:   []string{"user"},
			})
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func (p *KeycloakProvider) GetUser(r *http.Request) (*User, error) {
	return nil, fmt.Errorf("not implemented")
}

func (p *KeycloakProvider) RegisterRoutes(r chi.Router) {
	// No local routes
}
