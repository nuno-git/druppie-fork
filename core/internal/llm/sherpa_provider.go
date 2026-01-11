package llm

import (
	"archive/tar"
	"bytes"
	"compress/bzip2"
	"context"
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	sherpa "github.com/k2-fsa/sherpa-onnx-go/sherpa_onnx"
	"github.com/sjhoeksma/druppie/core/internal/model"
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
	"nl-nathalie": {
		Language:    "nl",
		Voice:       "nathalie",
		SubDir:      "vits-piper-nl_BE-nathalie-medium",
		DownloadURL: "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-nl_BE-nathalie-medium.tar.bz2",
		OnnxFile:    "nl_BE-nathalie-medium.onnx",
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

// ListVoices returns available voices for a language (or all if empty)
func ListVoices(lang string) []string {
	var voices []string
	for k, v := range sherpaRegistry {
		if lang == "" || strings.EqualFold(v.Language, lang) {
			voices = append(voices, fmt.Sprintf("%s (%s)", k, v.Voice))
		}
	}
	sort.Strings(voices)
	return voices
}

type SherpaTTSProvider struct {
	DefaultLang  string
	DefaultModel string

	modelsMu sync.Mutex
	models   map[string]*sherpa.OfflineTts

	baseDir      string
	PricePerWord float64
}

func NewSherpaTTSProvider(lang, modelName string, pricePerWord float64) (*SherpaTTSProvider, error) {
	// Determine paths usage
	// Use project relative path as requested
	baseDir := filepath.Join(".druppie", "sherpa")

	p := &SherpaTTSProvider{
		DefaultLang:  lang,
		DefaultModel: modelName,
		models:       make(map[string]*sherpa.OfflineTts),
		baseDir:      baseDir,
		PricePerWord: pricePerWord,
	}

	// Pre-load default model
	// Resolve default config
	_, err := p.getOrLoadModel(lang, modelName)
	if err != nil {
		fmt.Printf("Warning: Failed to pre-load default Sherpa model: %v\n", err)
		// Don't fail init, allow lazy load
	}

	return p, nil
}

func (p *SherpaTTSProvider) getOrLoadModel(lang, modelName string) (*sherpa.OfflineTts, error) {
	p.modelsMu.Lock()
	defer p.modelsMu.Unlock()

	// Logic: modelName takes precedence if specific key (e.g. 'nl-nathalie').
	// If generic ('dutch'), look up by lang.

	// Composite key for cache
	key := fmt.Sprintf("%s:%s", lang, modelName)
	if tts, ok := p.models[key]; ok {
		return tts, nil
	}
	// Also check if we have a model for just the lang cached
	if modelName == "" || modelName == "default" {
		// Check if any model for this lang is loaded?
		// For simplicity, we stick to strict keys or map generic to specific.
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

	// Double check cache with resolved voice name to avoid duplicates
	cacheKey := selectedConfig.Language // Simplify caching by Language for now (1 voice per lang active)
	// Or cache by voice name
	cacheKey = selectedConfig.Voice // "nathalie", "amy"
	if tts, ok := p.models[cacheKey]; ok {
		p.models[key] = tts // Alias
		return tts, nil
	}

	fullDir := filepath.Join(p.baseDir, selectedConfig.SubDir)

	// Download if missing
	if _, err := os.Stat(fullDir); os.IsNotExist(err) {
		fmt.Printf("[Sherpa] Downloading model %s (%s) from %s...\n", selectedConfig.Voice, selectedConfig.Language, selectedConfig.DownloadURL)
		if err := downloadAndExtract(selectedConfig.DownloadURL, p.baseDir); err != nil {
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

	p.models[key] = tts
	p.models[cacheKey] = tts
	// Also map lang code to this model
	p.models[selectedConfig.Language] = tts

	return tts, nil
}

func (p *SherpaTTSProvider) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	// Parse System Prompt for metadata
	// Convention: "Language: en" or JSON
	lang := p.DefaultLang
	modelName := p.DefaultModel

	// Simple check for "Language: <lang>" in systemPrompt
	lines := strings.Split(systemPrompt, "\n")
	for _, line := range lines {
		lower := strings.ToLower(strings.TrimSpace(line))
		if strings.HasPrefix(lower, "language:") {
			parts := strings.SplitN(lower, ":", 2)
			if len(parts) == 2 {
				lang = strings.TrimSpace(parts[1])
			}
		}
		if strings.HasPrefix(lower, "voice:") {
			parts := strings.SplitN(lower, ":", 2)
			if len(parts) == 2 {
				modelName = strings.TrimSpace(parts[1])
			}
		}
	}

	tts, err := p.getOrLoadModel(lang, modelName)
	if err != nil {
		return "", model.TokenUsage{}, err
	}

	// Generate Audio
	audio := tts.Generate(prompt, 0, 1.0)
	if len(audio.Samples) == 0 {
		return "", model.TokenUsage{}, fmt.Errorf("generated empty audio")
	}

	// Convert float32 samples to int16 PCM WAV
	wavBytes, err := encodeWav(audio.Samples, audio.SampleRate)
	if err != nil {
		return "", model.TokenUsage{}, err
	}

	// Calculate Cost
	wordCount := len(strings.Fields(prompt))
	cost := float64(wordCount) * p.PricePerWord

	return fmt.Sprintf("base64,%s", base64.StdEncoding.EncodeToString(wavBytes)), model.TokenUsage{EstimatedCost: cost}, nil
}

func (p *SherpaTTSProvider) Close() error {
	p.modelsMu.Lock()
	defer p.modelsMu.Unlock()
	// Clear map, let GC handle
	p.models = make(map[string]*sherpa.OfflineTts)
	return nil
}

// downloadAndExtract downloads a tar.bz2 and extracts it to destDir
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
			// Ensure dir exists
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

// encodeWav writes PCM WAV format
func encodeWav(samples []float32, sampleRate int) ([]byte, error) {
	buf := new(bytes.Buffer)

	// Format: RIFF/WAVE PCM 16bit mono
	numSamples := len(samples)
	numChannels := 1
	bitsPerSample := 16
	byteRate := sampleRate * numChannels * bitsPerSample / 8
	blockAlign := numChannels * bitsPerSample / 8
	dataSize := numSamples * numChannels * bitsPerSample / 8
	fileSize := 36 + dataSize

	// RIFF
	buf.WriteString("RIFF")
	binary.Write(buf, binary.LittleEndian, int32(fileSize))
	buf.WriteString("WAVE")

	// fmt
	buf.WriteString("fmt ")
	binary.Write(buf, binary.LittleEndian, int32(16))
	binary.Write(buf, binary.LittleEndian, int16(1))
	binary.Write(buf, binary.LittleEndian, int16(numChannels))
	binary.Write(buf, binary.LittleEndian, int32(sampleRate))
	binary.Write(buf, binary.LittleEndian, int32(byteRate))
	binary.Write(buf, binary.LittleEndian, int16(blockAlign))
	binary.Write(buf, binary.LittleEndian, int16(bitsPerSample))

	// data
	buf.WriteString("data")
	binary.Write(buf, binary.LittleEndian, int32(dataSize))

	for _, sample := range samples {
		// Clamp and scale
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
