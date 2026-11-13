# Black GPT

Black GPT is an independent AI chat application with its own visual identity and an editable system prompt. It is not affiliated with OpenAI and does not copy ChatGPT branding.

## Included

- Responsive Black GPT interface with dark/light themes
- Chat history, search, rename, delete, export and sharing
- Streaming assistant replies
- Custom system prompt that is sent with every API request and saved separately from chat history
- Temperature control
- Image and text-file attachments (image support depends on the selected model)
- Voice dictation in browsers that support Web Speech API
- Cloudflare Pages Function proxy; the API key is never placed in browser code

## Cloudflare Pages deployment

1. Keep `index.html`, `app.js`, `styles.css`, `wrangler.toml`, and the `functions` directory at the project root.
2. In Cloudflare Pages → Settings → Variables and Secrets, add these for Production (and Preview if needed):
   - `AI_API_KEY` — provider API key, stored as a secret.
   - `AI_BASE_URL` — for Groq: `https://api.groq.com/openai/v1`.
   - `AI_MODEL` — for example `openai/gpt-oss-120b`, or another model available to your provider.
3. Redeploy the Pages project after changing variables.

Do not put the API key in `app.js`, `index.html`, GitHub, or a browser-side `.env` file.

## Local preview

For the full API flow, use Cloudflare Pages local development (`wrangler pages dev`). A static file preview will display the interface but `/api/chat` requires the Pages Function.

## Prompt behavior

The system prompt editor is in **Настройки ИИ → Личность и промт**. The prompt is saved in its own local-storage key, independently from chat history, and is included in every request to `/api/chat`. The provider model still generates the actual answer, so instruction-following quality depends partly on the selected model.

## Current limitations

- Chat history and personalization settings are stored in the current browser; there are no user accounts or cross-device synchronization.
- PDF text extraction is not included.
- Image analysis requires a vision-capable model from the selected provider.
- Voice input depends on browser support and microphone permission.
