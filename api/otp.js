// api/otp.js  — Vercel serverless function
// Slack sends OTP here when user types it in Slack
// This writes OTP to a GitHub Actions variable so the running workflow can read it

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).send("Method not allowed");

  const { text, user_name } = req.body;
  const otp = (text || "").trim();

  if (!otp || !/^\d{4,8}$/.test(otp)) {
    return res.status(200).json({
      response_type: "ephemeral",
      text: `:warning: Invalid OTP format. Please type just the numbers, e.g. \`/otp 583921\``,
    });
  }

  // Store OTP in a GitHub Actions variable that the running workflow polls
  try {
    const ghRes = await fetch(
      `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/variables/CURRENT_OTP`,
      {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name: "CURRENT_OTP", value: otp }),
      }
    );

    // If variable doesn't exist yet, create it
    if (ghRes.status === 404) {
      await fetch(
        `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/variables`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
            Accept: "application/vnd.github+json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ name: "CURRENT_OTP", value: otp }),
        }
      );
    }

    return res.status(200).json({
      response_type: "in_channel",
      text: `:white_check_mark: OTP received from @${user_name}! Bot is logging in now...`,
    });
  } catch (e) {
    return res.status(200).json({
      response_type: "ephemeral",
      text: `:x: Could not send OTP to bot: ${e.message}`,
    });
  }
}
