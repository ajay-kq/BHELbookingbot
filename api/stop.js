export const config = { runtime: "edge" };

export default async function handler(req) {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

  const text = await req.text();
  const params = new URLSearchParams(text);
  const user_name = params.get("user_name") || "user";

  try {
    const listRes = await fetch(
      `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/runs?status=in_progress&per_page=5`,
      {
        headers: {
          Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "bhel-booking-bot",
        },
      }
    );

    if (listRes.ok) {
      const data = await listRes.json();
      const runs = (data.workflow_runs || []).filter(
        (r) => r.name === "BHEL Appointment Booking Bot"
      );

      if (runs.length === 0) {
        return new Response(
          JSON.stringify({
            response_type: "in_channel",
            text: `:white_circle: Bot is not running. Nothing to stop.`,
          }),
          { headers: { "Content-Type": "application/json" } }
        );
      }

      for (const run of runs) {
        await fetch(
          `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/runs/${run.id}/cancel`,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
              Accept: "application/vnd.github+json",
              "User-Agent": "bhel-booking-bot",
            },
          }
        );
      }

      return new Response(
        JSON.stringify({
          response_type: "in_channel",
          text: `:octagonal_sign: *Bot stopped* by @${user_name}\n${runs.length} run(s) cancelled.\nType \`/start\` tomorrow at 6:25 AM.`,
        }),
        { headers: { "Content-Type": "application/json" } }
      );
    }
  } catch (e) {
    return new Response(
      JSON.stringify({ response_type: "in_channel", text: `:x: Stop failed: ${e.message}` }),
      { headers: { "Content-Type": "application/json" } }
    );
  }

  return new Response(
    JSON.stringify({ response_type: "in_channel", text: `:x: Could not stop bot.` }),
    { headers: { "Content-Type": "application/json" } }
  );
}
