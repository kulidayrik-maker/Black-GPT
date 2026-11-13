export async function onRequestPost({ request, env }) {
  const json = (body, status = 200) => new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
  });

  // Image generation uses a separate provider key; the Groq chat key is never exposed or reused.
  const apiKey = env.OPENAI_API_KEY || env.IMAGE_API_KEY;
  if (!apiKey) {
    return json({ error: "Генерация изображений не подключена. Добавь OPENAI_API_KEY в Cloudflare Pages → Settings → Variables and Secrets (тип Secret)." }, 503);
  }

  let body;
  try { body = await request.json(); }
  catch { return json({ error: "Некорректный JSON-запрос." }, 400); }

  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (prompt.length < 3) return json({ error: "Опиши изображение подробнее." }, 400);
  if (prompt.length > 5000) return json({ error: "Описание слишком длинное: максимум 5000 символов." }, 413);

  const allowedSizes = new Set(["1024x1024", "1536x1024", "1024x1536"]);
  const allowedQualities = new Set(["low", "medium", "high"]);
  const size = allowedSizes.has(body.size) ? body.size : "1024x1024";
  const quality = allowedQualities.has(body.quality) ? body.quality : "medium";
  const model = typeof env.IMAGE_MODEL === "string" && env.IMAGE_MODEL.trim()
    ? env.IMAGE_MODEL.trim()
    : "gpt-image-2.5-flare";

  let upstream;
  try {
    upstream = await fetch("https://api.openai.com/v1/images/generations", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model,
        prompt,
        size,
        quality,
        n: 1,
        output_format: "png"
      })
    });
  } catch {
    return json({ error: "Не удалось подключиться к сервису генерации изображений." }, 502);
  }

  let data;
  try { data = await upstream.json(); }
  catch { return json({ error: "Сервис генерации вернул нечитаемый ответ." }, 502); }

  if (!upstream.ok) {
    const detail = data?.error?.message || data?.message || "Сервис генерации изображения вернул ошибку.";
    return json({ error: detail }, upstream.status >= 400 && upstream.status < 600 ? upstream.status : 502);
  }

  const first = Array.isArray(data?.data) ? data.data[0] : null;
  if (typeof first?.b64_json === "string" && first.b64_json.length > 100) {
    return json({
      image: `data:image/png;base64,${first.b64_json}`,
      revisedPrompt: typeof first.revised_prompt === "string" ? first.revised_prompt : "",
      model,
      size
    });
  }
  if (typeof first?.url === "string" && first.url.startsWith("https://")) {
    return json({ image: first.url, revisedPrompt: first.revised_prompt || "", model, size });
  }
  return json({ error: "Генератор завершил запрос, но не вернул изображение." }, 502);
}
