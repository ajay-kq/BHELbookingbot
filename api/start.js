export const config = { runtime: "edge" };

export default async function handler(req) {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

  const text = await req.text();
  const params = new URLSearchParams(text);
  const user_name   = params.get("user_name")   || "user";
  const response_url = params.get("response_url") || "";

  // Immediately acknowledge Slack
  const ack = new Response(
    JSON.stringify({
      response_type: "in_channel",
      text: `:rocket: *BHEL Booking Bot starting!*\nTriggered by @${user_name}\nOpening portal and sending OTP to your phone...`,
    }),
    { headers: { "Content-Type": "application/json" } }
  );

  // Trigger GitHub Actions in background
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
        },
      }),
    }
  ).then(async (res) => {
    if (!res.ok) {
      const err = await res.text();
      console.error("GitHub trigger failed:", err);
      if (response_url) {
        await fetch(response_url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: `:x: Failed to start bot: ${err}` }),
        });
      }
    } else {
      console.log("GitHub Actions triggered OK");
    }
  }).catch((e) => console.error("Fetch error:", e.message));

  return ack;
}
