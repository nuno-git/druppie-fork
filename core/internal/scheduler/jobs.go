package scheduler

import (
	"context"
	"fmt"

	"github.com/sjhoeksma/druppie/core/internal/store"
)

// CleanupJob removes old plans
type CleanupJob struct {
	Store        store.Store
	CleanupDays  int
	CronSchedule string
}

func (j *CleanupJob) Name() string {
	return "Cleanup Plans"
}

func (j *CleanupJob) Schedule() string {
	if j.CronSchedule != "" {
		return j.CronSchedule
	}
	return "@daily" // Default
}

func (j *CleanupJob) Run(ctx context.Context) error {
	days := j.CleanupDays
	if days <= 0 {
		days = 7
	}
	fmt.Printf("[Cleanup] Checking for plans older than %d days...\n", days)

	count, err := j.Store.CleanupOldPlans(days)
	if err != nil {
		return err
	}
	if count > 0 {
		fmt.Printf("[Cleanup] Completed. Removed %d old plans.\n", count)
	}
	return nil
}

// LLMJob triggers an LLM task
type LLMJob struct {
	JobName      string
	PlanID       string
	Prompt       string
	CronSchedule string
	ExecuteFunc  func(ctx context.Context, planID, prompt string) error
}

func (j *LLMJob) Name() string {
	return j.JobName
}

func (j *LLMJob) Schedule() string {
	return j.CronSchedule
}

func (j *LLMJob) Run(ctx context.Context) error {
	if j.ExecuteFunc == nil {
		return fmt.Errorf("no execution function defined")
	}
	return j.ExecuteFunc(ctx, j.PlanID, j.Prompt)
}

// RegistryReloadJob reloads the registry
type RegistryReloadJob struct {
	JobName      string
	CronSchedule string
	ExecuteFunc  func(ctx context.Context) error
}

func (j *RegistryReloadJob) Name() string {
	return j.JobName
}

func (j *RegistryReloadJob) Schedule() string {
	return j.CronSchedule
}

func (j *RegistryReloadJob) Run(ctx context.Context) error {
	if j.ExecuteFunc == nil {
		return fmt.Errorf("no execution function defined")
	}
	fmt.Println("[Scheduler] Reloading Registry...")
	return j.ExecuteFunc(ctx)
}
