export const config = { runtime: "edge" };

export default async function handler(req) {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

  const text         = await req.text();
  const params       = new URLSearchParams(text);
  const user_name    = params.get("user_name") || "user";
  const response_url = params.get("response_url") || "";

  const ack = new Response(
    JSON.stringify({
      response_type: "in_channel",
      text: `:clipboard: *Fetching your upcoming appointments...*\nTriggered by @${user_name}`,
    }),
    { headers: { "Content-Type": "application/json" } }
  );

  fetch(
    `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/workflows/book.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "bhel-booking-bot",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          response_url: response_url,
          triggered_by: user_name,
          bot_mode: "orders",
        },
      }),
    }
  ).catch(console.error);

  return ack;
}
