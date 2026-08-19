// @ts-check
const { expect, test } = require("@playwright/test");

/**
 * End-to-end smoke test for the dess-crm frontend.
 *
 * Every /api/* call is mocked via page.route() so no backend is needed.
 * The test walks the full happy path:
 *   1. Login page loads
 *   2. Sign-in-with-Google click redirects (mocked) to /auth/success
 *   3. AuthSuccess fetches /users/me (mocked, intro_seen=false)
 *   4. Routes to /intro
 *   5. User clicks "Let's get to work" — PATCH /users/me/intro-seen
 *   6. Routes to home
 *   7. User types in the chat; /api/chat returns a mocked response
 *      with one contact card result
 *   8. Contact card renders with the mocked contact's name
 *
 * CommonJS (.js with require) because this workspace's Node (18.17) is
 * older than Playwright's ESM-loader requirement (18.19+). Bump to .ts
 * if Node gets upgraded.
 */

test("happy path: login -> intro -> dismiss -> chat -> contact card", async ({
  page,
}) => {
  // --- Mock every API call -------------------------------------------------
  let introSeenPatched = false;

  await page.route("**/api/auth/google", async (route) => {
    // Simulate the OAuth round-trip: send the user straight to the
    // frontend's /auth/success with a fake cookie.
    await route.fulfill({
      status: 302,
      headers: {
        Location: "/auth/success",
        "Set-Cookie": "dess_session=mock-session; Path=/; SameSite=Lax",
      },
      body: "",
    });
  });

  await page.route("**/api/users/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        email: "pat@example.com",
        name: "Pat Carter",
        role: "admin",
        intro_seen: introSeenPatched,
      }),
    });
  });

  await page.route("**/api/users/me/intro-seen", async (route) => {
    introSeenPatched = true;
    await route.fulfill({ status: 204, body: "" });
  });

  await page.route("**/api/chat", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        reply: "Found 1 Maritime contact.",
        tool_calls: [
          {
            name: "search_contacts",
            params: { primary_fund: "Maritime" },
            result: {
              count: 1,
              truncated: false,
              limit: 50,
              results: [
                {
                  id: 101,
                  name: "Admiral William Barrett (Ret.)",
                  company_name: "Mare Island Naval Shipyard LLC",
                  title: "CEO",
                  email: null,
                  cell_phone: null,
                  office_phone: null,
                  primary_fund: "Maritime",
                  contact_type: "Portfolio",
                  sectors: ["Shipbuilding", "Defense"],
                  is_private: false,
                  gender: "Male",
                  country: "United States",
                  lp_subtype: null,
                  fly_status: "Must Fly",
                  image_url: null,
                  ex_government: "Yes",
                  patina_overrides: null,
                },
              ],
            },
          },
        ],
        input_tokens_used: 500,
        output_tokens_used: 20,
      }),
    });
  });

  // --- 1. Login page loads -------------------------------------------------
  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "DIN Command Center",
  );
  await expect(
    page.getByRole("button", { name: /Sign in with Google/i }),
  ).toBeVisible();

  // --- 2-4. Click Sign in -> mocked redirect -> /auth/success -> /intro ---
  await page.getByRole("button", { name: /Sign in with Google/i }).click();

  // AuthSuccess fetches /users/me (intro_seen=false) and routes to /intro.
  await page.waitForURL("**/intro");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Welcome to the DIN team portal",
  );

  // --- 5-6. Dismiss intro -> home -----------------------------------------
  await page.getByRole("button", { name: /Let's get to work/i }).click();
  await page.waitForURL(/\/$/);

  // Chat input is the identifying element on Home.
  const chatInput = page.getByPlaceholder(/Type a question/i);
  await expect(chatInput).toBeVisible();

  // --- 7-8. Type a query -> assistant reply + contact card ----------------
  await chatInput.fill("show me Maritime contacts");
  await page.getByRole("button", { name: /^Send$/i }).click();

  // Contact card renders with the mocked contact's name.
  await expect(page.getByText("Admiral William Barrett (Ret.)")).toBeVisible({
    timeout: 5000,
  });

  // The assistant's reply is shown too.
  await expect(page.getByText(/Found 1 Maritime contact/i)).toBeVisible();
});
