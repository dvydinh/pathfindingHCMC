// Visual gate driver: captures the demo beats as PNGs (G1.3/G1.4/G4.x evidence).
import { chromium } from "playwright";

const OUT = process.env.OUT ?? "e2e/shots";
const BASE = process.env.BASE ?? "http://localhost:5173";
const mobile = process.argv.includes("--mobile");

const record = process.argv.includes("--video");
const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: mobile ? { width: 390, height: 780 } : { width: 1280, height: 800 },
  ...(record ? { recordVideo: { dir: "../../docs/media", size: { width: 1280, height: 800 } } } : {}),
});
const page = await ctx.newPage();
const sfx = mobile ? "_mobile" : "";
page.on("console", (m) => { if (m.type() === "error") console.log("console.error:", m.text()); });

// 1) load at t=0
await page.goto(`${BASE}/?t=0`, { waitUntil: "networkidle" });
await page.waitForTimeout(4000);
await page.screenshot({ path: `${OUT}/01_load_t0${sfx}.png` });

// 2) storm peak t=22
await page.goto(`${BASE}/?t=22`, { waitUntil: "networkidle" });
await page.waitForTimeout(4500);
await page.screenshot({ path: `${OUT}/02_peak_t22${sfx}.png` });

// 3) coverage layer on
await page.getByRole("checkbox").check();
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/03_coverage${sfx}.png` });
await page.getByRole("checkbox").uncheck();

// 4) vehicle switch to car
await page.getByRole("button", { name: /Ô tô|car/i }).click();
await page.waitForTimeout(2500);
await page.screenshot({ path: `${OUT}/04_vehicle_car${sfx}.png` });
await page.getByRole("button", { name: /Xe máy|motorbike/i }).click();
await page.waitForTimeout(1500);

// 5) click an edge near a flood hotspot -> inspector
await page.mouse.click(mobile ? 195 : 640, mobile ? 390 : 400);
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/05_inspector${sfx}.png` });

// 6) route via deterministic hook (moderate OD with a real detour at peak)
await page.goto(`${BASE}/?t=22&route=106.755,10.835,106.775,10.850`, { waitUntil: "networkidle" });
await page.waitForTimeout(9000);
await page.screenshot({ path: `${OUT}/06_routes${sfx}.png` });

// 7) ops panel
await page.getByRole("button", { name: /Vận hành|Operations/i }).click();
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/07_ops${sfx}.png` });

await ctx.close();
await browser.close();
console.log(record ? "screens + video captured" : "screens captured");
