/** Добавляет Bearer token только запросам к явно разрешённым origin. */
export default async ({ page }) => {
  const token = process.env.API_BEARER_TOKEN;
  const origins = new Set(
    (process.env.API_BEARER_ORIGINS ?? "")
      .split(",")
      .map((value) => value.trim().replace(/\/$/, ""))
      .filter(Boolean),
  );

  if (!token || origins.size === 0) {
    return;
  }

  await page.route("**/*", async (route) => {
    const request = route.request();
    const origin = new URL(request.url()).origin;
    if (!origins.has(origin)) {
      await route.continue();
      return;
    }

    await route.continue({
      headers: {
        ...request.headers(),
        authorization: `Bearer ${token}`,
      },
    });
  });
};

