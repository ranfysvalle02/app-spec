FROM node:22-slim

WORKDIR /app

COPY package.json .
RUN npm install

COPY tsconfig.json .
COPY *.ts ./
COPY static/ ./static/

RUN npm run build

EXPOSE 8000

CMD ["node", "dist/server.js"]
