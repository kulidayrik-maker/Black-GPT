export async function onRequestPost({ request, env }) {
  const json = (body, status = 200) => new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
  });

  if (!env.AI_API_KEY) return json({ error: "На сервере не настроен AI_API_KEY." }, 503);
  const base = (env.AI_BASE_URL || "https://api.groq.com/openai/v1").replace(/\/+$/, "");
  const model = env.AI_MODEL || "openai/gpt-oss-120b";

  let body;
  try { body = await request.json(); }
  catch { return json({ error: "Некорректный JSON-запрос." }, 400); }

  if (!Array.isArray(body.messages) || body.messages.length === 0) {
    return json({ error: "В сообщении отсутствует история диалога." }, 400);
  }
  if (body.messages.length > 50) return json({ error: "Слишком длинная история. Начни новый чат." }, 413);

  const cleanMessages = [];
  for (const item of body.messages) {
    if (!item || !["user", "assistant"].includes(item.role)) continue;
    if (typeof item.content === "string") {
      if (item.content.length > 50000) return json({ error: "Одно из сообщений слишком большое." }, 413);
      cleanMessages.push({ role: item.role, content: item.content });
    } else if (item.role === "user" && Array.isArray(item.content)) {
      const parts = [];
      for (const part of item.content) {
        if (part?.type === "text" && typeof part.text === "string") {
          if (part.text.length > 50000) return json({ error: "Текст вложения слишком большой." }, 413);
          parts.push({ type: "text", text: part.text });
        } else if (part?.type === "image_url" && typeof part.image_url?.url === "string" && part.image_url.url.startsWith("data:image/")) {
          if (part.image_url.url.length > 12_000_000) return json({ error: "Изображение слишком большое." }, 413);
          parts.push({ type: "image_url", image_url: { url: part.image_url.url } });
        }
      }
      cleanMessages.push({ role: "user", content: parts });
    }
  }
  if (!cleanMessages.some(m => m.role === "user")) return json({ error: "Добавь сообщение пользователя." }, 400);

  const requestedPrompt = typeof body.systemPrompt === "string" ? body.systemPrompt.slice(0, 12000).trim() : "";
  const systemPrompt = requestedPrompt || "Ты — Denny AI, дружелюбный и полезный ИИ-помощник. Отвечай ясно и честно.";
  const temperature = Number.isFinite(body.temperature) ? Math.max(0, Math.min(1.5, body.temperature)) : 0.7;

  let upstream;
  try {
    upstream = await fetch(`${base}/chat/completions`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.AI_API_KEY}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "system", content: systemPrompt }, ...cleanMessages],
        temperature,
        stream: true
      })
    });
  } catch {
    return json({ error: "Не удалось подключиться к API модели. Проверь AI_BASE_URL." }, 502);
  }

  if (!upstream.ok) {
    let detail = "Провайдер ИИ вернул ошибку.";
    try {
      const data = await upstream.json();
      detail = data?.error?.message || data?.message || detail;
    } catch {}
    return json({ error: detail }, upstream.status >= 400 && upstream.status < 600 ? upstream.status : 502);
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no"
    }
  });
}
