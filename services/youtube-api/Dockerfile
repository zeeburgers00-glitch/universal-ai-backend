FROM node:22-alpine AS build
WORKDIR /app
COPY services/youtube-api/package.json ./package.json
RUN npm install
COPY services/youtube-api/tsconfig.json ./tsconfig.json
COPY services/youtube-api/src ./src
RUN npm run build
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY catalog/youtube_creator_team.json ./catalog/youtube_creator_team.json
EXPOSE 8080
CMD ["node","dist/server.js"]
