# Denny AI

ChatGPT-inspired personal AI chat interface. This is an independent project and is not affiliated with OpenAI.

## Included

- Responsive chat layout with sidebar and chat history
- Streaming assistant responses
- Editable system prompt in Settings → Поведение ИИ
- Temperature control
- Local chat history, search, rename, delete, export to Markdown
- Image and text-file attachments (image support depends on the selected model/provider)
- Voice dictation in browsers that support the Web Speech API
- Cloudflare Pages Function proxy so the API key is not exposed in the browser

## Deploy to Cloudflare Pages

1. Create a new Pages project and upload/deploy the contents of this folder (the `functions` folder must stay at the project root).
2. In Cloudflare Pages → your project → Settings → Environment variables, add:
   - `AI_API_KEY` — your provider API key (mark it as a secret).
   - `AI_BASE_URL` — for Groq use `https://api.groq.com/openai/v1`.
   - `AI_MODEL` — for example `openai/gpt-oss-120b`, or another model available to your provider.
3. Add the variables for both Production and Preview if you need both environments.
4. Redeploy the Pages project after adding or changing variables.

The API key belongs only in Cloudflare environment variables. Do not paste it into `app.js`, `index.html`, or a public GitHub repository. Never put it in a browser-side `.env` file.

## Local preview

The UI can be previewed by serving this directory with a static web server, but chat replies require the Cloudflare Pages Function at `/api/chat`. To test the full application locally, use the Cloudflare Pages local development workflow (`wrangler pages dev`).

## Notes and limitations

- Chat history and the editable prompt are stored in this browser's local storage. There is no user account or cloud synchronization in this starter version.
- PDF files are currently attached by name only; automatic PDF text extraction is not included.
- Voice dictation depends on browser support and may require microphone permission.
- Some providers/models do not accept image attachments. Choose a vision-capable model if image understanding is needed.
- The UI resembles common AI chat applications but uses its own Denny AI identity and does not copy OpenAI branding or claim to be ChatGPT.
