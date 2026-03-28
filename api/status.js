export const config = { runtime: "edge" };

export default async function handler(req) {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405 });

  try {
    const res = await fetch(
      `https://api.github.com/repos/${process.env.GITHUB_REPO}/actions/runs?status=in_progress&per_page=5`,
      {
        headers: {
          Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "bhel-booking-bot",
        },
      }
    );

    if (res.ok) {
      const data = await res.json();
      const active = (data.workflow_runs || []).filter(
        (r) => r.name === "BHEL Appointment Booking Bot"
      );

      if (active.length > 0) {
        const run = active[0];
        const started = new Date(run.created_at).toLocaleTimeString("en-IN", {
          timeZone: "Asia/Kolkata",
          hour: "2-digit",
          minute: "2-digit",
        });
        return new Response(
          JSON.stringify({
            response_type: "in_channel",
            text: `:green_circle: *Bot is running*\nStarted at: *${started} IST*\nPolling every 30 seconds for slots.\nType \`/stop\` to stop it.`,
          }),
          { headers: { "Content-Type": "application/json" } }
        );
      } else {
        return new Response(
          JSON.stringify({
            response_type: "in_channel",
            text: `:white_circle: *Bot is not running*\nType \`/start\` at 6:25 AM to begin.`,
          }),
          { headers: { "Content-Type": "application/json" } }
        );
      }
    }
  } catch (e) {
    // fall through
  }

  return new Response(
    JSON.stringify({
      response_type: "in_channel",
      text: `:grey_question: Could not check status. Try again.`,
    }),
    { headers: { "Content-Type": "application/json" } }
  );
}
