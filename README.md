# Nebula - Security Validation Platform (Render Optimized)

This project is a full-stack application that automates interactions with Google AI Studio using Puppeteer.

## Deployment on Render

1.  **Create a New Web Service** on Render.
2.  **Connect this Repository**.
3.  **Select Runtime:** Docker.
4.  **Environment Variables:**
    *   `GOOGLE_EMAIL`: `dangerforyouaccouents@gmail.con`
    *   `GOOGLE_PASSWORD`: `12345098765qwertpoiuyt`
    *   `AI_STUDIO_URL`: `https://aistudio.google.com/u/3/prompts/19-FE9TkNS7CpJAmLStYEYOc7SdqlVPhC`
    *   `GEMINI_API_KEY`: Your Gemini API Key.
    *   `PORT`: 3000 (Render will handle this automatically).

## Features
- Automated Google Authentication.
- Dynamic response polling for faster interactions.
- React-based terminal interface.

## Security Note
Ensure that the Google account used does not have 2FA enabled for the automation to work seamlessly.
