package scheduler

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/robfig/cron/v3"
)

// Job defines a schedulable task
type Job interface {
	Name() string
	Schedule() string // Cron expression e.g. "0 0 * * *" or "@daily"
	Run(ctx context.Context) error
}

// Scheduler manages background jobs
type Scheduler struct {
	cron *cron.Cron
	mu   sync.Mutex
	jobs map[string]Job
}

func NewScheduler() *Scheduler {
	return &Scheduler{
		cron: cron.New(),
		jobs: make(map[string]Job),
	}
}

func (s *Scheduler) AddJob(j Job) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	id, err := s.cron.AddFunc(j.Schedule(), func() {
		fmt.Printf("⏰ [Scheduler] Running Job: %s\n", j.Name())
		// Create a context with timeout (e.g. 1 hour max for any job?)
		ctx, cancel := context.WithTimeout(context.Background(), 1*time.Hour)
		defer cancel()

		if err := j.Run(ctx); err != nil {
			fmt.Printf("❌ [Scheduler] Job %s failed: %v\n", j.Name(), err)
		} else {
			fmt.Printf("✅ [Scheduler] Job %s completed.\n", j.Name())
		}
	})
	if err != nil {
		return fmt.Errorf("failed to add job %s: %w", j.Name(), err)
	}
	s.jobs[j.Name()] = j
	fmt.Printf("📅 [Scheduler] Added Job: %s [%s] (ID: %d)\n", j.Name(), j.Schedule(), id)
	return nil
}

func (s *Scheduler) Start() {
	s.cron.Start()
	fmt.Println("🕰️ [Scheduler] Started.")
}

func (s *Scheduler) Stop() {
	s.cron.Stop()
	fmt.Println("🛑 [Scheduler] Stopped.")
}
