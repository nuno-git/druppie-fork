package builder

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"

	tektonv1 "github.com/tektoncd/pipeline/pkg/apis/pipeline/v1"
	tektonclientset "github.com/tektoncd/pipeline/pkg/client/clientset/versioned"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/client-go/util/homedir"
)

// TektonClient implements BuildEngine for Tekton
type TektonClient struct {
	client    tektonclientset.Interface
	namespace string
}

// NewTektonClient creates a new Tekton client
// It attempts to load in-cluster config first, then falls back to local kubeconfig
func NewTektonClient(namespace string) (*TektonClient, error) {
	if namespace == "" {
		namespace = "default"
	}

	config, err := rest.InClusterConfig()
	if err != nil {
		// Fallback to local kubeconfig
		var kubeconfig string
		if home := homedir.HomeDir(); home != "" {
			kubeconfig = filepath.Join(home, ".kube", "config")
		} else {
			kubeconfig = os.Getenv("KUBECONFIG")
		}

		if kubeconfig == "" {
			return nil, fmt.Errorf("could not find kubeconfig and not running in cluster")
		}

		config, err = clientcmd.BuildConfigFromFlags("", kubeconfig)
		if err != nil {
			return nil, fmt.Errorf("failed to load kubeconfig: %w", err)
		}
	}

	clientset, err := tektonclientset.NewForConfig(config)
	if err != nil {
		return nil, fmt.Errorf("failed to create tekton clientset: %w", err)
	}

	return &TektonClient{
		client:    clientset,
		namespace: namespace,
	}, nil
}

// TriggerBuild creates a PipelineRun to build the repo
func (c *TektonClient) TriggerBuild(ctx context.Context, repoURL string, commitHash string, logWriter io.Writer) (string, error) {
	// Name generation
	runName := fmt.Sprintf("build-%s", filepath.Base(repoURL))
	// Sanitize name if needed, simple version for now

	pr := &tektonv1.PipelineRun{
		ObjectMeta: metav1.ObjectMeta{
			GenerateName: runName + "-",
			Namespace:    c.namespace,
			Labels: map[string]string{
				"3pi.dev/managed-by": "druppie",
				"3pi.dev/repo":       repoURL,
			},
		},
		Spec: tektonv1.PipelineRunSpec{
			PipelineRef: &tektonv1.PipelineRef{
				Name: "kaniko-build-pipeline", // Assumes this pipeline exists in the cluster
			},
			Params: []tektonv1.Param{
				{
					Name:  "repo-url",
					Value: tektonv1.ParamValue{Type: tektonv1.ParamTypeString, StringVal: repoURL},
				},
				{
					Name:  "commit-hash",
					Value: tektonv1.ParamValue{Type: tektonv1.ParamTypeString, StringVal: commitHash},
				},
			},
		},
	}

	createdPr, err := c.client.TektonV1().PipelineRuns(c.namespace).Create(ctx, pr, metav1.CreateOptions{})
	if err != nil {
		return "", fmt.Errorf("failed to create pipeline run: %w", err)
	}

	return createdPr.Name, nil
}

// GetBuildStatus checks the status of a PipelineRun
func (c *TektonClient) GetBuildStatus(ctx context.Context, buildID string) (string, error) {
	pr, err := c.client.TektonV1().PipelineRuns(c.namespace).Get(ctx, buildID, metav1.GetOptions{})
	if err != nil {
		return "", err
	}

	if len(pr.Status.Conditions) == 0 {
		return "Unknown", nil
	}

	// Simple status check based on usage of Knative generic conditions
	condition := pr.Status.Conditions[0]
	switch condition.Status {
	case "True":
		return "Succeeded", nil
	case "False":
		return "Failed", nil
	}

	return "Running", nil
}

func (c *TektonClient) IsLocal() bool {
	return false
}
