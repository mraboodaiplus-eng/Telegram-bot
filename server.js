const express = require('express');
const puppeteer = require('puppeteer');
const path = require('path');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
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
  if (browser) return;
  console.log('>>> NEBULA: INITIALIZING CORE...');
  browser = await puppeteer.launch({
    headless: "new",
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--no-first-run',
      '--no-zygote',
      '--single-process'
    ],
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || null
  });
  page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  // Set a realistic user agent
  await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
  console.log('>>> NEBULA: CORE ONLINE.');
}

async function loginAndNavigate() {
  if (isLoggedIn) return;
  try {
    console.log('>>> NEBULA: ATTEMPTING AUTHENTICATION...');
    await page.goto('https://accounts.google.com/signin/v2/identifier?flowName=GlifWebSignIn&flowEntry=ServiceLogin', { waitUntil: 'networkidle2' });
    
    // Email Step
    await page.waitForSelector('input[type="email"]');
    await page.type('input[type="email"]', CREDENTIALS.email, { delay: 50 });
    await page.click('#identifierNext');
    
    // Password Step
    await page.waitForSelector('input[type="password"]', { visible: true, timeout: 20000 });
    await new Promise(r => setTimeout(r, 1500)); // Wait for animation
    await page.type('input[type="password"]', CREDENTIALS.password, { delay: 50 });
    await page.click('#passwordNext');
    
    await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 });
    
    console.log('>>> NEBULA: AUTHENTICATION SEQUENCE COMPLETE.');
    console.log(`>>> NEBULA: NAVIGATING TO TARGET SESSION [${AI_STUDIO_URL}]...`);
    await page.goto(AI_STUDIO_URL, { waitUntil: 'networkidle2' });
    
    // Wait for AI Studio to load
    await page.waitForSelector('textarea', { timeout: 60000 });
    isLoggedIn = true;
    console.log('>>> NEBULA: UPLINK ESTABLISHED. READY FOR COMMANDS.');
  } catch (error) {
    console.error('!!! NEBULA: UPLINK FAILED !!!', error);
    isLoggedIn = false;
    throw error;
  }
}

app.get('/api/status', (req, res) => {
  res.json({ 
    status: isLoggedIn ? 'ONLINE' : 'OFFLINE', 
    browser_active: !!browser,
    backend: 'NEBULA_CORE_V1' 
  });
});

app.post('/api/init', async (req, res) => {
  try {
    await initBrowser();
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
    
    // Clear and Type
    await page.click(inputSelector, { clickCount: 3 });
    await page.keyboard.press('Backspace');
    await page.type(inputSelector, message);
    
    // Send (Ctrl+Enter)
    await page.keyboard.down('Control');
    await page.keyboard.press('Enter');
    await page.keyboard.up('Control');
    
    // Wait for response - Improved logic: wait for the "Stop" button to disappear or a new bubble
    // For speed, we use a shorter initial wait then check for content
    await new Promise(r => setTimeout(r, 3000)); 
    
    // Poll for the response to be complete (AI Studio shows a 'Stop' button while generating)
    let isGenerating = true;
    let attempts = 0;
    while (isGenerating && attempts < 20) {
      isGenerating = await page.evaluate(() => {
        const stopButton = document.querySelector('button[aria-label*="Stop"], .stop-button');
        return !!stopButton;
      });
      if (isGenerating) {
        await new Promise(r => setTimeout(r, 1000));
        attempts++;
      }
    }

    const lastResponse = await page.evaluate(() => {
      // Try multiple selectors for AI Studio's evolving UI
      const bubbles = document.querySelectorAll('.model-turn, ms-chat-bubble[type="model"], .response-content'); 
      if (bubbles.length > 0) {
        return bubbles[bubbles.length - 1].innerText;
      }
      const outputArea = document.querySelector('ms-output-area, .output-container');
      return outputArea ? outputArea.innerText : "Response captured but content extraction failed.";
    });
    
    res.json({ response: lastResponse });
  } catch (error) {
    console.error('!!! NEBULA: EXECUTION ERROR !!!', error);
    res.status(500).json({ error: 'Transmission Error: ' + error.message });
  }
});

app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`>>> NEBULA SERVER LISTENING ON PORT ${PORT}`);
});
