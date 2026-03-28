import querystring from "querystring";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).send("Method not allowed");

  // Slack sends form-encoded data, not JSON
  let body = req.body;
  if (typeof body === "string") {
    body = querystring.parse(body);
  }

  const { user_name, response_url } = body;

  // Immediately acknowledge Slack (must respond within 3 seconds)
  res.status(200).json({
    response_type: "in_channel",
    text: `*BHEL Appointment Bot started!* :rocket:\nTriggered by @${user_name || "user"}\nI'll send an OTP prompt here shortly. Stand by...`,
  });

  // Trigger GitHub Actions workflow_dispatch
  try {
    const ghRes = await fetch(
      `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/workflows/book.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: "main",
          inputs: {
            response_url: response_url || "",
            triggered_by: user_name || "user",
          },
        }),
      }
    );

    if (!ghRes.ok) {
      const err = await ghRes.text();
      console.error("GitHub Actions trigger failed:", err);
      await notifySlack(response_url, `:x: Failed to start bot: ${err}`);
    } else {
      console.log("GitHub Actions triggered successfully");
    }
  } catch (e) {
    console.error("Error:", e.message);
    await notifySlack(response_url, `:x: Error: ${e.message}`);
  }
}

async function notifySlack(url, text) {
  if (!url) return;
  try {
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  } catch (e) {
    console.error("Slack notify error:", e.message);
  }
}
