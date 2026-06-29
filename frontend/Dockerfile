# ── Build ────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json .npmrc ./
RUN npm install --no-audit --no-fund

COPY . .

ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ── Runtime: Vite preview (React SPA + API proxy) ─────────────────────────
FROM node:20-alpine

WORKDIR /app

COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/vite.config.ts ./vite.config.ts
COPY --from=builder /app/dist ./dist

ENV VITE_DEV_API_TARGET=http://backend:8000

EXPOSE 3000

CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "3000"]
