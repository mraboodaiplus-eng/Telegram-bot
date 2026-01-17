FROM node:20-slim

# Install Puppeteer dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-thai-tlwg \
    fonts-kacst \
    fonts-freefont-ttf \
    libxss1 \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Build the frontend
RUN npm run build

# Expose the port
EXPOSE 3000

# Set environment variables for Puppeteer
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Start the server
CMD ["node", "server.js"]
