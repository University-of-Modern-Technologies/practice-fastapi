FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS build
# The API address is read by the browser bundle, so it has to be present while
# the bundle is produced rather than at container start.
ARG NEXT_PUBLIC_API_URL=/api/v1
ARG NEXT_PUBLIC_WS_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
COPY tsconfig.json next.config.mjs postcss.config.mjs ./
COPY src ./src
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production
ENV PORT=3100
ENV HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app
# The standalone bundle carries only the modules the server actually reached,
# so neither the sources nor the dev dependencies reach the running image.
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
USER app
EXPOSE 3100
CMD ["node", "server.js"]
