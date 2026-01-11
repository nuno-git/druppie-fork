package llm

import "context"

type loggerKey struct{}

// WithLogger returns a context with a logger function attached
func WithLogger(ctx context.Context, logger func(string)) context.Context {
	return context.WithValue(ctx, loggerKey{}, logger)
}

// Log sends a message to the logger attached to context, if any
func Log(ctx context.Context, msg string) {
	if logger, ok := ctx.Value(loggerKey{}).(func(string)); ok {
		logger(msg)
	}
}
