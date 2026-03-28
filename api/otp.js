export const config = { runtime: "edge" };

export default async function handler(req) {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

  const text = await req.text();
  const params = new URLSearchParams(text);
  const user_name = params.get("user_name") || "user";
  const otp = (params.get("text") || "").trim();

  if (!otp || !/^\d{4,8}$/.test(otp)) {
    return new Response(
      JSON.stringify({
        response_type: "ephemeral",
        text: `:warning: Invalid OTP. Please type just the 6 digits.\nExample: \`/otp 583921\``,
      }),
      { headers: { "Content-Type": "application/json" } }
    );
  }

  try {
    // Try update first
    let ghRes = await fetch(
      `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/variables/CURRENT_OTP`,
      {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "User-Agent": "bhel-booking-bot",
        },
        body: JSON.stringify({ name: "CURRENT_OTP", value: otp }),
      }
    );

    // If not found, create it
    if (ghRes.status === 404) {
      ghRes = await fetch(
        `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/variables`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
            Accept: "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "bhel-booking-bot",
          },
          body: JSON.stringify({ name: "CURRENT_OTP", value: otp }),
        }
      );
    }

    return new Response(
      JSON.stringify({
        response_type: "in_channel",
        text: `:white_check_mark: OTP received from @${user_name}! Bot is logging in now...`,
      }),
      { headers: { "Content-Type": "application/json" } }
    );
  } catch (e) {
    return new Response(
      JSON.stringify({
        response_type: "ephemeral",
        text: `:x: Could not send OTP to bot: ${e.message}`,
      }),
      { headers: { "Content-Type": "application/json" } }
    );
  }
}
