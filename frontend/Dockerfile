FROM node:22-alpine AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ARG NEXT_PUBLIC_MARKETING_URL
ENV NEXT_PUBLIC_MARKETING_URL=${NEXT_PUBLIC_MARKETING_URL}
ARG NEXT_PUBLIC_TURNSTILE_SITE_KEY
ENV NEXT_PUBLIC_TURNSTILE_SITE_KEY=${NEXT_PUBLIC_TURNSTILE_SITE_KEY}
ARG NEXT_PUBLIC_GA4_ID
ENV NEXT_PUBLIC_GA4_ID=${NEXT_PUBLIC_GA4_ID}
ARG NEXT_PUBLIC_ADS_ID
ENV NEXT_PUBLIC_ADS_ID=${NEXT_PUBLIC_ADS_ID}
ARG NEXT_PUBLIC_ADS_LABEL_ESSAI
ENV NEXT_PUBLIC_ADS_LABEL_ESSAI=${NEXT_PUBLIC_ADS_LABEL_ESSAI}
ARG NEXT_PUBLIC_ADS_LABEL_DEMO
ENV NEXT_PUBLIC_ADS_LABEL_DEMO=${NEXT_PUBLIC_ADS_LABEL_DEMO}

RUN npm run build

# Seul le serveur compilé et ses dépendances tracées entrent dans l'image finale.
# Pas de sources, de configuration TypeScript ou d'installation au démarrage.
FROM node:22-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Le code et node_modules restent non modifiables par le processus applicatif.
RUN mkdir -p .next/cache && chown -R node:node .next/cache

USER node
EXPOSE 3000

CMD ["node", "server.js"]
