/**
 * Spec §17.3 E2E: upload -> HITL-0 -> HITL-1 -> validate facts -> approve summary -> decide (+UR) -> sign off,
 * driven through the real UI by each persona on the seeded synthetic claim.
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

const PW = "Demo!Passw0rd";
const SHOTS = process.env.SHOT_DIR ?? "e2e-screens";

async function as(browser: Browser, email: string): Promise<Page> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  return page;
}

async function waitFor(page: Page, url: string, name: string | RegExp) {
  await expect(async () => {
    await page.goto(url);
    await expect(page.getByRole("button", { name })).toBeVisible({ timeout: 4000 });
  }).toPass({ timeout: 90_000, intervals: [1000, 2000] });
}

test("full HITL workflow through the UI", async ({ browser }) => {
  // Summarization team starts processing the seeded claim
  const summ = await as(browser, "summ@claims.example");
  await summ.goto("/claims");
  await summ.getByText("WC-2024-PA-087341").click();
  await expect(summ).toHaveURL(/\/claims\/[0-9a-f-]{36}$/);
  const claimUrl = new URL(summ.url()).pathname;
  await summ.screenshot({ path: `${SHOTS}/01-dashboard-before.png`, fullPage: true });
  await summ.getByRole("button", { name: "Start processing" }).click();
  await expect(summ.getByText(/Paused for/)).toBeVisible({ timeout: 90_000 });
  await summ.screenshot({ path: `${SHOTS}/02-dashboard-paused-hitl0.png`, fullPage: true });

  // HITL-0 examiner confirms the employer conflict
  const examiner = await as(browser, "examiner@claims.example");
  await examiner.goto("/");
  await expect(examiner.getByText("HITL-0").first()).toBeVisible();
  await examiner.screenshot({ path: `${SHOTS}/03-work-queue.png`, fullPage: true });
  await waitFor(examiner, `${claimUrl}/baseline`, "Confirm and lock baseline");
  await expect(examiner.getByText(/claim metadata "Meridian Risk Partners LLC"/)).toBeVisible();
  await examiner.screenshot({ path: `${SHOTS}/04-hitl0-baseline.png`, fullPage: true });
  await examiner.getByRole("row", { name: /Employer/ }).getByRole("textbox").fill("Keystone Industrial Services");
  await examiner.getByRole("button", { name: "Confirm and lock baseline" }).click();

  // HITL-1 NCM approves the timeline
  const ncm = await as(browser, "ncm@claims.example");
  await waitFor(ncm, `${claimUrl}/timeline`, "Approve timeline");
  await expect(ncm.getByText(/MRI dated 2024-10-02 is referenced/)).toBeVisible();
  await ncm.screenshot({ path: `${SHOTS}/05-hitl1-timeline.png`, fullPage: true });
  await ncm.getByRole("button", { name: "Approve timeline" }).click();

  // HITL-2 clinical reviewer validates facts side by side with the source page
  const reviewer = await as(browser, "reviewer@claims.example");
  await waitFor(reviewer, `${claimUrl}/facts`, /Submit validation/);
  await reviewer.getByRole("row").nth(1).click();
  await expect(reviewer.locator("[data-testid=highlight]").first()).toBeVisible();
  await reviewer.screenshot({ path: `${SHOTS}/06-hitl2-facts.png`, fullPage: true });
  await reviewer.getByRole("checkbox", { name: "Select all pending" }).check();
  await reviewer.getByRole("button", { name: /Accept selected/ }).click();
  await expect(reviewer.getByRole("button", { name: /Submit validation \(0 remaining\)/ })).toBeVisible();
  await reviewer.getByRole("button", { name: /Submit validation/ }).click();

  // guideline findings are visible to the reviewer
  await expect(async () => {
    await reviewer.goto(`${claimUrl}/guidelines`);
    await expect(reviewer.getByText(/Physical therapy exceeds guideline/)).toBeVisible({ timeout: 4000 });
  }).toPass({ timeout: 90_000 });
  await reviewer.screenshot({ path: `${SHOTS}/07-guidelines.png`, fullPage: true });

  // HITL-3 NCM approves the one-page summary
  await waitFor(ncm, `${claimUrl}/summary`, "Approve and lock summaries");
  await ncm.screenshot({ path: `${SHOTS}/08-hitl3-summary.png`, fullPage: true });
  await ncm.getByRole("button", { name: "Approve and lock summaries" }).click();

  // HITL-4 UR determination by the clinical reviewer (parallel branch)
  await waitFor(reviewer, `${claimUrl}/decision`, /Record UR determination/);
  await reviewer.getByLabel("Determination").click();
  await reviewer.getByRole("option", { name: "non certified" }).click();
  await reviewer.getByLabel(/Clinical rationale/).fill("24 PT visits exceed the 16-visit guideline with no functional gain since visit 6; FCE recommends work hardening.");
  await reviewer.screenshot({ path: `${SHOTS}/09-hitl4-ur.png`, fullPage: true });
  await reviewer.getByRole("button", { name: /Record UR determination/ }).click();

  // HITL-4 claims decision with one-click flag approvals
  await waitFor(examiner, `${claimUrl}/decision`, /Approve all remaining/);
  await examiner.screenshot({ path: `${SHOTS}/10-hitl4-decision.png`, fullPage: true });
  await examiner.getByRole("button", { name: /Approve all remaining/ }).click();
  await examiner.getByRole("button", { name: "Start from draft" }).click();
  const outcomes = examiner.getByLabel("Outcome");
  await outcomes.nth(0).fill("Deny additional PT; authorize 4-week work hardening");
  await outcomes.nth(1).fill("Light duty within FCE restrictions; TTD continues if not accommodated");
  await examiner.getByRole("button", { name: /^Submit decision/ }).click();

  // HITL-5 supervisor sign-off (high-risk claim)
  const supervisor = await as(browser, "supervisor@claims.example");
  await waitFor(supervisor, `${claimUrl}/decision`, "Sign off and seal");
  await supervisor.getByLabel("Comments").fill("Reviewed decision record and evidence; approved.");
  await supervisor.screenshot({ path: `${SHOTS}/11-hitl5-signoff.png`, fullPage: true });
  await supervisor.getByRole("button", { name: "Sign off and seal" }).click();

  await expect(async () => {
    await supervisor.goto(claimUrl);
    await expect(supervisor.getByText(/Workflow complete/)).toBeVisible({ timeout: 4000 });
  }).toPass({ timeout: 90_000 });
  await expect(supervisor.getByText(/Keystone Industrial Services/).first()).toBeVisible(); // HITL-0 confirmed employer applied
  await supervisor.screenshot({ path: `${SHOTS}/12-dashboard-complete.png`, fullPage: true });
  await supervisor.goto(`${claimUrl}/chronology`);
  await expect(supervisor.getByText("turning point").first()).toBeVisible();
  await supervisor.screenshot({ path: `${SHOTS}/13-chronology.png`, fullPage: true });
  await supervisor.goto("/supervisor");
  await expect(supervisor.getByText("Pages processed")).toBeVisible();
  await supervisor.screenshot({ path: `${SHOTS}/14-supervisor.png`, fullPage: true });
  await supervisor.goto(`${claimUrl}/audit`);
  await expect(supervisor.getByText(/Chain verified/)).toBeVisible();
  await supervisor.screenshot({ path: `${SHOTS}/15-audit.png`, fullPage: true });

  // citation chip opens the source page with highlighted lines
  await supervisor.goto(`${claimUrl}/summary`);
  await supervisor.getByText("[1]", { exact: true }).first().click();
  await expect(supervisor.locator("[data-testid=highlight]").first()).toBeVisible();
  await supervisor.screenshot({ path: `${SHOTS}/16-citation-drawer.png` });
});
