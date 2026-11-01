FROM node:22-alpine
WORKDIR /app
COPY package.json ./
# @freesewing/config and plugin-transform are listed explicitly: hugo/sven need them but do not declare them
RUN npm install --omit=dev --no-audit --no-fund
COPY src ./src
ENV PORT=7110
EXPOSE 7110
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://localhost:7110/health || exit 1
CMD ["node", "src/server.mjs"]
