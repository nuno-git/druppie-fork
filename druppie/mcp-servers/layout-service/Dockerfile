FROM node:20-alpine

WORKDIR /app

RUN apk add --no-cache curl

COPY package.json ./
RUN npm install --omit=dev

ARG CACHEBUST
COPY server.js ./

EXPOSE 8090

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
  CMD curl -f http://localhost:8090/health || exit 1

CMD ["node", "server.js"]
