# Tiny isolated container for the final `git push`.
#
# This is the ONLY container that ever sees a real git credential.
# It reads a bundle produced by the main sandbox (opaque data; cannot
# contain executable code in a bare fetch) and pushes it to the remote.
#
# Run with:
#   docker run --rm \
#     --read-only --tmpfs /tmp:rw,size=128m \
#     --cap-drop=ALL --security-opt=no-new-privileges \
#     --network=bridge \
#     -e GIT_ASKPASS=/usr/local/bin/git-askpass \
#     -e GITHUB_TOKEN=ghs_xxx \
#     -e REMOTE_URL=https://github.com/org/repo \
#     -e BRANCH=feat/foo \
#     -v /host/tmp/run.bundle:/in/run.bundle:ro \
#     oneshot-push-sandbox

FROM alpine:3.21

RUN apk add --no-cache git ca-certificates

RUN addgroup -g 1000 push && adduser -D -u 1000 -G push push

COPY --chown=push:push entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chown=push:push git-askpass.sh /usr/local/bin/git-askpass
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/git-askpass

USER push
WORKDIR /tmp

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
