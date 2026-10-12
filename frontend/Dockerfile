FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS build
COPY tsconfig.json next.config.mjs postcss.config.mjs ./
COPY src ./src
# Rewrites are fixed at build time. Behind nginx `/api` never reaches this
# server; opened directly on its own port, the client still finds the API.
ARG API_ORIGIN=http://api:8000
ENV API_ORIGIN=$API_ORIGIN
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app
# The standalone bundle carries only the modules the server actually reached,
# so neither the sources nor the dev dependencies reach the running image.
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
USER app
EXPOSE 3000
CMD ["node", "server.js"]
