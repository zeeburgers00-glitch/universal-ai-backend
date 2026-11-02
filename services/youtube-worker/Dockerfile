FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY services/youtube-worker/package.json ./package.json
RUN npm install
COPY services/youtube-worker/tsconfig.json ./tsconfig.json
COPY services/youtube-worker/src ./src
RUN npm run build
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
CMD ["node","dist/index.js"]