const express = require('express');
const puppeteer = require('puppeteer');
const path = require('path');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

// Serve static files from the React app build
app.use(express.static(path.join(__dirname, 'dist')));

let browser;
let page;
let isLoggedIn = false;

const CREDENTIALS = {
  email: process.env.GOOGLE_EMAIL,
  password: process.env.GOOGLE_PASSWORD
};

const AI_STUDIO_URL = process.env.AI_STUDIO_URL || 'https://aistudio.google.com/app/prompts/new';

async function initBrowser() {
  console.log('>>> NEBULA: INITIALIZING CORE...');
  browser = await puppeteer.launch({
    headless: "new",
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-accelerated-2d-canvas',
      '--no-first-run',
      '--no-zygote',
      '--single-process',
      '--disable-gpu'
    ],
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || null
  });
  page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  console.log('>>> NEBULA: CORE ONLINE.');
}

async function loginAndNavigate() {
  if (isLoggedIn) return;
  try {
    console.log('>>> NEBULA: ATTEMPTING AUTHENTICATION...');
    await page.goto('https://accounts.google.com', { waitUntil: 'networkidle2' });
    
    const emailSelector = 'input[type="email"]';
    await page.waitForSelector(emailSelector);
    await page.type(emailSelector, CREDENTIALS.email);
    await page.keyboard.press('Enter');
    
    const passwordSelector = 'input[type="password"]';
    await page.waitForSelector(passwordSelector, { visible: true, timeout: 10000 });
    await new Promise(r => setTimeout(r, 2000));
    await page.type(passwordSelector, CREDENTIALS.password);
    await page.keyboard.press('Enter');
    await page.waitForNavigation({ waitUntil: 'networkidle2' });
    
    console.log('>>> NEBULA: AUTHENTICATION SEQUENCE COMPLETE.');
    console.log(`>>> NEBULA: NAVIGATING TO TARGET SESSION [${AI_STUDIO_URL}]...`);
    await page.goto(AI_STUDIO_URL, { waitUntil: 'networkidle2' });
    
    await page.waitForSelector('textarea', { timeout: 30000 });
    isLoggedIn = true;
    console.log('>>> NEBULA: UPLINK ESTABLISHED. READY FOR COMMANDS.');
  } catch (error) {
    console.error('!!! NEBULA: UPLINK FAILED !!!', error);
    isLoggedIn = false;
    throw error;
  }
}

app.get('/api/status', (req, res) => {
  res.json({ status: isLoggedIn ? 'ONLINE' : 'OFFLINE', backend: 'NEBULA_CORE_V1' });
});

app.post('/api/init', async (req, res) => {
  try {
    if (!browser) await initBrowser();
    await loginAndNavigate();
    res.json({ success: true, message: 'Uplink Established' });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/chat', async (req, res) => {
  const { message } = req.body;
  if (!message) return res.status(400).json({ error: 'Payload empty' });
  try {
    if (!browser) await initBrowser();
    if (!isLoggedIn) await loginAndNavigate();
    
    const inputSelector = 'textarea';
    await page.waitForSelector(inputSelector);
    await page.click(inputSelector, { clickCount: 3 });
    await page.keyboard.press('Backspace');
    await page.type(inputSelector, message);
    
    await page.keyboard.down('Control');
    await page.keyboard.press('Enter');
    await page.keyboard.up('Control');
    
    await new Promise(r => setTimeout(r, 8000));
    await new Promise(r => setTimeout(r, 5000)); 
    
    const lastResponse = await page.evaluate(() => {
      const bubbles = document.querySelectorAll('.model-turn'); 
      if (bubbles.length > 0) {
        return bubbles[bubbles.length - 1].innerText;
      }
      const outputArea = document.querySelector('ms-output-area');
      return outputArea ? outputArea.innerText : "Remote execution successful, but output parsing failed.";
    });
    
    res.json({ response: lastResponse });
  } catch (error) {
    console.error('!!! NEBULA: EXECUTION ERROR !!!', error);
    res.status(500).json({ error: 'Transmission Error: ' + error.message });
  }
});

// Catch-all to serve React app
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`>>> NEBULA SERVER LISTENING ON PORT ${PORT}`);
});
