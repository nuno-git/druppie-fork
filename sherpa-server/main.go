package main

import (
	"archive/tar"
	"bytes"
	"compress/bzip2"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	sherpa "github.com/k2-fsa/sherpa-onnx-go/sherpa_onnx"
)

// SherpaModelInfo defines a VITS model
type SherpaModelInfo struct {
	Language    string
	Voice       string
	SubDir      string
	DownloadURL string
	OnnxFile    string
	TokensFile  string
	LexiconFile string // For DataDir
}

// Registry of known models
var sherpaRegistry = map[string]SherpaModelInfo{
	"en-amy": {
		Language:    "en",
		Voice:       "amy",
		SubDir:      "vits-piper-en_US-amy-low",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-amy-low.tar.bz2",
		OnnxFile:    "en_US-amy-low.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"en-lessac": {
		Language:    "en",
		Voice:       "lessac",
		SubDir:      "vits-piper-en_US-lessac-medium",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-lessac-medium.tar.bz2",
		OnnxFile:    "en_US-lessac-medium.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"en-bryce": {
		Language:    "en",
		Voice:       "bryce",
		SubDir:      "vits-piper-en_US-bryce-medium",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-bryce-medium.tar.bz2",
		OnnxFile:    "en_US-bryce-medium.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"en-alan": {
		Language:    "en",
		Voice:       "alan",
		SubDir:      "vits-piper-en_GB-alan-medium",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_GB-alan-medium.tar.bz2",
		OnnxFile:    "en_GB-alan-medium.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"nl-nathalie": {
		Language:    "nl",
		Voice:       "nathalie",
		SubDir:      "vits-piper-nl_BE-nathalie-medium",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-nl_BE-nathalie-medium.tar.bz2",
		OnnxFile:    "nl_BE-nathalie-medium.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"nl-pim": {
		Language:    "nl",
		Voice:       "pim",
		SubDir:      "vits-piper-nl_NL-pim-medium",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-nl_NL-pim-medium.tar.bz2",
		OnnxFile:    "nl_NL-pim-medium.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"nl-ronnie": {
		Language:    "nl",
		Voice:       "ronnie",
		SubDir:      "vits-piper-nl_NL-ronnie-medium",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-nl_NL-ronnie-medium.tar.bz2",
		OnnxFile:    "nl_NL-ronnie-medium.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"de-thorsten": {
		Language:    "de",
		Voice:       "thorsten",
		SubDir:      "vits-piper-de_DE-thorsten-low",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-de_DE-thorsten-low.tar.bz2",
		OnnxFile:    "de_DE-thorsten-low.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"fr-siwis": {
		Language:    "fr",
		Voice:       "siwis",
		SubDir:      "vits-piper-fr_FR-siwis-low",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-fr_FR-siwis-low.tar.bz2",
		OnnxFile:    "fr_FR-siwis-low.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
	"es-davefx": {
		Language:    "es",
		Voice:       "davefx",
		SubDir:      "vits-piper-es_ES-davefx-medium",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-es_ES-davefx-medium.tar.bz2",
		OnnxFile:    "es_ES-davefx-medium.onnx",
		TokensFile:  "tokens.txt",
		LexiconFile: "espeak-ng-data",
	},
}

type GenerateRequest struct {
	Text         string `json:"text"`
	Language     string `json:"language"`      // Optional
	Voice        string `json:"voice"`         // Optional
	SystemPrompt string `json:"system_prompt"` // Optional, for context/compatibility
}

type GenerateResponse struct {
	AudioBase64 string `json:"audio_base64"`
	Error       string `json:"error,omitempty"`
}

type ModelManager struct {
	modelsMu sync.Mutex
	models   map[string]*sherpa.OfflineTts
	baseDir  string
}

func NewModelManager(baseDir string) *ModelManager {
	return &ModelManager{
		models:  make(map[string]*sherpa.OfflineTts),
		baseDir: baseDir,
	}
}

func (m *ModelManager) GetOrLoadModel(lang, modelName string) (*sherpa.OfflineTts, error) {
	m.modelsMu.Lock()
	defer m.modelsMu.Unlock()

	// Logic: modelName takes precedence if specific key (e.g. 'nl-nathalie').
	// If generic ('dutch'), look up by lang.

	// Composite key for cache
	key := fmt.Sprintf("%s:%s", lang, modelName)
	if tts, ok := m.models[key]; ok {
		return tts, nil
	}

	// Resolve Config
	var selectedConfig SherpaModelInfo
	found := false

	// Try direct key match
	if info, ok := sherpaRegistry[strings.ToLower(modelName)]; ok {
		selectedConfig = info
		found = true
	} else {
		// Search by language
		searchLang := lang
		if searchLang == "" {
			// Infer from modelName
			if strings.Contains(strings.ToLower(modelName), "dutch") || modelName == "nl" {
				searchLang = "nl"
			} else if strings.Contains(strings.ToLower(modelName), "english") || modelName == "en" {
				searchLang = "en"
			} else {
				searchLang = "en" // Default
			}
		}

		// Find first match for language
		for _, info := range sherpaRegistry {
			if strings.EqualFold(info.Language, searchLang) {
				selectedConfig = info
				found = true
				break
			}
		}
	}

	if !found {
		// Fallback to English Amy
		selectedConfig = sherpaRegistry["en-amy"]
	}

	// Double check cache with resolved voice name
	cacheKey := selectedConfig.Language
	// Or cache by voice name
	if tts, ok := m.models[cacheKey]; ok {
		m.models[key] = tts
		return tts, nil
	}

	fullDir := filepath.Join(m.baseDir, selectedConfig.SubDir)

	// Download if missing
	if _, err := os.Stat(fullDir); os.IsNotExist(err) {
		log.Printf("[Sherpa] Downloading model %s (%s) from %s...\n", selectedConfig.Voice, selectedConfig.Language, selectedConfig.DownloadURL)
		if err := downloadAndExtract(selectedConfig.DownloadURL, m.baseDir); err != nil {
			return nil, fmt.Errorf("failed to download model: %w", err)
		}
	}

	// Initialize Config
	config := sherpa.OfflineTtsConfig{
		Model: sherpa.OfflineTtsModelConfig{
			Vits: sherpa.OfflineTtsVitsModelConfig{
				Model:   filepath.Join(fullDir, selectedConfig.OnnxFile),
				Tokens:  filepath.Join(fullDir, selectedConfig.TokensFile),
				DataDir: filepath.Join(fullDir, selectedConfig.LexiconFile),
			},
			Provider:   "cpu",
			NumThreads: 1,
			Debug:      0,
		},
	}

	tts := sherpa.NewOfflineTts(&config)
	if tts == nil {
		return nil, fmt.Errorf("failed to create sherpa tts instance")
	}

	m.models[key] = tts
	m.models[selectedConfig.Language] = tts
	m.models[selectedConfig.Voice] = tts

	return tts, nil
}

func downloadAndExtract(url, destDir string) error {
	if err := os.MkdirAll(destDir, 0755); err != nil {
		return err
	}

	resp, err := http.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("bad status: %s", resp.Status)
	}

	bz2Reader := bzip2.NewReader(resp.Body)
	tarReader := tar.NewReader(bz2Reader)

	for {
		header, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}

		target := filepath.Join(destDir, header.Name)
		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
				return err
			}
			f, err := os.OpenFile(target, os.O_CREATE|os.O_RDWR, os.FileMode(header.Mode))
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tarReader); err != nil {
				f.Close()
				return err
			}
			f.Close()
		}
	}
	return nil
}

func encodeWav(samples []float32, sampleRate int) ([]byte, error) {
	buf := new(bytes.Buffer)

	numSamples := len(samples)
	numChannels := 1
	bitsPerSample := 16
	byteRate := sampleRate * numChannels * bitsPerSample / 8
	blockAlign := numChannels * bitsPerSample / 8
	dataSize := numSamples * numChannels * bitsPerSample / 8
	fileSize := 36 + dataSize

	buf.WriteString("RIFF")
	binary.Write(buf, binary.LittleEndian, int32(fileSize))
	buf.WriteString("WAVE")
	buf.WriteString("fmt ")
	binary.Write(buf, binary.LittleEndian, int32(16))
	binary.Write(buf, binary.LittleEndian, int16(1))
	binary.Write(buf, binary.LittleEndian, int16(numChannels))
	binary.Write(buf, binary.LittleEndian, int32(sampleRate))
	binary.Write(buf, binary.LittleEndian, int32(byteRate))
	binary.Write(buf, binary.LittleEndian, int16(blockAlign))
	binary.Write(buf, binary.LittleEndian, int16(bitsPerSample))
	buf.WriteString("data")
	binary.Write(buf, binary.LittleEndian, int32(dataSize))

	for _, sample := range samples {
		val := sample * 32767
		if val > 32767 {
			val = 32767
		}
		if val < -32768 {
			val = -32768
		}
		binary.Write(buf, binary.LittleEndian, int16(val))
	}

	return buf.Bytes(), nil
}

func main() {
	port := flag.Int("port", 8081, "Port to listen on")
	modelsDir := flag.String("models-dir", "models", "Directory to store models")
	flag.Parse()

	if err := os.MkdirAll(*modelsDir, 0755); err != nil {
		log.Fatalf("Failed to create models directory: %v", err)
	}

	manager := NewModelManager(*modelsDir)

	r := chi.NewRouter()
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)

	r.Post("/generate", func(w http.ResponseWriter, r *http.Request) {
		var req GenerateRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid request body", http.StatusBadRequest)
			return
		}

		// Handle context from SystemPrompt if needed, logic copied from original provider
		if req.Language == "" || req.Voice == "" {
			lines := strings.Split(req.SystemPrompt, "\n")
			for _, line := range lines {
				lower := strings.ToLower(strings.TrimSpace(line))
				if strings.HasPrefix(lower, "language:") {
					parts := strings.SplitN(lower, ":", 2)
					if len(parts) == 2 {
						req.Language = strings.TrimSpace(parts[1])
					}
				}
				if strings.HasPrefix(lower, "voice:") {
					parts := strings.SplitN(lower, ":", 2)
					if len(parts) == 2 {
						req.Voice = strings.TrimSpace(parts[1])
					}
				}
			}
		}

		tts, err := manager.GetOrLoadModel(req.Language, req.Voice)
		if err != nil {
			http.Error(w, fmt.Sprintf("Failed to load model: %v", err), http.StatusInternalServerError)
			return
		}

		audio := tts.Generate(req.Text, 0, 1.0)
		if len(audio.Samples) == 0 {
			http.Error(w, "Generated empty audio", http.StatusInternalServerError)
			return
		}

		wavBytes, err := encodeWav(audio.Samples, audio.SampleRate)
		if err != nil {
			http.Error(w, fmt.Sprintf("Failed to encode WAV: %v", err), http.StatusInternalServerError)
			return
		}

		resp := GenerateResponse{
			AudioBase64: base64.StdEncoding.EncodeToString(wavBytes),
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	})

	// Add health check
	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("OK"))
	})

	log.Printf("Starting Sherpa Server on :%d", *port)
	if err := http.ListenAndServe(fmt.Sprintf(":%d", *port), r); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
