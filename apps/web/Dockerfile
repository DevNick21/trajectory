# AskPicky frontend.
#
# Two-stage:
#   1. Node 22 to build the Vite bundle.
#   2. Nginx-alpine to serve the static output + proxy /api -> backend.
#
# For dev with hot-reload, docker-compose runs `npm run dev` against
# this same image (bind-mount source, override CMD) — see
# `docker-compose.dev.yml`.

# ---- build stage -----------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . ./
RUN npm run build

# ---- runtime stage ---------------------------------------------------
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
