// api/book.js  — Vercel serverless function
// Receives /book slash command from Slack
// Triggers GitHub Actions workflow
// Sends immediate acknowledgement back to Slack

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).send("Method not allowed");

  const { text, user_name, response_url } = req.body;

  // Immediately acknowledge Slack (must respond within 3 seconds)
  res.status(200).json({
    response_type: "in_channel",
    text: `*BHEL Appointment Bot started!* :rocket:\n Triggered by @${user_name}\n I'll send an OTP prompt here shortly. Stand by...`,
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
            response_url: response_url,
            triggered_by: user_name,
          },
        }),
      }
    );

    if (!ghRes.ok) {
      const err = await ghRes.text();
      await notifySlack(response_url, `:x: Failed to start GitHub Actions: ${err}`);
    }
  } catch (e) {
    await notifySlack(response_url, `:x: Error triggering bot: ${e.message}`);
  }
}

async function notifySlack(url, text) {
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}
